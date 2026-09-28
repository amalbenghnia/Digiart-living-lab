from datetime import datetime, timedelta, timezone
from typing import Dict

from app.models.lead import Lead, LeadPriority, LeadStatus, PaymentStatus
from app.repositories.base_repository import LeadRepository
from app.api.schemas.report_schema import DailyReportResponse
from app.core.logging import get_logger

logger = get_logger(__name__)


class ReportingService:
    def __init__(self, repository: LeadRepository):
        self._repository = repository

    def generate_daily_report(self) -> DailyReportResponse:
        leads = self._repository.get_all_leads()
        now = datetime.now(timezone.utc)
        one_day_ago = now - timedelta(days=1)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # ── Leads des dernières 24h (nouveaux arrivants) ──────────
        recent_leads = [l for l in leads if l.created_at and l.created_at >= one_day_ago]

        # ── Priorités sur TOUS les leads ──────────────────────────
        p0_count    = sum(1 for l in leads if l.priority == LeadPriority.P0.value)
        p1_count    = sum(1 for l in leads if l.priority == LeadPriority.P1.value)
        p2_count    = sum(1 for l in leads if l.priority == LeadPriority.P2.value)
        unscored    = sum(1 for l in leads if not l.priority or l.priority == LeadPriority.UNSCORED.value)

        # ── Activité commerciale ───────────────────────────────────
        called_all  = [l for l in leads if l.called]
        uncalled_all = [l for l in leads if not l.called]
        called_today_list = [
            l for l in leads
            if l.called and l.called_at and l.called_at >= today_start
        ]

        # ── Statuts & Paiements ────────────────────────────────────
        contacted   = [l for l in leads if l.status in {
            LeadStatus.CONTACTED.value,
            LeadStatus.CONFIRMED_UNPAID.value,
            LeadStatus.PAID.value,
        }]
        paid_leads  = [
            l for l in leads
            if l.status == LeadStatus.PAID.value
            or (l.payment_status and l.payment_status == PaymentStatus.PAID.value)
        ]
        pending_pay = [
            l for l in leads
            if l.status == LeadStatus.CONFIRMED_UNPAID.value
            or (l.payment_status and l.payment_status == PaymentStatus.PENDING.value)
        ]

        conversion_rate = None
        if contacted:
            conversion_rate = round(len(paid_leads) / len(contacted) * 100.0, 1)

        # ── Temps de réponse moyen (leads appelés, sur tous les leads) ──
        timed_leads = [l for l in called_all if l.called_at and l.created_at]
        avg_response = None
        if timed_leads:
            total_min = sum(
                (l.called_at - l.created_at).total_seconds() / 60.0
                for l in timed_leads
                if l.called_at >= l.created_at
            )
            avg_response = round(total_min / len(timed_leads), 1)

        # ── Sources & Formations (sur TOUS les leads) ──────────────
        leads_by_source: Dict[str, int] = {}
        leads_by_training: Dict[str, int] = {}
        for l in leads:
            src = l.source or "inconnue"
            trn = l.training or "inconnue"
            leads_by_source[src] = leads_by_source.get(src, 0) + 1
            leads_by_training[trn] = leads_by_training.get(trn, 0) + 1

        report = DailyReportResponse(
            total_leads_all=len(leads),
            total_leads_24h=len(recent_leads),
            p0_leads_count=p0_count,
            p1_leads_count=p1_count,
            p2_leads_count=p2_count,
            unscored_leads_count=unscored,
            called_count=len(called_all),
            uncalled_count=len(uncalled_all),
            called_today=len(called_today_list),
            contacted_count=len(contacted),
            paid_count=len(paid_leads),
            payment_pending_count=len(pending_pay),
            conversion_rate_percent=conversion_rate,
            average_response_time_minutes=avg_response,
            leads_by_source=leads_by_source,
            leads_by_training=leads_by_training,
            report_generated_at=now.strftime("%d/%m/%Y à %H:%M UTC"),
        )

        logger.info(
            f"Rapport quotidien généré : {report.total_leads_all} leads total, "
            f"{report.total_leads_24h} nouveaux (24h), "
            f"{report.called_today} appelés aujourd'hui."
        )
        return report
