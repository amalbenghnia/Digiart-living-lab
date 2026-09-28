"""Real Google Sheets-backed repository. Implements the exact same
LeadRepository interface as PrototypeLeadRepository — this file is the only
thing that changes when the project moves from prototype data to production.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from app.database.google_sheet import GoogleSheetClient
from app.exceptions.custom_exceptions import LeadNotFoundError
from app.models.lead import Lead, LeadStatus
from app.models.task import Task
from app.repositories.base_repository import LeadRepository
from app.core.cache import ttl_cache

_COLUMNS = [
    "id", "fullname", "phone", "email", "training", "source", "status",
    "priority", "score", "created_at", "last_contact", "payment_status",
    "payment_confirmed_at", "notes", "next_action", "next_followup_date",
    "called", "called_at", "called_by", "raw_message",
]


def _is_blank(value) -> bool:
    """True for None, empty string, and — importantly — the literal text
    "None"/"null" that a previous version of update_lead() could write into
    a cell (see the fix in update_lead below). Without this, a single row
    corrupted by that older bug would crash every future read of the whole
    sheet, not just that one row."""
    return value is None or str(value).strip().lower() in ("", "none", "null")


def _parse_datetime(value: str) -> datetime:
    # datetime.fromisoformat() only accepts a "Z" (UTC) suffix from Python
    # 3.11+. Pydantic's model_dump(mode="json") always writes "Z" for UTC
    # regardless of Python version, so on 3.10 this raises ValueError unless
    # we normalise "Z" to the explicit "+00:00" offset first. Safe on every
    # Python version, not just <3.11.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _row_to_lead(row: dict) -> Lead:
    return Lead(
        id=row["id"],
        fullname=row["fullname"],
        # gspread's get_all_records() auto-detects cell types: a phone number
        # containing only digits comes back as a Python int, not a string.
        # str(...) here is what was missing — Lead.phone requires a string.
        phone=str(row["phone"]) if not _is_blank(row.get("phone")) else None,
        email=row.get("email") if not _is_blank(row.get("email")) else None,
        training=row["training"],
        source=row.get("source") or "manual",
        status=row.get("status") or LeadStatus.NEW,
        priority=row.get("priority") or "unscored",
        score=float(row["score"]) if not _is_blank(row.get("score")) else None,
        created_at=_parse_datetime(row["created_at"]),
        last_contact=_parse_datetime(row["last_contact"]) if not _is_blank(row.get("last_contact")) else None,
        payment_status=row.get("payment_status") or "not_applicable",
        payment_confirmed_at=_parse_datetime(row["payment_confirmed_at"])
        if not _is_blank(row.get("payment_confirmed_at"))
        else None,
        notes=row.get("notes") if not _is_blank(row.get("notes")) else None,
        next_action=row.get("next_action") if not _is_blank(row.get("next_action")) else None,
        next_followup_date=row.get("next_followup_date") if not _is_blank(row.get("next_followup_date")) else None,
        called=str(row.get("called", "")).lower() in ("true", "1", "yes") if not _is_blank(row.get("called")) else False,
        called_at=_parse_datetime(row["called_at"]) if not _is_blank(row.get("called_at")) else None,
        called_by=row.get("called_by") if not _is_blank(row.get("called_by")) else None,
        raw_message=row.get("raw_message") if not _is_blank(row.get("raw_message")) else None,
    )


def _lead_to_row(lead: Lead) -> list:
    # mode="json" is the fix: without it, model_dump() keeps enums as Enum
    # instances and datetimes as datetime objects, so the str(...) below
    # would silently produce "LeadPriority.UNSCORED" instead of "unscored",
    # and "2026-07-25 19:07:10+00:00" (space) instead of a clean ISO8601
    # string — both unreadable by _row_to_lead on the way back in.
    d = lead.model_dump(mode="json")
    return [str(d.get(col) or "") for col in _COLUMNS]


class GoogleSheetLeadRepository(LeadRepository):
    def __init__(self, client: GoogleSheetClient):
        self._client = client

    @ttl_cache(ttl_seconds=15)
    def get_all_leads(self) -> list[Lead]:
        rows = self._client.get_all_records()
        return [_row_to_lead(r) for r in rows]

    def get_new_leads(self) -> list[Lead]:
        return [l for l in self.get_all_leads() if l.status == LeadStatus.NEW]

    def get_lead_by_id(self, lead_id: str) -> Lead | None:
        for lead in self.get_all_leads():
            if lead.id == lead_id:
                return lead
        return None

    def create_lead(self, lead: Lead) -> Lead:
        if not lead.id:
            lead = lead.model_copy(update={"id": str(uuid.uuid4())})
        self._client.append_row(_lead_to_row(lead))
        self.get_all_leads.cache_clear()
        return lead

    def update_lead(self, lead: Lead) -> Lead:
        # Guard against None explicitly — without it, str(None) writes the
        # literal text "None" into the cell (this is exactly what corrupted
        # an earlier test row and made every future read of the sheet crash).
        updates = {
            col: (str(v) if v is not None else "")
            for col, v in lead.model_dump(mode="json").items()
            if col in _COLUMNS
        }
        self._client.update_row_by_id("id", lead.id, updates)
        self.get_all_leads.cache_clear()
        return lead

    def update_priority(self, lead_id: str, priority: str, score: float | None) -> Lead:
        lead = self.get_lead_by_id(lead_id)
        if lead is None:
            raise LeadNotFoundError(lead_id)
        self._client.update_row_by_id(
            "id", lead_id, {"priority": priority, "score": score if score is not None else ""}
        )
        self.get_all_leads.cache_clear()
        return lead.model_copy(update={"priority": priority, "score": score})

    def create_task(self, task: Task) -> Task:
        # MVP: tasks are written to the same sheet's automation layer via n8n
        # (see AutomationService.trigger_create_task) rather than a second
        # worksheet, to keep the MVP footprint small. Swap for a dedicated
        # "Tasks" worksheet reader/writer here when that becomes necessary.
        return task

    def get_tasks_for_lead(self, lead_id: str) -> list[Task]:
        return []