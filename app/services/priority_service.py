from __future__ import annotations

from app.business_rules.lead_rules import LeadBusinessRules, PriorityResult
from app.core.logging import get_logger, log_event
from app.models.lead import Lead
from app.repositories.base_repository import LeadRepository

logger = get_logger(__name__)


class PriorityService:
    """Priority is a pure business-rule calculation. The LLM never assigns
    a priority directly — it may inform the *score* upstream (via
    QualificationService's urgency field, mapped by the caller), but the
    P0/P1/P2 threshold logic itself always stays in Python, auditable."""

    def __init__(self, repository: LeadRepository, rules: LeadBusinessRules, catalog_repo=None):
        self._repository = repository
        self._rules = rules
        self._catalog_repo = catalog_repo

    def compute_and_persist(self, lead: Lead) -> tuple[Lead, PriorityResult]:
        days_to_start = None
        if self._catalog_repo and lead.training:
            agenda = self._catalog_repo.get_course_agenda(lead.training)
            if agenda and agenda.get("Next Session Date"):
                try:
                    from datetime import datetime
                    session_date = datetime.strptime(agenda["Next Session Date"], "%Y-%m-%d").date()
                    days_to_start = (session_date - datetime.now().date()).days
                except Exception:
                    pass

        result = self._rules.compute_priority(lead, days_to_start=days_to_start)
        
        # Sync followup date with agenda if not set
        if not lead.next_followup_date:
            lead.next_followup_date = self._rules.compute_initial_followup_date(days_to_start)
            # Update the lead repo explicitly for the followup date
            self._repository.update_lead(lead)
            
        updated = self._repository.update_priority(lead.id, result.priority, lead.score)
        log_event(
            logger, "business_rule", "Priority computed",
            lead_id=lead.id, priority=result.priority, reason=result.reason,
            followup=lead.next_followup_date
        )
        return updated, result
