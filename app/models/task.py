"""Domain model for a Task, created for the human (SDR) after a lead is processed."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TaskType(str, Enum):
    CALL_LEAD = "call_lead"
    FOLLOW_UP = "follow_up"
    PAYMENT_REMINDER = "payment_reminder"
    REVIEW_CUSTOM_REQUEST = "review_custom_request"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class Task(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str
    lead_id: str
    type: TaskType
    assigned_to: str = Field(..., description="Team member name, e.g. 'Ines Zouaoui'")
    status: TaskStatus = TaskStatus.PENDING
    priority: str = "P1"
    due_at: datetime | None = None
    created_at: datetime
    notes: str | None = None
