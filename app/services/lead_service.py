"""LeadService: the orchestrator. This is the only service that calls the
others in sequence — it contains no business logic of its own beyond
ordering the pipeline, so the pipeline order itself stays easy to audit:

    1. Validate mandatory fields         (business_rules, no LLM)
    2. Check duplicate                   (business_rules, no LLM)
    3. Persist the lead
    4. Qualify (LLM only if raw_message present)
    5. Compute priority                  (business_rules, no LLM)
    6. If hot (P0): create a call task + notify
    7. If payment overdue: create a reminder task + notify
    8. Trigger dashboard + reporting automation hooks
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.business_rules.lead_rules import LeadBusinessRules
from app.core.logging import get_logger, log_event
from app.exceptions.custom_exceptions import DuplicateLeadError, ValidationError
from app.models.lead import Lead, LeadPriority, LeadStatus
from app.repositories.base_repository import LeadRepository
from app.services.automation_service import AutomationService
from app.services.duplicate_service import DuplicateService
from app.services.notification_service import NotificationService
from app.services.priority_service import PriorityService
from app.services.qualification_service import QualificationService
from app.services.task_service import TaskService

logger = get_logger(__name__)


class LeadService:
    def __init__(
        self,
        repository: LeadRepository,
        rules: LeadBusinessRules,
        duplicate_service: DuplicateService,
        qualification_service: QualificationService,
        priority_service: PriorityService,
        task_service: TaskService,
        notification_service: NotificationService,
        automation_service: AutomationService,
    ):
        self._repository = repository
        self._rules = rules
        self._duplicate_service = duplicate_service
        self._qualification_service = qualification_service
        self._priority_service = priority_service
        self._task_service = task_service
        self._notification_service = notification_service
        self._automation_service = automation_service

    # -- Read operations --------------------------------------------------------

    def get_all_leads(self, sort_by: str | None = None) -> list[Lead]:
        leads = self._repository.get_all_leads()
        if sort_by == "priority":
            # Presentation-only ordering (P0 first, then by score descending
            # within the same priority) — not a business rule, so it lives
            # here rather than in business_rules/: it has no side effect,
            # it only changes the order the caller sees.
            rank = {"P0": 0, "P1": 1, "P2": 2, "unscored": 3}
            leads = sorted(
                leads,
                key=lambda lead: (rank.get(lead.priority, 9), -(lead.score or 0)),
            )
        return leads

    def get_lead(self, lead_id: str) -> Lead | None:
        return self._repository.get_lead_by_id(lead_id)

    def get_leads_due_for_followup(self, today: datetime | None = None) -> list[Lead]:
        """Returns all leads that have a next_followup_date set to today or earlier,
        and are in a status where follow-ups still make sense."""
        today_date = (today or datetime.now(timezone.utc)).date()
        due_leads = []
        for lead in self._repository.get_all_leads():
            if lead.status in (LeadStatus.PAID.value, LeadStatus.ARCHIVED.value):
                continue
            if lead.next_followup_date:
                try:
                    followup_date = datetime.strptime(str(lead.next_followup_date), "%Y-%m-%d").date()
                    if followup_date <= today_date:
                        due_leads.append(lead)
                except ValueError:
                    continue
        return due_leads

    # -- Write operations ---------------------------------------------------------

    def register_new_lead(self, lead: Lead) -> Lead:
        """Step 1-3 of the pipeline: validate, dedupe, persist. Raises on
        failure — the caller (API layer) maps exceptions to HTTP responses."""
        validation = self._rules.validate_mandatory_fields(lead)
        log_event(
            logger, "business_rule", "Mandatory fields validated",
            lead_id=lead.id, is_valid=validation.is_valid,
        )
        if not validation.is_valid:
            raise ValidationError("; ".join(v.message for v in validation.violations))

        dup = self._duplicate_service.check(lead)
        if dup.is_duplicate:
            self._notification_service.notify_duplicate_detected(lead, dup.existing_lead_id or "")
            raise DuplicateLeadError(
                field=dup.matched_field or "unknown",
                value=dup.matched_value or "unknown",
                existing_lead_id=dup.existing_lead_id or "unknown",
            )

        created = self._repository.create_lead(lead)
        self._automation_service.trigger_dashboard(created.id)
        self._automation_service.trigger_reporting(created.id, event_type="lead_created")
        return created

    def analyse_lead(self, lead_id: str) -> Lead:
        """The full pipeline (steps 4-8): qualify, prioritize, route, notify.
        This is what POST /lead/analyse calls — it is idempotent-ish (safe to
        re-run; re-running just recomputes and re-persists the same fields)."""
        lead = self._repository.get_lead_by_id(lead_id)
        if lead is None:
            raise ValueError(f"Lead not found: {lead_id}")

        # Step 4: qualification (LLM only if there is free text to understand)
        qualification = self._qualification_service.qualify(lead)
        if qualification is not None:
            score = lead.score if lead.score is not None else self._rules.compute_baseline_score(lead)
            score = self._rules.adjust_score_for_urgency(score, qualification.urgency)
            lead = lead.model_copy(
                update={
                    "notes": qualification.summary,
                    "next_action": qualification.suggested_next_action,
                    "score": score,
                }
            )
            lead = self._repository.update_lead(lead)
        elif lead.score is None:
            # No free text to qualify, but the lead still needs a starting
            # score to be routable — baseline rule, never a guess.
            lead = lead.model_copy(update={"score": self._rules.compute_baseline_score(lead)})
            lead = self._repository.update_lead(lead)

        # Step 5: priority (pure business rules)
        lead, priority_result = self._priority_service.compute_and_persist(lead)

        # Step 6: hot lead escalation
        if priority_result.priority == LeadPriority.P0:
            task, task_created = self._task_service.get_or_create_call_task(lead, priority_result)
            if task_created:
                self._automation_service.trigger_create_task(
                    lead_id=lead.id, task_id=task.id,
                    assigned_to=task.assigned_to, priority=task.priority,
                )
                self._notification_service.notify_hot_lead(lead)

        # Step 7: payment overdue escalation
        if self._rules.is_payment_overdue(lead):
            days = self._rules.days_overdue(lead)
            task, task_created = self._task_service.get_or_create_payment_reminder_task(lead, days)
            if task_created:
                self._automation_service.trigger_create_task(
                    lead_id=lead.id, task_id=task.id,
                    assigned_to=task.assigned_to, priority=task.priority,
                )
                self._notification_service.notify_payment_overdue(lead, days)

        # Step 8: always refresh the dashboard + reporting feed
        self._automation_service.trigger_dashboard(lead.id)
        self._automation_service.trigger_reporting(lead.id, event_type="lead_analysed")

        return lead

    def update_lead_status(self, lead_id: str, target_status: LeadStatus) -> Lead:
        lead = self._repository.get_lead_by_id(lead_id)
        if lead is None:
            raise ValueError(f"Lead not found: {lead_id}")

        validation = self._rules.validate_transition(lead.status, target_status)
        if not validation.is_valid:
            raise ValidationError("; ".join(v.message for v in validation.violations))

        updated = lead.model_copy(update={"status": target_status})
        return self._repository.update_lead(updated)

    def mark_lead_called(self, lead_id: str, called_by: str) -> Lead:
        """Mark a lead as called — updates called flag, timestamp, caller,
        transitions status to CONTACTED, and records last_contact."""
        lead = self._repository.get_lead_by_id(lead_id)
        if lead is None:
            raise ValueError(f"Lead not found: {lead_id}")
        now = datetime.now(timezone.utc)
        updated = lead.model_copy(update={
            "called": True,
            "called_at": now,
            "called_by": called_by,
            "status": "contacted",
            "last_contact": now,
        })
        persisted = self._repository.update_lead(updated)
        self._automation_service.trigger_reporting(lead_id, event_type="lead_called")
        return persisted

    def get_uncalled_urgent_leads(self) -> list[dict]:
        """Return P0 leads that have NOT been called and are older than the
        hot-lead response threshold (default 2h).  Each entry includes the
        lead plus how many hours it has been waiting."""
        leads = self._repository.get_all_leads()
        now = datetime.now(timezone.utc)
        results = []
        for lead in leads:
            if lead.priority != "P0":
                continue
            if lead.called:
                continue
            if not self._rules.is_lead_older_than_hot_threshold(lead, now):
                continue
            hours_waiting = (now - lead.created_at).total_seconds() / 3600
            results.append({
                "id": lead.id,
                "fullname": lead.fullname,
                "phone": lead.phone,
                "email": lead.email,
                "training": lead.training,
                "priority": lead.priority,
                "score": lead.score,
                "created_at": lead.created_at.isoformat(),
                "hours_waiting": round(hours_waiting, 1),
                "assigned_to": "Ines Zouaoui",
            })
        return results
