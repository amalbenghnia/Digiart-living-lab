"""Service-level tests. These exercise the orchestration logic, with the LLM
replaced by FakeLLMProvider (see conftest.py) so the suite stays fast,
deterministic, and free — never a real network call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.exceptions.custom_exceptions import BudgetExceededError, DuplicateLeadError, ValidationError
from app.models.lead import LeadPriority, LeadStatus, PaymentStatus
from app.services.duplicate_service import DuplicateService
from app.services.priority_service import PriorityService
from tests.conftest import make_lead


# ---------------------------------------------------------------------------
# QualificationService — the LLM gate is the single most important behaviour
# to prove in this whole project.
# ---------------------------------------------------------------------------

class TestQualificationServiceGate:
    def test_structured_lead_never_calls_llm(self, qualification_service, fake_llm):
        lead = make_lead(raw_message=None)
        result = qualification_service.qualify(lead)
        assert result is None
        assert fake_llm.calls == []  # the network was never touched

    def test_free_text_lead_calls_llm_exactly_once(self, qualification_service, fake_llm):
        lead = make_lead(raw_message="Bonjour, quand commence la formation ?")
        result = qualification_service.qualify(lead)
        assert result is not None
        assert len(fake_llm.calls) == 1

    def test_llm_output_is_parsed_into_typed_schema(self, qualification_service):
        lead = make_lead(raw_message="Je veux payer maintenant.")
        result = qualification_service.qualify(lead)
        assert result.intent in {"information_request", "ready_to_pay", "objection", "complaint", "other"}
        assert result.urgency in {"low", "medium", "high"}
        assert result.summary

    def test_malformed_llm_output_raises_validation_error(self, qualification_service, fake_llm):
        from app.exceptions.custom_exceptions import LLMValidationError

        fake_llm.next_response = "this is not json at all"
        lead = make_lead(raw_message="Bonjour")
        with pytest.raises(LLMValidationError):
            qualification_service.qualify(lead)

    def test_llm_output_missing_required_field_raises(self, qualification_service, fake_llm):
        from app.exceptions.custom_exceptions import LLMValidationError

        fake_llm.next_response = '{"intent": "information_request"}'  # missing urgency/summary/action
        lead = make_lead(raw_message="Bonjour")
        with pytest.raises(LLMValidationError):
            qualification_service.qualify(lead)

    def test_quota_exceeded_blocks_llm_call(self, rules, fake_llm):
        from app.interfaces.rag import NullRAGProvider
        from app.services.qualification_service import QualificationService
        from app.utils.rate_limiter import HourlyQuota

        tiny_quota = HourlyQuota(max_calls_per_hour=1)
        service = QualificationService(rules, fake_llm, NullRAGProvider(), tiny_quota)

        lead1 = make_lead(id="l1", raw_message="premier message")
        lead2 = make_lead(id="l2", raw_message="deuxième message")

        service.qualify(lead1)  # consumes the only slot
        with pytest.raises(BudgetExceededError):
            service.qualify(lead2)
        assert len(fake_llm.calls) == 1  # the second call never reached the LLM


# ---------------------------------------------------------------------------
# DuplicateService
# ---------------------------------------------------------------------------

class TestDuplicateService:
    def test_detects_duplicate_against_seeded_data(self, seeded_repository, rules):
        service = DuplicateService(seeded_repository, rules)
        new_lead = make_lead(id="brand-new", phone="+21620000001")  # matches lead-001
        result = service.check(new_lead)
        assert result.is_duplicate is True
        assert result.existing_lead_id == "lead-001"

    def test_no_duplicate_for_unique_contact_info(self, seeded_repository, rules):
        service = DuplicateService(seeded_repository, rules)
        new_lead = make_lead(id="brand-new", phone="+21699999999", email="unique@example.com")
        result = service.check(new_lead)
        assert result.is_duplicate is False


# ---------------------------------------------------------------------------
# PriorityService
# ---------------------------------------------------------------------------

class TestPriorityService:
    def test_compute_and_persist_updates_repository(self, empty_repository, rules):
        service = PriorityService(empty_repository, rules)
        lead = make_lead(id="p-lead", score=80.0)
        empty_repository.create_lead(lead)

        updated, result = service.compute_and_persist(lead)

        assert result.priority == LeadPriority.P0
        assert empty_repository.get_lead_by_id("p-lead").priority == LeadPriority.P0


# ---------------------------------------------------------------------------
# LeadService — full pipeline, end to end against the prototype repository
# ---------------------------------------------------------------------------

class TestLeadServiceRegisterNewLead:
    def test_valid_lead_is_persisted(self, lead_service, seeded_repository):
        lead = make_lead(id="fresh-1", phone="+21677777777", email="fresh@example.com")
        created = lead_service.register_new_lead(lead)
        assert seeded_repository.get_lead_by_id(created.id) is not None

    def test_invalid_lead_raises_validation_error(self, lead_service):
        lead = make_lead(id="bad-1", fullname=" ")
        with pytest.raises(ValidationError):
            lead_service.register_new_lead(lead)

    def test_duplicate_lead_raises_and_is_not_persisted(self, lead_service, seeded_repository):
        # lead-001 in the seed data has phone +21620000001
        dup = make_lead(id="dup-1", phone="+21620000001")
        with pytest.raises(DuplicateLeadError):
            lead_service.register_new_lead(dup)
        assert seeded_repository.get_lead_by_id("dup-1") is None


class TestLeadServiceAnalysePipeline:
    def test_hot_lead_gets_p0_and_a_call_task(self, lead_service, seeded_repository):
        """lead-001 in the seed data: source=meta_ads (baseline 50) with a
        raw_message whose fake LLM urgency is 'medium' (+5) -> score 55,
        which lands P1 by default thresholds. We drive score high enough
        here explicitly to prove the P0 escalation path end-to-end."""
        lead = seeded_repository.get_lead_by_id("lead-001")
        boosted = lead.model_copy(update={"score": 90.0})
        seeded_repository.update_lead(boosted)

        result = lead_service.analyse_lead("lead-001")

        assert result.priority == LeadPriority.P0
        tasks = seeded_repository.get_tasks_for_lead("lead-001")
        assert any(t.type == "call_lead" for t in tasks)

    def test_structured_lead_gets_baseline_score_without_llm(self, lead_service, seeded_repository, fake_llm):
        # lead-002 has no raw_message in the seed data
        result = lead_service.analyse_lead("lead-002")
        assert result.score is not None  # baseline score was applied
        assert fake_llm.calls == []

    def test_overdue_payment_lead_gets_reminder_task(self, lead_service, seeded_repository):
        # lead-004 in the seed data is CONFIRMED_UNPAID, last_contact 4 days ago
        result = lead_service.analyse_lead("lead-004")
        tasks = seeded_repository.get_tasks_for_lead("lead-004")
        assert any(t.type == "payment_reminder" for t in tasks)

    def test_repeated_analysis_reuses_open_tasks(self, lead_service, seeded_repository):
        lead = seeded_repository.get_lead_by_id("lead-001")
        seeded_repository.update_lead(lead.model_copy(update={"score": 90.0}))

        lead_service.analyse_lead("lead-001")
        lead_service.analyse_lead("lead-001")

        tasks = seeded_repository.get_tasks_for_lead("lead-001")
        assert len([task for task in tasks if task.type == "call_lead"]) == 1

    def test_unknown_lead_raises(self, lead_service):
        with pytest.raises(ValueError):
            lead_service.analyse_lead("does-not-exist")


class TestLeadServiceStatusTransition:
    def test_valid_transition_succeeds(self, lead_service, seeded_repository):
        updated = lead_service.update_lead_status("lead-002", LeadStatus.QUALIFIED)
        assert updated.status == LeadStatus.QUALIFIED

    def test_invalid_transition_raises(self, lead_service):
        # lead-004 is CONFIRMED_UNPAID -> jumping straight to NEW is not allowed
        with pytest.raises(ValidationError):
            lead_service.update_lead_status("lead-004", LeadStatus.NEW)
