from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.core.logging import get_logger, log_event
from app.models.lead import Lead, LeadPriority
from app.models.task import Task, TaskStatus, TaskType
from app.repositories.base_repository import LeadRepository

logger = get_logger(__name__)

_DEFAULT_ASSIGNEE = "Ines Zouaoui"


class TaskService:
    def __init__(self, repository: LeadRepository):
        self._repository = repository

    def _find_open_task(self, lead_id: str, task_type: TaskType) -> Task | None:
        """Return an unfinished task of the same type for a lead."""
        open_statuses = {TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value}
        for task in self._repository.get_tasks_for_lead(lead_id):
            if task.type == task_type and task.status in open_statuses:
                return task
        return None

    @staticmethod
    def _stable_task_id(lead_id: str, task_type: TaskType) -> str:
        """Build an idempotency key that is stable across retries."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"digiart:{lead_id}:{task_type.value}"))

    def get_or_create_call_task(self, lead: Lead, priority: PriorityResultLike) -> tuple[Task, bool]:
        """Return an open call task and whether this invocation created it."""
        existing = self._find_open_task(lead.id, TaskType.CALL_LEAD)
        if existing:
            log_event(
                logger,
                "business_rule",
                "Existing call task reused",
                lead_id=lead.id,
                task_id=existing.id,
            )
            return existing, False

        due_offset = timedelta(hours=2) if priority.priority == LeadPriority.P0 else timedelta(days=1)
        task = Task(
            id=self._stable_task_id(lead.id, TaskType.CALL_LEAD),
            lead_id=lead.id,
            type=TaskType.CALL_LEAD,
            assigned_to=_DEFAULT_ASSIGNEE,
            status=TaskStatus.PENDING,
            priority=priority.priority,
            due_at=datetime.now(timezone.utc) + due_offset,
            created_at=datetime.now(timezone.utc),
            notes=priority.reason,
        )
        created = self._repository.create_task(task)
        log_event(
            logger, "business_rule", "Call task created",
            lead_id=lead.id, task_id=created.id, assigned_to=_DEFAULT_ASSIGNEE,
        )
        return created, True

    def create_call_task(self, lead: Lead, priority: PriorityResultLike) -> Task:
        """Compatibility helper for callers that only need the task itself."""
        task, _ = self.get_or_create_call_task(lead, priority)
        return task

    def get_or_create_payment_reminder_task(self, lead: Lead, days_overdue: int) -> tuple[Task, bool]:
        """Return an open payment reminder and whether this call created it."""
        existing = self._find_open_task(lead.id, TaskType.PAYMENT_REMINDER)
        if existing:
            log_event(
                logger,
                "business_rule",
                "Existing payment reminder task reused",
                lead_id=lead.id,
                task_id=existing.id,
            )
            return existing, False

        task = Task(
            id=self._stable_task_id(lead.id, TaskType.PAYMENT_REMINDER),
            lead_id=lead.id,
            type=TaskType.PAYMENT_REMINDER,
            assigned_to=_DEFAULT_ASSIGNEE,
            status=TaskStatus.PENDING,
            priority="P1",
            due_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            notes=f"Payment pending for {days_overdue} days — relance required",
        )
        return self._repository.create_task(task), True

    def create_payment_reminder_task(self, lead: Lead, days_overdue: int) -> Task:
        """Compatibility helper for callers that only need the task itself."""
        task, _ = self.get_or_create_payment_reminder_task(lead, days_overdue)
        return task


# Lightweight structural type to avoid circular imports
from typing import Protocol


class PriorityResultLike(Protocol):
    priority: str
    reason: str
