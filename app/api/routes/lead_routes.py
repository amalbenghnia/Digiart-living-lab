"""Lead endpoints.

POST /lead/new       -> register a new lead (validation + dedup + persist)
POST /lead/analyse   -> run the full pipeline (qualify -> priority -> route)
GET  /leads          -> list all leads
GET  /lead/{id}      -> fetch one lead
PUT  /lead/{id}      -> update status (validated transition)
POST /lead/priority  -> recompute priority on demand
POST /lead/duplicate -> check duplicate without creating a lead
POST /lead/task      -> manually create a task for a lead (e.g. custom request review)

Every route is a thin adapter: it calls exactly one service method and maps
exceptions to HTTP status codes. No business logic lives here.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.schemas.email_schema import EmailGenerationRequest, EmailGenerationResponse
from app.api.schemas.lead_schema import (
    DuplicateCheckRequest,
    DuplicateCheckResponse,
    LeadCreateRequest,
    LeadListResponse,
    LeadResponse,
    LeadStatusUpdateRequest,
    MarkCalledRequest,
    PriorityRequest,
    PriorityResponse,
)
from app.api.schemas.task_schema import TaskCreateRequest, TaskResponse
from app.core.container import Container, get_container
from app.core.logging import get_logger, log_event
from app.exceptions.custom_exceptions import (
    BudgetExceededError,
    DuplicateLeadError,
    LLMTimeoutError,
    LLMValidationError,
    ValidationError,
)
from app.models.lead import Lead, LeadStatus
from app.models.task import Task, TaskStatus

router = APIRouter(tags=["leads"])
logger = get_logger(__name__)


def _lead_or_404(container: Container, lead_id: str) -> Lead:
    lead = container.lead_service.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Lead not found: {lead_id}")
    return lead


@router.post("/lead/new", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
def create_lead(payload: LeadCreateRequest, container: Container = Depends(get_container)) -> LeadResponse:
    log_event(logger, "api_call", "POST /lead/new", fullname=payload.fullname, source=payload.source)
    lead = Lead(
        id=str(uuid.uuid4()),
        fullname=payload.fullname,
        phone=payload.phone,
        email=payload.email,
        training=payload.training,
        source=payload.source,
        status=LeadStatus.NEW,
        created_at=datetime.now(timezone.utc),
        raw_message=payload.raw_message,
    )
    try:
        created = container.lead_service.register_new_lead(lead)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except DuplicateLeadError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return LeadResponse.from_domain(created)


@router.post("/lead/analyse", response_model=LeadResponse)
def analyse_lead(
    payload: PriorityRequest, container: Container = Depends(get_container)
) -> LeadResponse:
    """Runs the full agent pipeline: qualification (LLM if needed) ->
    priority -> task creation -> notifications -> automation triggers."""
    log_event(logger, "api_call", "POST /lead/analyse", lead_id=payload.lead_id)
    try:
        lead = container.lead_service.analyse_lead(payload.lead_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BudgetExceededError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except LLMValidationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return LeadResponse.from_domain(lead)


@router.get("/leads", response_model=LeadListResponse)
def list_leads(
    sort_by: str | None = None, container: Container = Depends(get_container)
) -> LeadListResponse:
    """?sort_by=priority orders P0 first, then P1, then P2, and by score
    descending within each priority — useful for a daily call list."""
    leads = container.lead_service.get_all_leads(sort_by=sort_by)
    return LeadListResponse(count=len(leads), leads=[LeadResponse.from_domain(l) for l in leads])


@router.get("/leads/followup-due", response_model=LeadListResponse)
def list_leads_due_for_followup(container: Container = Depends(get_container)) -> LeadListResponse:
    log_event(logger, "api_call", "GET /leads/followup-due")
    leads = container.lead_service.get_leads_due_for_followup()
    return LeadListResponse(count=len(leads), leads=[LeadResponse.from_domain(l) for l in leads])


@router.get("/lead/{lead_id}", response_model=LeadResponse)
def get_lead(lead_id: str, container: Container = Depends(get_container)) -> LeadResponse:
    lead = _lead_or_404(container, lead_id)
    return LeadResponse.from_domain(lead)


@router.put("/lead/{lead_id}", response_model=LeadResponse)
def update_lead_status(
    lead_id: str, payload: LeadStatusUpdateRequest, container: Container = Depends(get_container)
) -> LeadResponse:
    log_event(logger, "api_call", "PUT /lead/{id}", lead_id=lead_id, target_status=payload.status)
    try:
        lead = container.lead_service.update_lead_status(lead_id, payload.status)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return LeadResponse.from_domain(lead)


@router.post("/lead/priority", response_model=PriorityResponse)
def compute_priority(
    payload: PriorityRequest, container: Container = Depends(get_container)
) -> PriorityResponse:
    lead = _lead_or_404(container, payload.lead_id)
    updated, result = container.priority_service.compute_and_persist(lead)
    is_payment_overdue = container.rules.is_payment_overdue(updated)
    return PriorityResponse(
        lead_id=updated.id, priority=result.priority, score=updated.score,
        reason=result.reason,
        is_hot=result.is_hot,
        is_payment_overdue=is_payment_overdue,
        days_overdue=container.rules.days_overdue(updated) if is_payment_overdue else 0,
    )


@router.post("/lead/duplicate", response_model=DuplicateCheckResponse)
def check_duplicate(
    payload: DuplicateCheckRequest, container: Container = Depends(get_container)
) -> DuplicateCheckResponse:
    probe = Lead(
        id="probe", fullname="probe", phone=payload.phone, email=payload.email,
        training="probe", created_at=datetime.now(timezone.utc),
    )
    result = container.duplicate_service.check(probe)
    return DuplicateCheckResponse(
        is_duplicate=result.is_duplicate, matched_field=result.matched_field,
        matched_value=result.matched_value, existing_lead_id=result.existing_lead_id,
    )


@router.post("/lead/task", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest, container: Container = Depends(get_container)
) -> TaskResponse:
    lead = _lead_or_404(container, payload.lead_id)
    if payload.type.value == "payment_reminder":
        task = container.task_service.create_payment_reminder_task(
            lead, container.rules.days_overdue(lead)
        )
    else:
        from app.business_rules.lead_rules import PriorityResult
        fallback_priority = PriorityResult(priority=lead.priority, reason="Manual task creation", is_hot=False)
        task = container.task_service.create_call_task(lead, fallback_priority)
    return TaskResponse.from_domain(task)


@router.post("/lead/{lead_id}/mark-called", response_model=LeadResponse)
def mark_lead_called(
    lead_id: str, payload: MarkCalledRequest, container: Container = Depends(get_container)
) -> LeadResponse:
    """Mark a lead as called. Updates called=True, records who called and
    when, transitions status to CONTACTED, and records last_contact."""
    log_event(logger, "api_call", "POST /lead/{id}/mark-called", lead_id=lead_id, called_by=payload.called_by)
    try:
        lead = container.lead_service.mark_lead_called(lead_id, payload.called_by)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return LeadResponse.from_domain(lead)


@router.get("/leads/uncalled-urgent")
def get_uncalled_urgent_leads(
    container: Container = Depends(get_container),
) -> JSONResponse:
    """Return all P0 leads that have NOT been called and have been waiting
    longer than the hot-lead threshold (default 2h). Used by the n8n
    reminder workflow to send escalation alerts."""
    results = container.lead_service.get_uncalled_urgent_leads()
    return JSONResponse(content={"count": len(results), "leads": results})


@router.get("/leads/export-excel")
def export_leads_excel(
    container: Container = Depends(get_container),
) -> StreamingResponse:
    """Export all leads sorted by priority as an Excel file. Also saves a
    timestamped copy in the data/ directory so the LLM's scoring work is
    persisted and never lost."""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail="openpyxl is not installed. Run: pip install openpyxl",
        )

    leads = container.lead_service.get_all_leads(sort_by="priority")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Leads"

    # Header row
    headers = [
        "#", "Priorité", "Score", "Nom complet", "Téléphone", "Email",
        "Formation", "Source", "Statut", "Appelé", "Appelé par",
        "Appelé le", "Créé le", "Dernier contact", "Paiement", "Notes",
        "Prochaine action",
    ]
    header_fill = PatternFill(start_color="2B5797", end_color="2B5797", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    # Priority color mapping
    priority_fills = {
        "P0": PatternFill(start_color="FF4444", end_color="FF4444", fill_type="solid"),
        "P1": PatternFill(start_color="FFB020", end_color="FFB020", fill_type="solid"),
        "P2": PatternFill(start_color="44AA44", end_color="44AA44", fill_type="solid"),
    }

    for row_idx, lead in enumerate(leads, 2):
        ws.cell(row=row_idx, column=1, value=row_idx - 1)
        priority_cell = ws.cell(row=row_idx, column=2, value=lead.priority)
        if lead.priority in priority_fills:
            priority_cell.fill = priority_fills[lead.priority]
            priority_cell.font = Font(color="FFFFFF", bold=True)
        ws.cell(row=row_idx, column=3, value=lead.score)
        ws.cell(row=row_idx, column=4, value=lead.fullname)
        ws.cell(row=row_idx, column=5, value=lead.phone or "")
        ws.cell(row=row_idx, column=6, value=lead.email or "")
        ws.cell(row=row_idx, column=7, value=lead.training)
        ws.cell(row=row_idx, column=8, value=lead.source)
        ws.cell(row=row_idx, column=9, value=lead.status)
        ws.cell(row=row_idx, column=10, value="Oui" if lead.called else "Non")
        ws.cell(row=row_idx, column=11, value=lead.called_by or "")
        ws.cell(row=row_idx, column=12, value=lead.called_at.isoformat() if lead.called_at else "")
        ws.cell(row=row_idx, column=13, value=lead.created_at.isoformat())
        ws.cell(row=row_idx, column=14, value=lead.last_contact.isoformat() if lead.last_contact else "")
        ws.cell(row=row_idx, column=15, value=lead.payment_status)
        ws.cell(row=row_idx, column=16, value=lead.notes or "")
        ws.cell(row=row_idx, column=17, value=lead.next_action or "")

    # Auto-width columns
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 40)

    # Save a persistent copy in data/
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_path = data_dir / f"leads_sorted_{timestamp}.xlsx"
    wb.save(str(file_path))
    log_event(logger, "business_rule", "Excel export saved", path=str(file_path), count=len(leads))

    # Stream the file back to the caller
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="leads_sorted_{timestamp}.xlsx"'},
    )


@router.post("/lead/{lead_id}/generate-email", response_model=EmailGenerationResponse)
def generate_lead_email(
    lead_id: str,
    payload: EmailGenerationRequest,
    container: Container = Depends(get_container),
) -> EmailGenerationResponse:
    """Use the LLM to generate a personalised email for a lead.

    The caller (n8n) provides the context (contact_p1, nurturing_p2,
    payment_reminder). The response contains a ready-to-use subject line and
    HTML/text email body. n8n is responsible for actually sending the email
    so that the CM always has a chance to review or override it.
    """
    log_event(
        logger, "api_call", "POST /lead/{id}/generate-email",
        lead_id=lead_id, context=payload.context,
    )
    lead = _lead_or_404(container, lead_id)
    try:
        result = container.communication_service.generate_email(lead, payload.context)
    except BudgetExceededError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except LLMValidationError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return result
