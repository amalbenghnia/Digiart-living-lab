from datetime import datetime, timezone

from app.business_rules.lead_rules import LeadBusinessRules
from app.core.config import DataSourceMode, LLMProviderName, Settings
from app.repositories.prototype_repository import PrototypeLeadRepository
from app.services.control_tower_service import ControlTowerService
from app.utils.rate_limiter import HourlyQuota


def test_control_tower_exposes_sla_and_unconfigured_integrations():
    settings = Settings(
        data_source_mode=DataSourceMode.PROTOTYPE,
        llm_provider=LLMProviderName.OLLAMA,
        automation_enabled=True,
        n8n_webhook_base_url=None,
    )
    service = ControlTowerService(
        settings=settings,
        repository=PrototypeLeadRepository(seed=True),
        rules=LeadBusinessRules(settings),
        quota=HourlyQuota(max_calls_per_hour=50),
    )

    snapshot = service.snapshot(now=datetime.now(timezone.utc))

    assert snapshot["summary"]["p0_sla_breaches"] >= 1
    assert any(item["status"] == "prototype" for item in snapshot["integrations"])
    assert any(item["type"] == "p0_call_sla" for item in snapshot["attention_queue"])
