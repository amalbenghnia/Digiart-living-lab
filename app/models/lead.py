"""Domain model for a Lead.

This is the single source of truth for what a "Lead" looks like across the
whole application: API schemas, repositories, and services all convert
to/from this model. Keeping it here (instead of duplicating fields in the
Google Sheet repository) is what makes the repository swap (prototype ->
Google Sheets -> PostgreSQL later) safe.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class LeadStatus(str, Enum):
    NEW = "new"
    QUALIFIED = "qualified"
    ASSIGNED = "assigned"
    CONTACTED = "contacted"
    CONFIRMED_UNPAID = "confirmed_unpaid"
    PAID = "paid"
    NO_RESPONSE = "no_response"
    ARCHIVED = "archived"


class LeadPriority(str, Enum):
    P0 = "P0"  # hot lead, call within 2h
    P1 = "P1"  # standard priority
    P2 = "P2"  # low priority / needs nurturing
    UNSCORED = "unscored"


class PaymentStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"
    OVERDUE = "overdue"
    PAID = "paid"


class Lead(BaseModel):
    """A single lead, as it lives in the source of truth (Sheet/DB)."""

    model_config = ConfigDict(use_enum_values=True, str_strip_whitespace=True)

    id: str = Field(..., description="Stable unique identifier (UUID or Sheet row key)")
    fullname: str = Field(
        default="",
        description="Full name. Blank is allowed at the model level on purpose — "
        "'missing mandatory field' is a business rule violation (see "
        "LeadBusinessRules.validate_mandatory_fields), not a schema error. This "
        "keeps validation logic in one place and lets the API report it as a "
        "structured, user-facing rule violation instead of a raw 422.",
    )
    phone: str | None = None
    email: EmailStr | None = None
    training: str = Field(default="", description="Requested training / course name")
    source: str = Field(default="manual", description="meta_ads, manual, website, referral...")
    status: LeadStatus = LeadStatus.NEW
    priority: LeadPriority = LeadPriority.UNSCORED
    score: float | None = Field(default=None, ge=0, le=100)
    created_at: datetime
    last_contact: datetime | None = None
    payment_status: PaymentStatus = PaymentStatus.NOT_APPLICABLE
    payment_confirmed_at: datetime | None = None
    notes: str | None = None
    next_action: str | None = None
    next_followup_date: str | None = Field(
        default=None,
        description="Date de relance planifiée (YYYY-MM-DD). Alimentée par le SDR Copilot."
    )
    called: bool = False
    called_at: datetime | None = None
    called_by: str | None = None
    raw_message: str | None = Field(
        default=None,
        description="Free-text field (WhatsApp/email/notes). Only this field may trigger an LLM call.",
    )
    sdr_brief: str | None = Field(default=None, description="Generated call brief and anticipated objections for the SDR")
    email_draft: str | None = Field(default=None, description="Generated draft email for follow-up")

    @field_validator("phone")
    @classmethod
    def validate_phone_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        cleaned = v.replace(" ", "").replace("-", "")
        if not cleaned.replace("+", "").isdigit():
            raise ValueError(f"Invalid phone format: {v}")
        return cleaned

    def has_minimum_contact_info(self) -> bool:
        """A lead must have at least one way to be reached."""
        return bool(self.phone) or bool(self.email)
