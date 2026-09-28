"""Shared pytest fixtures.

Design note: tests NEVER hit a real LLM or a real Google Sheet. The whole
point of the ports-and-adapters layout (LeadRepository, LLMProvider as
abstract interfaces) is that we can substitute a fully deterministic fake
for both in tests, so the suite runs in under a second, offline, in CI.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.business_rules.lead_rules import LeadBusinessRules
from app.core.config import DataSourceMode, LLMProviderName, Settings
from app.interfaces.rag import NullRAGProvider
from app.llm.base_provider import LLMProvider, LLMResponse
from app.models.lead import Lead, LeadStatus, PaymentStatus
from app.repositories.prototype_repository import PrototypeLeadRepository
from app.services.automation_service import AutomationService
from app.services.duplicate_service import DuplicateService
from app.services.lead_service import LeadService
from app.services.notification_service import NotificationService
from app.services.priority_service import PriorityService
from app.services.qualification_service import QualificationService
from app.services.task_service import TaskService
from app.utils.rate_limiter import HourlyQuota


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def settings() -> Settings:
    """A Settings instance with predictable, test-friendly thresholds —
    independent of whatever .env happens to contain on the machine running
    the suite."""
    return Settings(
        data_source_mode=DataSourceMode.PROTOTYPE,
        llm_provider=LLMProviderName.OLLAMA,
        lead_hot_response_hours=2.0,
        payment_overdue_days=3,
        follow_up_offset_days=1,
        duplicate_check_enabled=True,
        priority_p0_score_threshold=75.0,
        priority_p1_score_threshold=40.0,
        llm_max_calls_per_hour=50,
        automation_enabled=True,
        n8n_webhook_base_url=None,  # forces AutomationService into log-only stub mode
    )


@pytest.fixture
def rules(settings: Settings) -> LeadBusinessRules:
    return LeadBusinessRules(settings)


@pytest.fixture
def empty_repository() -> PrototypeLeadRepository:
    """Prototype repository with NO seed data — used when a test wants full
    control over exactly which leads exist."""
    return PrototypeLeadRepository(seed=False)


@pytest.fixture
def seeded_repository() -> PrototypeLeadRepository:
    """The repository with the realistic seed data described in its own
    docstring (includes an intentional duplicate phone, an overdue payment,
    a hot lead past threshold, and a follow-up due today)."""
    return PrototypeLeadRepository(seed=True)


class FakeLLMProvider(LLMProvider):
    """Deterministic stand-in for Ollama/OpenRouter. Returns a fixed, valid
    QualificationOutput-shaped JSON string unless the test overrides
    `next_response` — never makes a network call."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.next_response: str = (
            '{"intent": "information_request", "urgency": "medium", '
            '"summary": "Lead asks about start date.", '
            '"suggested_next_action": "Call within 2h with the schedule."}'
        )

    def generate(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        self.calls.append((system_prompt, user_prompt))
        return LLMResponse(text=self.next_response, model="fake-model", latency_ms=1.0)


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def quota(settings: Settings) -> HourlyQuota:
    return HourlyQuota(max_calls_per_hour=settings.llm_max_calls_per_hour)


@pytest.fixture
def qualification_service(rules, fake_llm, quota) -> QualificationService:
    return QualificationService(
        rules=rules, llm_provider=fake_llm, rag_provider=NullRAGProvider(), quota=quota
    )


@pytest.fixture
def automation_service(settings: Settings) -> AutomationService:
    return AutomationService(settings)


@pytest.fixture
def lead_service(seeded_repository, rules, qualification_service, automation_service) -> LeadService:
    duplicate_service = DuplicateService(seeded_repository, rules)
    priority_service = PriorityService(seeded_repository, rules)
    task_service = TaskService(seeded_repository)
    notification_service = NotificationService(automation_service)
    return LeadService(
        repository=seeded_repository,
        rules=rules,
        duplicate_service=duplicate_service,
        qualification_service=qualification_service,
        priority_service=priority_service,
        task_service=task_service,
        notification_service=notification_service,
        automation_service=automation_service,
    )


def make_lead(**overrides) -> Lead:
    """Factory for a minimal valid Lead — pass overrides for the field(s)
    under test to keep each test focused on one thing."""
    defaults = dict(
        id="lead-test-001",
        fullname="Test Lead",
        phone="+21699999999",
        email="test.lead@example.com",
        training="Python for AI",
        source="manual",
        status=LeadStatus.NEW,
        created_at=_now(),
        payment_status=PaymentStatus.NOT_APPLICABLE,
    )
    defaults.update(overrides)
    return Lead(**defaults)
