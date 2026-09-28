"""GET /roster — live enrollment view (calculated, never stored)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends

from app.core.container import Container, get_container
from app.models.course import RosterEntry

router = APIRouter(tags=["roster"])


@router.get("/roster/debug")
def get_roster_debug(container: Container = Depends(get_container)):
    """Debug view: shows exactly which leads matched each session and why.

    Use this to diagnose why registered count is 0.
    Check: lead.training matches session title? lead.status is 'paid'?
    """
    leads = container.lead_service.get_all_leads()
    return container.roster_service.get_roster_debug(leads)


@router.get("/roster", response_model=List[RosterEntry])
def get_roster(container: Container = Depends(get_container)):
    """Return the live enrollment state for all scheduled sessions.

    The roster is computed on-the-fly by crossing:
      - Agenda tab (sessions + capacity)
      - Leads (confirmed_unpaid + paid → counted as registered)
    """
    leads = container.lead_service.get_all_leads()
    return container.roster_service.get_roster(leads)


@router.get("/roster/{session_id}", response_model=RosterEntry)
def get_session_roster(
    session_id: str,
    container: Container = Depends(get_container),
):
    """Return the roster for a single session."""
    from fastapi import HTTPException, status
    leads = container.lead_service.get_all_leads()
    entry = container.roster_service.get_session_roster(session_id, leads)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found or has no active roster",
        )
    return entry
