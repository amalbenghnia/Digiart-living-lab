from fastapi import APIRouter, Depends

from app.core.container import Container, get_container
from app.api.schemas.report_schema import DailyReportResponse

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/daily", response_model=DailyReportResponse)
def get_daily_report(container: Container = Depends(get_container)) -> DailyReportResponse:
    """
    Generate the daily KPI report.
    This endpoint is typically called by an automation tool like n8n on a schedule.
    """
    return container.reporting_service.generate_daily_report()
