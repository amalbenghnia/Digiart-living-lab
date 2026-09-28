"""Prototype repository: pure in-memory storage, seeded with realistic fake
leads. This is what the spec calls "sources prototype" — it implements the
exact same LeadRepository interface as the real Google Sheets repository,
so every service, every business rule, and every test written against this
class works unchanged against production data later.

This is intentionally the ONLY difference between "sprint 1 prototype" and
"sprint 2 real data": swap DATA_SOURCE_MODE in .env, nothing else.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.lead import Lead, LeadPriority, LeadStatus, PaymentStatus
from app.models.task import Task
from app.repositories.base_repository import LeadRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PrototypeLeadRepository(LeadRepository):
    def __init__(self, seed: bool = True):
        self._leads: dict[str, Lead] = {}
        self._tasks: dict[str, Task] = {}
        if seed:
            self._seed_data()

    # -- LeadRepository implementation --------------------------------------

    def get_all_leads(self) -> list[Lead]:
        return list(self._leads.values())

    def get_new_leads(self) -> list[Lead]:
        return [l for l in self._leads.values() if l.status == LeadStatus.NEW]

    def get_lead_by_id(self, lead_id: str) -> Lead | None:
        return self._leads.get(lead_id)

    def create_lead(self, lead: Lead) -> Lead:
        if not lead.id:
            lead = lead.model_copy(update={"id": str(uuid.uuid4())})
        self._leads[lead.id] = lead
        return lead

    def update_lead(self, lead: Lead) -> Lead:
        self._leads[lead.id] = lead
        return lead

    def update_priority(self, lead_id: str, priority: str, score: float | None) -> Lead:
        lead = self._leads[lead_id]
        updated = lead.model_copy(update={"priority": priority, "score": score})
        self._leads[lead_id] = updated
        return updated

    def create_task(self, task: Task) -> Task:
        if not task.id:
            task = task.model_copy(update={"id": str(uuid.uuid4())})
        self._tasks[task.id] = task
        return task

    def get_tasks_for_lead(self, lead_id: str) -> list[Task]:
        return [t for t in self._tasks.values() if t.lead_id == lead_id]

    # -- Seed data ------------------------------------------------------------

    def _seed_data(self) -> None:
        now = _now()
        seed_leads = [
            Lead(
                id="lead-001",
                fullname="Yassine Trabelsi",
                phone="+21620000001",
                email="yassine.t@example.com",
                training="Python for AI",
                source="meta_ads",
                status=LeadStatus.NEW,
                priority=LeadPriority.P0,
                score=85.0,
                called=False,
                created_at=now - timedelta(hours=3),  # P0 and uncalled for >2h
                raw_message="Bonjour, je suis intéressé par la formation Python for AI, "
                "vous commencez quand ?",
            ),
            Lead(
                id="lead-002",
                fullname="Salma Ben Youssef",
                phone="+21620000002",
                email="salma.by@example.com",
                training="Graphic Design",
                source="manual",
                status=LeadStatus.NEW,
                called=False,
                created_at=now - timedelta(minutes=20),  # fresh, not hot yet
            ),
            Lead(
                id="lead-003",
                fullname="Karim Jaziri",
                phone="+21620000001",  # duplicate phone with lead-001 on purpose
                email="karim.j@example.com",
                training="Digital Marketing",
                source="meta_ads",
                status=LeadStatus.NEW,
                called=False,
                created_at=now - timedelta(minutes=5),
            ),
            Lead(
                id="lead-004",
                fullname="Nour Abidi",
                phone="+21620000004",
                email=None,
                training="Python for AI",
                source="website",
                status=LeadStatus.CONFIRMED_UNPAID,
                payment_status=PaymentStatus.PENDING,
                created_at=now - timedelta(days=6),
                last_contact=now - timedelta(days=4),  # 4 days pending -> overdue
                score=68.0,
                priority=LeadPriority.P1,
                called=False,
            ),
            Lead(
                id="lead-005",
                fullname="Firas Mejri",
                phone="+21620000005",
                email="firas.m@example.com",
                training="Graphic Design",
                source="manual",
                status=LeadStatus.CONTACTED,
                created_at=now - timedelta(days=2),
                last_contact=now - timedelta(days=1, hours=1),  # follow-up due today
                score=55.0,
                priority=LeadPriority.P1,
                called=True,
                called_at=now - timedelta(days=1, hours=1),
                called_by="Ines Zouaoui",
            ),
        ]
        for lead in seed_leads:
            self._leads[lead.id] = lead
