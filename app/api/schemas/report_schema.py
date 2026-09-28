from pydantic import BaseModel
from typing import Dict, Optional


class DailyReportResponse(BaseModel):
    # — Vue globale —
    total_leads_all: int
    total_leads_24h: int

    # — Priorités (tous les leads actifs) —
    p0_leads_count: int
    p1_leads_count: int
    p2_leads_count: int
    unscored_leads_count: int

    # — Activité commerciale —
    called_count: int
    uncalled_count: int
    called_today: int

    # — Conversions & Paiements —
    contacted_count: int
    paid_count: int
    payment_pending_count: int
    conversion_rate_percent: Optional[float]

    # — Performance —
    average_response_time_minutes: Optional[float]

    # — Répartition —
    leads_by_source: Dict[str, int]
    leads_by_training: Dict[str, int]

    # — Méta —
    report_generated_at: str
