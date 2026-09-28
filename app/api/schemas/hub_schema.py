from __future__ import annotations

from pydantic import BaseModel, Field


class HubTaskCompletionRequest(BaseModel):
    """Payload emitted by the existing Hub after a human completes a task."""

    task_id: str = Field(..., min_length=1)
    lead_id: str = Field(..., min_length=1)
    actor_id: str = Field(..., min_length=1)
    outcome: str | None = None
    notes: str | None = None


class HubTaskCompletionResponse(BaseModel):
    task_id: str
    lead_id: str
    status: str
    next_followup_date: str | None = None
    next_action: str | None = None
