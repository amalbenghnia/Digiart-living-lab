"""Request/response schemas for the /lead* endpoints.

These are deliberately separate from app.models.lead.Lead: the API contract
and the domain model are allowed to drift (e.g. the API never accepts a
client-supplied `status` on creation) without that leaking into the service
layer.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.lead import Lead, LeadPriority, LeadStatus, PaymentStatus


class LeadCreateRequest(BaseModel):
    fullname: str = Field(..., min_length=1, examples=["Yassine Trabelsi"])
    phone: str | None = Field(default=None, examples=["+21620000001"])
    email: EmailStr | None = None
    training: str = Field(..., examples=["Python for AI"])
    source: str = Field(default="manual", examples=["meta_ads", "manual", "website"])
    raw_message: str | None = Field(
        default=None,
        description="Free text (WhatsApp/email/form). Presence of this field is "
        "what may trigger an LLM call downstream — never send filler text here.",
    )


class LeadStatusUpdateRequest(BaseModel):
    status: LeadStatus


class LeadResponse(BaseModel):
    id: str
    fullname: str
    phone: str | None
    email: str | None
    training: str
    source: str
    status: LeadStatus
    priority: LeadPriority
    score: float | None
    created_at: datetime
    last_contact: datetime | None
    payment_status: PaymentStatus
    called: bool
    called_at: datetime | None
    called_by: str | None
    notes: str | None
    next_action: str | None

    @classmethod
    def from_domain(cls, lead: Lead) -> "LeadResponse":
        return cls(
            id=lead.id,
            fullname=lead.fullname,
            phone=lead.phone,
            email=lead.email,
            training=lead.training,
            source=lead.source,
            status=lead.status,
            priority=lead.priority,
            score=lead.score,
            created_at=lead.created_at,
            last_contact=lead.last_contact,
            payment_status=lead.payment_status,
            called=lead.called,
            called_at=lead.called_at,
            called_by=lead.called_by,
            notes=lead.notes,
            next_action=lead.next_action,
        )


class LeadListResponse(BaseModel):
    count: int
    leads: list[LeadResponse]


class DuplicateCheckRequest(BaseModel):
    phone: str | None = None
    email: EmailStr | None = None


class DuplicateCheckResponse(BaseModel):
    is_duplicate: bool
    matched_field: str | None = None
    matched_value: str | None = None
    existing_lead_id: str | None = None


class MarkCalledRequest(BaseModel):
    called_by: str = Field(..., min_length=1, examples=["Ines Zouaoui"])


class PriorityRequest(BaseModel):
    lead_id: str


class PriorityResponse(BaseModel):
    lead_id: str
    priority: LeadPriority
    score: float | None
    reason: str
    is_hot: bool
    is_payment_overdue: bool
    days_overdue: int
