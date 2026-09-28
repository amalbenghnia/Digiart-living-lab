from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.task import Task, TaskStatus, TaskType


class TaskCreateRequest(BaseModel):
    lead_id: str
    type: TaskType


class TaskResponse(BaseModel):
    id: str
    lead_id: str
    type: TaskType
    assigned_to: str
    status: TaskStatus
    priority: str
    due_at: datetime | None
    created_at: datetime
    notes: str | None

    @classmethod
    def from_domain(cls, task: Task) -> "TaskResponse":
        return cls(
            id=task.id,
            lead_id=task.lead_id,
            type=task.type,
            assigned_to=task.assigned_to,
            status=task.status,
            priority=task.priority,
            due_at=task.due_at,
            created_at=task.created_at,
            notes=task.notes,
        )


class DashboardResponse(BaseModel):
    total_leads: int
    new_leads: int
    p0_leads: int
    p1_leads: int
    p2_leads: int
    payment_overdue: int
    llm_calls_this_hour: int
    llm_hourly_quota: int
