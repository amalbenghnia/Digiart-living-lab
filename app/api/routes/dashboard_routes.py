"""GET /dashboard — the one endpoint the future frontend (or n8n, or a
simple cron) polls to get a snapshot. Deliberately just reads and counts —
no side effects, safe to call as often as needed."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.schemas.task_schema import DashboardResponse
from app.core.container import Container, get_container
from app.models.lead import LeadPriority, LeadStatus, PaymentStatus

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(container: Container = Depends(get_container)) -> DashboardResponse:
    leads = container.lead_service.get_all_leads()
    return DashboardResponse(
        total_leads=len(leads),
        new_leads=sum(1 for l in leads if l.status == LeadStatus.NEW),
        p0_leads=sum(1 for l in leads if l.priority == "P0"),
        p1_leads=sum(1 for l in leads if l.priority == "P1"),
        p2_leads=sum(1 for l in leads if l.priority == "P2"),
        payment_overdue=sum(
            1 for l in leads
            if l.payment_status == PaymentStatus.PENDING and container.rules.is_payment_overdue(l)
        ),
        llm_calls_this_hour=container.quota.calls_in_current_window,
        llm_hourly_quota=container.settings.llm_max_calls_per_hour,
    )
