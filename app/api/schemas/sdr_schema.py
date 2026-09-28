from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


# ──────────────────────── Sprint 1: Brief ────────────────────────

class SDRBriefRequest(BaseModel):
    lead_id: str

class SDRBriefResponse(BaseModel):
    lead_id: str
    fullname: str
    priority: str
    customer_summary: str
    suggested_pitch: str
    predicted_objections: str
    email_draft_html: str


# ──────────────────────── Sprint 2: Objection Handler ────────────

class ObjectionRequest(BaseModel):
    lead_id: str
    objection_text: str  # What the customer actually said

class ObjectionResponse(BaseModel):
    lead_id: str
    objection_category: str       # e.g. "prix", "temps", "distance"
    recommended_response: str     # The counter-argument
    alternative_offer: str        # e.g. "Proposer Summer School au lieu du BTS"
    suggested_next_action: str    # e.g. "Envoyer brochure par email"


# ──────────────────────── Sprint 2: Call Outcome ─────────────────

class CallOutcome(str, Enum):
    INTERESTED = "interested"
    VERY_INTERESTED = "very_interested"
    NEED_TIME = "need_time"
    CALL_LATER = "call_later"
    NO_ANSWER = "no_answer"
    WRONG_NUMBER = "wrong_number"
    NOT_INTERESTED = "not_interested"
    ALREADY_REGISTERED = "already_registered"
    PAYMENT_PENDING = "payment_pending"

class CallOutcomeRequest(BaseModel):
    lead_id: str
    outcome: str  # relaxed from CallOutcome Enum to prevent 422 errors from n8n
    call_notes: Optional[str] = None  # Free text notes from the SDR

class CallOutcomeResponse(BaseModel):
    lead_id: str
    outcome: str
    new_status: str               # The updated lead status
    call_summary: str             # AI-generated summary of the call
    follow_up_email_draft: str    # AI-generated follow-up email
    suggested_next_action: str    # What to do next
    next_followup_date: Optional[str] = None  # When to follow up


# ──────────────────────── Sprint 2: Next Best Action ─────────────

class NextActionRequest(BaseModel):
    lead_id: str

class NextActionResponse(BaseModel):
    lead_id: str
    recommended_action: str       # "call_immediately", "send_brochure", "wait_48h", etc.
    reasoning: str                # Why this action is recommended
    urgency: str                  # "haute", "moyenne", "basse"
    message_template: Optional[str] = None  # Optional pre-written message
