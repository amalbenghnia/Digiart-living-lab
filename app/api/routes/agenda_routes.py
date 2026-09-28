"""Agenda routes — manage course sessions and rescheduling."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.container import Container, get_container
from app.models.course import SessionModel

router = APIRouter(tags=["agenda"])


class RescheduleRequest(BaseModel):
    new_date: str  # YYYY-MM-DD


class AddSessionRequest(BaseModel):
    course_id: str
    title: str
    date: str           # YYYY-MM-DD
    start_time: str = "09:00"
    end_time: str = "17:00"
    capacity: int = 20
    format: str = "On-site"


@router.get("/agenda", response_model=List[SessionModel])
def get_agenda(container: Container = Depends(get_container)):
    """Return all scheduled sessions from the Agenda tab."""
    return container.agenda_repo.get_all_sessions()


@router.get("/agenda/calendar")
def get_agenda_calendar(container: Container = Depends(get_container)):
    """Return sessions grouped by week, for the calendar view."""
    sessions = container.agenda_repo.get_all_sessions()

    calendar: dict[str, list] = {}
    for s in sessions:
        try:
            dt = datetime.strptime(s.date, "%Y-%m-%d")
            # ISO week key: "2026-W38"
            week_key = dt.strftime("%Y-W%W")
        except ValueError:
            week_key = "unknown"
        calendar.setdefault(week_key, []).append(s.model_dump())

    return {"calendar": calendar, "total_sessions": len(sessions)}


@router.put("/agenda/{session_id}/reschedule")
def reschedule_session(
    session_id: str,
    body: RescheduleRequest,
    container: Container = Depends(get_container),
):
    """Reschedule a session (Drag & Drop in the Dashboard).
    Updates the Date field in the Google Sheets Agenda tab.
    """
    # Validate date format
    try:
        datetime.strptime(body.new_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="new_date must be in YYYY-MM-DD format",
        )

    success = container.agenda_repo.update_session_date(session_id, body.new_date)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found in Agenda tab",
        )

    return {"message": f"Session {session_id} rescheduled to {body.new_date}", "success": True}


@router.post("/agenda/sessions", response_model=SessionModel, status_code=status.HTTP_201_CREATED)
def add_session(
    body: AddSessionRequest,
    container: Container = Depends(get_container),
):
    """Add a new session to the Agenda (e.g. after promoting a recommendation)."""
    new_session = SessionModel(
        session_id=f"S{uuid.uuid4().hex[:6].upper()}",
        course_id=body.course_id,
        title=body.title,
        date=body.date,
        start_time=body.start_time,
        end_time=body.end_time,
        capacity=body.capacity,
        format=body.format,
        status="open",
    )
    success = container.agenda_repo.add_session(new_session)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add session to Google Sheets",
        )
    return new_session
