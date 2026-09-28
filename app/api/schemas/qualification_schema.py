"""Schema the LLM output MUST conform to. Parsing a raw LLM string into this
model IS the post-generation business-rule validation step required by the
spec ('Business Rules (validation) — after LLM')."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QualificationOutput(BaseModel):
    intent: Literal["information_request", "ready_to_pay", "objection", "complaint", "other"]
    urgency: Literal["low", "medium", "high"]
    summary: str = Field(..., min_length=1, max_length=500)
    suggested_next_action: str = Field(..., min_length=1, max_length=300)
