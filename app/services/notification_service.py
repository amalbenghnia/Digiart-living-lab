from __future__ import annotations

from app.core.logging import get_logger, log_event
from app.models.lead import Lead
from app.services.automation_service import AutomationService

logger = get_logger(__name__)


class NotificationService:
    """Thin, semantic layer on top of AutomationService: callers say *what*
    happened in business terms; this maps it to the right n8n trigger."""

    def __init__(self, automation: AutomationService):
        self._automation = automation

    def notify_hot_lead(self, lead: Lead) -> None:
        log_event(logger, "business_rule", "Hot lead notification sent", lead_id=lead.id)
        self._automation.trigger_notification(
            channel="chat",
            message=f"Lead chaud (P0) : {lead.fullname} — {lead.training}. À appeler sous 2h.",
            lead_id=lead.id,
        )

    def notify_payment_overdue(self, lead: Lead, days_overdue: int) -> None:
        log_event(
            logger, "business_rule", "Payment overdue notification sent",
            lead_id=lead.id, days_overdue=days_overdue,
        )
        self._automation.trigger_notification(
            channel="chat",
            message=f"Paiement en retard ({days_overdue}j) : {lead.fullname}.",
            lead_id=lead.id,
        )

    def notify_duplicate_detected(self, lead: Lead, existing_lead_id: str) -> None:
        self._automation.trigger_notification(
            channel="chat",
            message=f"Doublon détecté : {lead.fullname} correspond au lead {existing_lead_id}.",
            lead_id=lead.id,
        )

    def notify_uncalled_reminder(self, lead: Lead, hours_waiting: float) -> None:
        """Urgent reminder: a P0 lead has been waiting too long without a call."""
        log_event(
            logger, "business_rule", "Uncalled lead reminder sent",
            lead_id=lead.id, hours_waiting=hours_waiting,
        )
        self._automation.trigger_notification(
            channel="chat",
            message=(
                f"⚠️ RAPPEL URGENT : {lead.fullname} ({lead.training}) attend un appel "
                f"depuis {hours_waiting:.1f}h. Téléphone : {lead.phone}. "
                f"Ce lead P0 DOIT être rappelé immédiatement ou il sera réassigné."
            ),
            lead_id=lead.id,
        )
