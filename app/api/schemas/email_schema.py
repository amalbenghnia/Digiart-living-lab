"""Schemas for the email generation endpoint.

These are the request/response models for POST /lead/{lead_id}/generate-email.
The response contains a ready-to-send subject and HTML body drafted by the LLM.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class EmailContext(str, Enum):
    """The intent behind the generated email."""
    CONTACT_P1 = "contact_p1"     # P1 not called in 24h — first outreach
    NURTURING_P2 = "nurturing_p2" # P2 nurturing — informational content
    PAYMENT_REMINDER = "payment_reminder"  # Overdue payment follow-up


class EmailGenerationRequest(BaseModel):
    context: EmailContext = EmailContext.CONTACT_P1


class EmailGenerationResponse(BaseModel):
    lead_id: str
    context: str
    subject: str
    body_html: str
    body_text: str
