"""Unit tests for LeadBusinessRules — the deterministic core of the agent.

Every test here is checkable by hand with a calculator and a stopwatch, per
the design principle stated in business_rules/lead_rules.py. No mocks, no
LLM, no I/O: pure function behaviour.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.lead import Lead, LeadPriority, LeadStatus, PaymentStatus
from tests.conftest import make_lead


# ---------------------------------------------------------------------------
# Mandatory fields
# ---------------------------------------------------------------------------

class TestMandatoryFields:
    def test_valid_lead_passes(self, rules):
        lead = make_lead()
        result = rules.validate_mandatory_fields(lead)
        assert result.is_valid is True
        assert result.violations == []

    def test_missing_fullname_fails(self, rules):
        lead = make_lead(fullname=" ")
        result = rules.validate_mandatory_fields(lead)
        assert result.is_valid is False
        assert any(v.rule == "mandatory_fullname" for v in result.violations)

    def test_missing_training_fails(self, rules):
        lead = make_lead(training=" ")
        result = rules.validate_mandatory_fields(lead)
        assert result.is_valid is False
        assert any(v.rule == "mandatory_training" for v in result.violations)

    def test_no_phone_and_no_email_fails(self, rules):
        lead = make_lead(phone=None, email=None)
        result = rules.validate_mandatory_fields(lead)
        assert result.is_valid is False
        assert any(v.rule == "mandatory_contact" for v in result.violations)

    def test_phone_only_is_sufficient(self, rules):
        lead = make_lead(phone="+21699999999", email=None)
        result = rules.validate_mandatory_fields(lead)
        assert result.is_valid is True

    def test_email_only_is_sufficient(self, rules):
        lead = make_lead(phone=None, email="a@b.com")
        result = rules.validate_mandatory_fields(lead)
        assert result.is_valid is True

    def test_multiple_violations_are_all_reported(self, rules):
        lead = make_lead(fullname=" ", training=" ", phone=None, email=None)
        result = rules.validate_mandatory_fields(lead)
        assert len(result.violations) == 3


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

class TestDuplicateDetection:
    def test_no_existing_leads_never_duplicate(self, rules):
        lead = make_lead()
        result = rules.check_duplicate(lead, existing_leads=[])
        assert result.is_duplicate is False

    def test_matching_phone_is_duplicate(self, rules):
        existing = make_lead(id="existing-1", phone="+21620000001")
        new = make_lead(id="new-1", phone="+21620000001", email="different@example.com")
        result = rules.check_duplicate(new, existing_leads=[existing])
        assert result.is_duplicate is True
        assert result.matched_field == "phone"
        assert result.existing_lead_id == "existing-1"

    def test_matching_email_is_duplicate(self, rules):
        existing = make_lead(id="existing-1", phone="+21611111111", email="same@example.com")
        new = make_lead(id="new-1", phone="+21622222222", email="same@example.com")
        result = rules.check_duplicate(new, existing_leads=[existing])
        assert result.is_duplicate is True
        assert result.matched_field == "email"

    def test_email_match_is_case_insensitive(self, rules):
        existing = make_lead(id="existing-1", email="Same@Example.com")
        new = make_lead(id="new-1", phone="+21600000000", email="same@example.com")
        result = rules.check_duplicate(new, existing_leads=[existing])
        assert result.is_duplicate is True

    def test_phone_takes_priority_over_email(self, rules):
        """If phone matches lead A but email matches lead B, phone wins —
        per the documented convenience-wrapper contract."""
        lead_a = make_lead(id="lead-a", phone="+21600000000", email="a@example.com")
        lead_b = make_lead(id="lead-b", phone="+21611111111", email="b@example.com")
        new = make_lead(id="new-1", phone="+21600000000", email="b@example.com")
        result = rules.check_duplicate(new, existing_leads=[lead_a, lead_b])
        assert result.existing_lead_id == "lead-a"
        assert result.matched_field == "phone"

    def test_does_not_match_itself(self, rules):
        lead = make_lead(id="lead-1", phone="+21600000000")
        result = rules.check_duplicate(lead, existing_leads=[lead])
        assert result.is_duplicate is False

    def test_duplicate_check_disabled_via_settings(self, settings, rules):
        settings.duplicate_check_enabled = False
        from app.business_rules.lead_rules import LeadBusinessRules

        disabled_rules = LeadBusinessRules(settings)
        existing = make_lead(id="existing-1", phone="+21600000000")
        new = make_lead(id="new-1", phone="+21600000000")
        result = disabled_rules.check_duplicate(new, existing_leads=[existing])
        assert result.is_duplicate is False


# ---------------------------------------------------------------------------
# Hot lead / age threshold
# ---------------------------------------------------------------------------

class TestHotLeadThreshold:
    def test_fresh_new_lead_is_not_hot(self, rules):
        lead = make_lead(status=LeadStatus.NEW, created_at=datetime.now(timezone.utc))
        assert rules.is_lead_older_than_hot_threshold(lead) is False

    def test_lead_past_2h_is_hot(self, rules):
        lead = make_lead(
            status=LeadStatus.NEW,
            created_at=datetime.now(timezone.utc) - timedelta(hours=3),
        )
        assert rules.is_lead_older_than_hot_threshold(lead) is True

    def test_already_contacted_lead_is_never_hot_by_age(self, rules):
        """Age-based hotness only applies to un-contacted NEW leads —
        once contacted, this rule must not re-fire."""
        lead = make_lead(
            status=LeadStatus.CONTACTED,
            created_at=datetime.now(timezone.utc) - timedelta(hours=10),
        )
        assert rules.is_lead_older_than_hot_threshold(lead) is False

    def test_threshold_is_configurable(self, settings):
        from app.business_rules.lead_rules import LeadBusinessRules

        settings.lead_hot_response_hours = 0.5
        strict_rules = LeadBusinessRules(settings)
        lead = make_lead(status=LeadStatus.NEW, created_at=datetime.now(timezone.utc) - timedelta(hours=1))
        assert strict_rules.is_lead_older_than_hot_threshold(lead) is True


# ---------------------------------------------------------------------------
# Payment overdue
# ---------------------------------------------------------------------------

class TestPaymentOverdue:
    def test_not_overdue_if_not_pending(self, rules):
        lead = make_lead(
            status=LeadStatus.CONFIRMED_UNPAID,
            payment_status=PaymentStatus.PAID,
            last_contact=datetime.now(timezone.utc) - timedelta(days=10),
        )
        assert rules.is_payment_overdue(lead) is False

    def test_not_overdue_before_threshold(self, rules):
        lead = make_lead(
            status=LeadStatus.CONFIRMED_UNPAID,
            payment_status=PaymentStatus.PENDING,
            last_contact=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert rules.is_payment_overdue(lead) is False

    def test_overdue_exactly_at_threshold(self, rules):
        lead = make_lead(
            status=LeadStatus.CONFIRMED_UNPAID,
            payment_status=PaymentStatus.PENDING,
            last_contact=datetime.now(timezone.utc) - timedelta(days=3),
        )
        assert rules.is_payment_overdue(lead) is True

    def test_overdue_past_threshold(self, rules):
        lead = make_lead(
            status=LeadStatus.CONFIRMED_UNPAID,
            payment_status=PaymentStatus.PENDING,
            last_contact=datetime.now(timezone.utc) - timedelta(days=7),
        )
        assert rules.is_payment_overdue(lead) is True

    def test_no_last_contact_is_never_overdue(self, rules):
        lead = make_lead(
            status=LeadStatus.CONFIRMED_UNPAID,
            payment_status=PaymentStatus.PENDING,
            last_contact=None,
        )
        assert rules.is_payment_overdue(lead) is False

    def test_days_overdue_count(self, rules):
        lead = make_lead(last_contact=datetime.now(timezone.utc) - timedelta(days=5))
        assert rules.days_overdue(lead) == 5


# ---------------------------------------------------------------------------
# Follow-up (J+1)
# ---------------------------------------------------------------------------

class TestFollowUpDue:
    def test_due_today_when_contacted_yesterday(self, rules):
        lead = make_lead(
            status=LeadStatus.CONTACTED,
            last_contact=datetime.now(timezone.utc) - timedelta(days=1, hours=1),
        )
        assert rules.is_follow_up_due_today(lead) is True

    def test_not_due_if_contacted_today(self, rules):
        lead = make_lead(status=LeadStatus.CONTACTED, last_contact=datetime.now(timezone.utc))
        assert rules.is_follow_up_due_today(lead) is False

    def test_not_due_if_status_is_not_contacted(self, rules):
        lead = make_lead(
            status=LeadStatus.NEW,
            last_contact=datetime.now(timezone.utc) - timedelta(days=1, hours=1),
        )
        assert rules.is_follow_up_due_today(lead) is False


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

class TestStatusTransitions:
    @pytest.mark.parametrize(
        "current,target,expected",
        [
            (LeadStatus.NEW, LeadStatus.QUALIFIED, True),
            (LeadStatus.NEW, LeadStatus.PAID, False),
            (LeadStatus.QUALIFIED, LeadStatus.ASSIGNED, True),
            (LeadStatus.ASSIGNED, LeadStatus.CONTACTED, True),
            (LeadStatus.CONTACTED, LeadStatus.CONFIRMED_UNPAID, True),
            (LeadStatus.CONTACTED, LeadStatus.NO_RESPONSE, True),
            (LeadStatus.CONFIRMED_UNPAID, LeadStatus.PAID, True),
            (LeadStatus.PAID, LeadStatus.NEW, False),  # terminal state
            (LeadStatus.ARCHIVED, LeadStatus.NEW, False),  # terminal state
            (LeadStatus.NEW, LeadStatus.NEW, True),  # no-op transition always allowed
        ],
    )
    def test_transition_matrix(self, rules, current, target, expected):
        assert rules.is_valid_transition(current, target) is expected

    def test_validate_transition_reports_allowed_targets(self, rules):
        result = rules.validate_transition(LeadStatus.PAID, LeadStatus.NEW)
        assert result.is_valid is False
        assert "PAID" in result.violations[0].message or "paid" in result.violations[0].message.lower()


# ---------------------------------------------------------------------------
# Priority computation
# ---------------------------------------------------------------------------

class TestPriorityComputation:
    def test_unscored_lead_gets_unscored_priority(self, rules):
        lead = make_lead(score=None)
        result = rules.compute_priority(lead)
        assert result.priority == LeadPriority.UNSCORED

    def test_high_score_is_p0(self, rules):
        lead = make_lead(score=80.0)
        result = rules.compute_priority(lead)
        assert result.priority == LeadPriority.P0
        assert result.is_hot is True

    def test_score_exactly_at_p0_threshold_is_p0(self, rules):
        lead = make_lead(score=75.0)
        result = rules.compute_priority(lead)
        assert result.priority == LeadPriority.P0

    def test_mid_score_is_p1(self, rules):
        lead = make_lead(score=50.0)
        result = rules.compute_priority(lead)
        assert result.priority == LeadPriority.P1

    def test_low_score_is_p2(self, rules):
        lead = make_lead(score=10.0)
        result = rules.compute_priority(lead)
        assert result.priority == LeadPriority.P2

    def test_thresholds_are_configurable(self, settings):
        from app.business_rules.lead_rules import LeadBusinessRules

        settings.priority_p0_score_threshold = 90.0
        custom_rules = LeadBusinessRules(settings)
        lead = make_lead(score=80.0)
        result = custom_rules.compute_priority(lead)
        assert result.priority == LeadPriority.P1  # would have been P0 with default threshold


# ---------------------------------------------------------------------------
# LLM necessity gate — the most important rule in the whole file
# ---------------------------------------------------------------------------

class TestRequiresLanguageUnderstanding:
    def test_structured_lead_never_needs_llm(self, rules):
        lead = make_lead(raw_message=None)
        assert rules.requires_language_understanding(lead) is False

    def test_empty_string_message_never_needs_llm(self, rules):
        lead = make_lead(raw_message="   ")
        assert rules.requires_language_understanding(lead) is False

    def test_free_text_message_needs_llm(self, rules):
        lead = make_lead(raw_message="Bonjour, je suis intéressé, ça commence quand ?")
        assert rules.requires_language_understanding(lead) is True


# ---------------------------------------------------------------------------
# Baseline score
# ---------------------------------------------------------------------------

class TestBaselineScore:
    @pytest.mark.parametrize(
        "source,expected",
        [("referral", 65.0), ("meta_ads", 50.0), ("website", 45.0), ("manual", 35.0), ("unknown_source", 30.0)],
    )
    def test_baseline_by_source(self, rules, source, expected):
        lead = make_lead(source=source)
        assert rules.compute_baseline_score(lead) == expected

    def test_urgency_adjustment_never_exceeds_100(self, rules):
        assert rules.adjust_score_for_urgency(95.0, "high") == 100.0

    def test_urgency_adjustment_never_below_0(self, rules):
        assert rules.adjust_score_for_urgency(5.0, "low") == 0.0

    def test_medium_urgency_small_boost(self, rules):
        assert rules.adjust_score_for_urgency(50.0, "medium") == 55.0
