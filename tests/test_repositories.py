"""Tests for PrototypeLeadRepository.

These tests exist for two reasons:
1. Verify the in-memory prototype behaves correctly on its own.
2. Document the CONTRACT (LeadRepository interface) precisely enough that
   whoever writes GoogleSheetLeadRepository's tests later can copy this
   file, swap the fixture, and expect the exact same assertions to pass —
   that is the whole point of coding against an interface.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.lead import LeadStatus
from app.models.task import Task, TaskStatus, TaskType
from app.repositories.prototype_repository import PrototypeLeadRepository
from tests.conftest import make_lead


class TestSeedData:
    def test_seed_creates_five_leads(self, seeded_repository):
        assert len(seeded_repository.get_all_leads()) == 5

    def test_seed_contains_intentional_duplicate_phone(self, seeded_repository):
        """lead-001 and lead-003 share a phone on purpose — this is what
        the DuplicateService tests exercise against."""
        leads = seeded_repository.get_all_leads()
        phones = [l.phone for l in leads if l.id in {"lead-001", "lead-003"}]
        assert phones[0] == phones[1]

    def test_empty_repository_has_no_leads(self, empty_repository):
        assert empty_repository.get_all_leads() == []


class TestCrud:
    def test_create_and_get_lead(self, empty_repository):
        lead = make_lead(id="new-lead")
        empty_repository.create_lead(lead)
        fetched = empty_repository.get_lead_by_id("new-lead")
        assert fetched is not None
        assert fetched.fullname == lead.fullname

    def test_create_lead_without_id_generates_uuid(self, empty_repository):
        lead = make_lead(id="")
        created = empty_repository.create_lead(lead)
        assert created.id != ""
        assert len(created.id) > 0

    def test_get_missing_lead_returns_none(self, empty_repository):
        assert empty_repository.get_lead_by_id("does-not-exist") is None

    def test_update_lead_persists_changes(self, empty_repository):
        lead = make_lead(id="lead-x", fullname="Original Name")
        empty_repository.create_lead(lead)
        updated = lead.model_copy(update={"fullname": "Updated Name"})
        empty_repository.update_lead(updated)
        assert empty_repository.get_lead_by_id("lead-x").fullname == "Updated Name"

    def test_update_priority(self, empty_repository):
        lead = make_lead(id="lead-y")
        empty_repository.create_lead(lead)
        empty_repository.update_priority("lead-y", "P0", 90.0)
        fetched = empty_repository.get_lead_by_id("lead-y")
        assert fetched.priority == "P0"
        assert fetched.score == 90.0

    def test_get_new_leads_filters_by_status(self, empty_repository):
        empty_repository.create_lead(make_lead(id="a", status=LeadStatus.NEW))
        empty_repository.create_lead(make_lead(id="b", status=LeadStatus.PAID))
        new_leads = empty_repository.get_new_leads()
        assert len(new_leads) == 1
        assert new_leads[0].id == "a"


class TestTasks:
    def test_create_and_fetch_task(self, empty_repository):
        task = Task(
            id="task-1",
            lead_id="lead-1",
            type=TaskType.CALL_LEAD,
            assigned_to="Ines Zouaoui",
            status=TaskStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        empty_repository.create_task(task)
        tasks = empty_repository.get_tasks_for_lead("lead-1")
        assert len(tasks) == 1
        assert tasks[0].id == "task-1"

    def test_tasks_for_unrelated_lead_are_not_returned(self, empty_repository):
        task = Task(
            id="task-1", lead_id="lead-1", type=TaskType.CALL_LEAD,
            assigned_to="Ines Zouaoui", created_at=datetime.now(timezone.utc),
        )
        empty_repository.create_task(task)
        assert empty_repository.get_tasks_for_lead("lead-999") == []
