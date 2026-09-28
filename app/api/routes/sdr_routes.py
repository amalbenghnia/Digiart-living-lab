from fastapi import APIRouter, Depends, HTTPException, status

from app.core.container import Container, get_container
from app.api.schemas.sdr_schema import (
    SDRBriefRequest, SDRBriefResponse,
    ObjectionRequest, ObjectionResponse,
    CallOutcomeRequest, CallOutcomeResponse,
    NextActionRequest, NextActionResponse,
)

router = APIRouter(prefix="/sdr", tags=["SDR Copilot"])


# ──────────────────────── Module 1: Brief ────────────────────────

@router.post("/brief", response_model=SDRBriefResponse)
def get_sdr_brief(
    request: SDRBriefRequest,
    container: Container = Depends(get_container),
) -> SDRBriefResponse:
    """
    Generate an AI-powered brief for the SDR before calling a lead.
    Combines lead data with the school's knowledge base (RAG).
    """
    try:
        return container.sdr_copilot_service.generate_brief(request.lead_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ──────────────────────── Module 3: Objection Handler ────────────

@router.post("/objection", response_model=ObjectionResponse)
def handle_objection(
    request: ObjectionRequest,
    container: Container = Depends(get_container),
) -> ObjectionResponse:
    """
    Handle a customer objection in real-time during a call.
    The SDR types the objection and gets an AI-powered counter-argument.
    """
    try:
        return container.sdr_copilot_service.handle_objection(request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ──────────────────────── Module 6: Call Outcome ─────────────────

@router.post("/outcome", response_model=CallOutcomeResponse)
def process_call_outcome(
    request: CallOutcomeRequest,
    container: Container = Depends(get_container),
) -> CallOutcomeResponse:
    """
    Process the result of a call. Updates lead status, generates a call
    summary, creates a follow-up email draft, and recommends next steps.
    """
    try:
        return container.sdr_copilot_service.process_call_outcome(request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ──────────────────────── Module 5: Next Best Action ─────────────

@router.post("/next-action", response_model=NextActionResponse)
def get_next_action(
    request: NextActionRequest,
    container: Container = Depends(get_container),
) -> NextActionResponse:
    """
    Recommend the optimal commercial action for a lead based on its
    priority, score, history and current status. Uses business rules
    first, falls back to LLM for complex/ambiguous cases.
    """
    try:
        return container.sdr_copilot_service.recommend_next_action(request.lead_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
