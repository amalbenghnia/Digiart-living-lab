"""Business rules for the Lead Agent.

CRITICAL DESIGN PRINCIPLE: nothing in this file calls an LLM. Every rule here
is a deterministic Python function that a non-technical person could verify
by hand with a calculator and a stopwatch. This is what makes the agent
predictable, cheap, and testable — the LLM is only ever consulted for the
one thing rules cannot do: understanding free text (see AIDecisionService).

Each rule returns a small, explicit result object rather than a bare bool,
so the caller (and the logs) always know *why* a rule fired.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.models.lead import Lead, LeadPriority, LeadStatus, PaymentStatus

# Result objects

@dataclass
class RuleViolation:
    rule: str
    message: str


@dataclass
class ValidationResult:
    is_valid: bool
    violations: list[RuleViolation] = field(default_factory=list)

    def add(self, rule: str, message: str) -> None:
        self.is_valid = False
        self.violations.append(RuleViolation(rule=rule, message=message))


@dataclass
class DuplicateCheckResult:
    is_duplicate: bool
    matched_field: str | None = None
    matched_value: str | None = None
    existing_lead_id: str | None = None


@dataclass
class PriorityResult:
    priority: LeadPriority
    reason: str
    is_hot: bool


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

class LeadBusinessRules:
    """Stateless rule engine. All thresholds come from Settings so they can
    be retuned from .env without a code change or a redeploy of logic."""

    def __init__(self, settings: Settings):
        self._settings = settings

    # -- Rule 1: mandatory fields -------------------------------------------------
    def validate_mandatory_fields(self, lead: Lead) -> ValidationResult:
        """A lead MUST have a full name, a training of interest, and at
        least one contact channel (phone OR email). This is checked before
        anything else — a lead that fails this is never scored or routed."""
        result = ValidationResult(is_valid=True)

        if not lead.fullname or not lead.fullname.strip():
            result.add("mandatory_fullname", "Full name is missing")

        if not lead.training or not lead.training.strip():
            result.add("mandatory_training", "Requested training is missing")

        if not lead.has_minimum_contact_info():
            result.add(
                "mandatory_contact",
                "Lead has neither a phone number nor an email — cannot be contacted",
            )

        return result

    # -- Rule 2: duplicate detection (phone) --------------------------------------
    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Strip all non-digit characters so that '+21650000001', '21650000001',
        and '216 500 00 001' all compare equal.  Google Sheets frequently
        strips the leading '+' or inserts spaces, so this is essential for
        reliable duplicate detection."""
        return "".join(c for c in phone if c.isdigit())

    def check_duplicate_phone(self, lead: Lead, existing_leads: list[Lead]) -> DuplicateCheckResult:
        if not self._settings.duplicate_check_enabled or not lead.phone:
            return DuplicateCheckResult(is_duplicate=False)

        normalized_new = self._normalize_phone(lead.phone)
        for other in existing_leads:
            if other.id == lead.id:
                continue
            if other.phone and self._normalize_phone(other.phone) == normalized_new:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    matched_field="phone",
                    matched_value=lead.phone,
                    existing_lead_id=other.id,
                )
        return DuplicateCheckResult(is_duplicate=False)

    # -- Rule 3: duplicate detection (email) --------------------------------------
    def check_duplicate_email(self, lead: Lead, existing_leads: list[Lead]) -> DuplicateCheckResult:
        if not self._settings.duplicate_check_enabled or not lead.email:
            return DuplicateCheckResult(is_duplicate=False)

        for other in existing_leads:
            if other.id == lead.id:
                continue
            if other.email and other.email.lower() == lead.email.lower():
                return DuplicateCheckResult(
                    is_duplicate=True,
                    matched_field="email",
                    matched_value=lead.email,
                    existing_lead_id=other.id,
                )
        return DuplicateCheckResult(is_duplicate=False)

    def check_duplicate(self, lead: Lead, existing_leads: list[Lead]) -> DuplicateCheckResult:
        """Convenience wrapper: phone takes priority over email as the match key,
        since a wrong/shared email is more common than a wrong phone number."""
        phone_result = self.check_duplicate_phone(lead, existing_leads)
        if phone_result.is_duplicate:
            return phone_result
        return self.check_duplicate_email(lead, existing_leads)

    # -- Rule 4: lead age -> hot lead (P0) -----------------------------------------
    def is_lead_older_than_hot_threshold(self, lead: Lead, now: datetime | None = None) -> bool:
        """True once a NEW, un-contacted lead has been sitting for longer than
        the configured hot-lead window (default 2h) — used to trigger an
        escalation notification, not to change priority by itself."""
        now = now or datetime.now(timezone.utc)
        age = now - lead.created_at
        threshold = timedelta(hours=self._settings.lead_hot_response_hours)
        return lead.status == LeadStatus.NEW and age > threshold

    # -- Rule 5: payment overdue --------------------------------------------------
    def is_payment_overdue(self, lead: Lead, now: datetime | None = None) -> bool:
        """A lead confirmed but unpaid for more than N days (default 3) is overdue.
        This is the trigger for the automated relance workflow."""
        if lead.payment_status != PaymentStatus.PENDING:
            return False
        if lead.status != LeadStatus.CONFIRMED_UNPAID:
            return False
        if lead.last_contact is None:
            return False

        now = now or datetime.now(timezone.utc)
        days_pending = (now - lead.last_contact).days
        return days_pending >= self._settings.payment_overdue_days

    def days_overdue(self, lead: Lead, now: datetime | None = None) -> int:
        if lead.last_contact is None:
            return 0
        now = now or datetime.now(timezone.utc)
        return max((now - lead.last_contact).days, 0)

    # -- Rule 6: follow-up due today (J+1 logic) -----------------------------------
    def is_follow_up_due_today(self, lead: Lead, today: datetime | None = None) -> bool:
        """Business rule: 'Relance / Date = J+1' — a lead contacted yesterday
        with no response is due for a follow-up today."""
        if lead.last_contact is None:
            return False
        today = today or datetime.now(timezone.utc)
        offset = timedelta(days=self._settings.follow_up_offset_days)
        due_date = lead.last_contact + offset
        return due_date.date() <= today.date() and lead.status == LeadStatus.CONTACTED

    def compute_initial_followup_date(self, days_to_start: int | None) -> str:
        """Determines when a NEW lead should be followed up, based on agenda urgency.
        - Starts in <= 7 days: Follow up today (0 days)
        - Starts in 8-14 days: Follow up tomorrow (1 day)
        - Starts in > 14 days: Follow up in 3 days
        - Unknown: Follow up tomorrow (1 day)
        """
        from datetime import datetime, timedelta, timezone
        if days_to_start is None:
            delay = 1
        elif days_to_start <= 7:
            delay = 0
        elif days_to_start <= 14:
            delay = 1
        else:
            delay = 3
        return (datetime.now(timezone.utc) + timedelta(days=delay)).strftime("%Y-%m-%d")

    # -- Rule 7: status transitions -------------------------------------------------
    _ALLOWED_TRANSITIONS: dict[LeadStatus, set[LeadStatus]] = {
        LeadStatus.NEW: {LeadStatus.QUALIFIED, LeadStatus.CONTACTED, LeadStatus.ARCHIVED},
        LeadStatus.QUALIFIED: {LeadStatus.ASSIGNED, LeadStatus.ARCHIVED},
        LeadStatus.ASSIGNED: {LeadStatus.CONTACTED, LeadStatus.ARCHIVED},
        LeadStatus.CONTACTED: {
            LeadStatus.CONFIRMED_UNPAID,
            LeadStatus.NO_RESPONSE,
            LeadStatus.ARCHIVED,
        },
        LeadStatus.CONFIRMED_UNPAID: {LeadStatus.PAID, LeadStatus.ARCHIVED},
        LeadStatus.NO_RESPONSE: {LeadStatus.CONTACTED, LeadStatus.ARCHIVED},
        LeadStatus.PAID: set(),  # terminal state
        LeadStatus.ARCHIVED: set(),  # terminal state
    }

    def is_valid_transition(self, current: LeadStatus, target: LeadStatus) -> bool:
        if current == target:
            return True
        return target in self._ALLOWED_TRANSITIONS.get(current, set())

    def validate_transition(self, current: LeadStatus, target: LeadStatus) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        if not self.is_valid_transition(current, target):
            result.add(
                "invalid_status_transition",
                f"Cannot move a lead from '{current}' to '{target}'. "
                f"Allowed targets from '{current}': "
                f"{sorted(s.value for s in self._ALLOWED_TRANSITIONS.get(current, set()))}",
            )
        return result

    # -- Rule 8: priority computation (P0 / P1 / P2) 
    def compute_priority(self, lead: Lead, now: datetime | None = None, days_to_start: int | None = None) -> PriorityResult:
        """Priority is computed from the score (set by QualificationService,
        itself possibly informed by the LLM) crossed with the hot-lead age
        rule, and optionally boosted if the requested course starts very soon."""
        is_hot_by_age = self.is_lead_older_than_hot_threshold(lead, now)
        
        # Agenda Boost: If course starts in <= 7 days, it's an absolute priority.
        if days_to_start is not None and days_to_start <= 7:
            return PriorityResult(
                priority=LeadPriority.P0,
                reason=f"Agenda Boost: Course starts in {days_to_start} days.",
                is_hot=True,
            )

        if lead.score is None:
            return PriorityResult(
                priority=LeadPriority.UNSCORED,
                reason="No score available yet — qualification pending",
                is_hot=is_hot_by_age,
            )

        if lead.score >= self._settings.priority_p0_score_threshold:
            return PriorityResult(
                priority=LeadPriority.P0,
                reason=f"Score {lead.score} >= P0 threshold "
                f"({self._settings.priority_p0_score_threshold})",
                is_hot=True,
            )
        if lead.score >= self._settings.priority_p1_score_threshold:
            return PriorityResult(
                priority=LeadPriority.P1,
                reason=f"Score {lead.score} >= P1 threshold "
                f"({self._settings.priority_p1_score_threshold})",
                is_hot=is_hot_by_age,
            )
        return PriorityResult(
            priority=LeadPriority.P2,
            reason=f"Score {lead.score} below P1 threshold",
            is_hot=is_hot_by_age,
        )

    # -- Decision: does this request need the LLM at all? ---------------------------
    def requires_language_understanding(self, lead: Lead) -> bool:
        """The single gate that decides whether the LLM layer is invoked.
        Per spec: only free text (WhatsApp message, email body, open notes)
        justifies a call. Structured fields never do."""
        return bool(lead.raw_message and lead.raw_message.strip())


    _SOURCE_BASELINE_SCORE: dict[str, float] = {
        "referral": 65.0,
        "meta_ads": 50.0,
        "website": 45.0,
        "manual": 35.0,
    }
    _URGENCY_SCORE_DELTA: dict[str, float] = {
        "high": 25.0,
        "medium": 5.0,
        "low": -10.0,
    }

    def compute_baseline_score(self, lead: Lead) -> float:
        return self._SOURCE_BASELINE_SCORE.get(lead.source, 30.0)

    def adjust_score_for_urgency(self, base_score: float, urgency: str) -> float:
        delta = self._URGENCY_SCORE_DELTA.get(urgency, 0.0)
        return max(0.0, min(100.0, base_score + delta))
