from __future__ import annotations

from app.business_rules.lead_rules import DuplicateCheckResult, LeadBusinessRules
from app.core.logging import get_logger, log_event
from app.models.lead import Lead
from app.repositories.base_repository import LeadRepository

logger = get_logger(__name__)


class DuplicateService:
    def __init__(self, repository: LeadRepository, rules: LeadBusinessRules):
        self._repository = repository
        self._rules = rules

    def check(self, lead: Lead) -> DuplicateCheckResult:
        existing = self._repository.get_all_leads()
        result = self._rules.check_duplicate(lead, existing)
        log_event(
            logger, "business_rule", "Duplicate check executed",
            lead_id=lead.id, is_duplicate=result.is_duplicate,
            matched_field=result.matched_field,
        )
        return result
