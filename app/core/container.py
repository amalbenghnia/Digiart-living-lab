"""Dependency injection container.

This is the single place in the codebase where concrete classes are chosen
and wired together. Every service and route depends on abstractions
(LeadRepository, LLMProvider, RAGProvider) — this file is the only one that
knows which concrete implementation backs each abstraction, based on
Settings. Swapping prototype -> Google Sheets, or Ollama -> OpenRouter,
never requires touching any file outside this one plus .env.
"""
from __future__ import annotations

from functools import lru_cache

from app.business_rules.lead_rules import LeadBusinessRules
from app.core.config import DataSourceMode, LLMProviderName, Settings, get_settings
from app.database.google_sheet import GoogleSheetClient
from app.interfaces.rag import FileRAGProvider, RAGProvider
from app.llm.base_provider import LLMProvider
from app.llm.ollama_provider import OllamaProvider
from app.llm.openrouter_provider import OpenRouterProvider
from app.repositories.base_repository import LeadRepository
from app.repositories.google_sheet_repository import GoogleSheetLeadRepository
from app.repositories.prototype_repository import PrototypeLeadRepository
from app.repositories.catalog_repository import CatalogRepository
from app.services.automation_service import AutomationService
from app.services.duplicate_service import DuplicateService
from app.services.lead_service import LeadService
from app.services.notification_service import NotificationService
from app.services.priority_service import PriorityService
from app.services.communication_service import CommunicationService
from app.services.qualification_service import QualificationService
from app.services.task_service import TaskService
from app.services.reporting_service import ReportingService
from app.services.sdr_copilot_service import SDRCopilotService
from app.services.content_agent_service import ContentAgentService
from app.services.control_tower_service import ControlTowerService
from app.services.hub_integration_service import HubIntegrationService
from app.utils.rate_limiter import HourlyQuota
# ── NEW: Course Recommendation & Agenda Engine ───────────────────────────────
from app.repositories.agenda_repository import AgendaRepository
from app.services.recommendation_service import RecommendationService
from app.services.roster_service import RosterService



def _build_repository(settings: Settings) -> LeadRepository:
    if settings.data_source_mode == DataSourceMode.PROTOTYPE:
        return PrototypeLeadRepository(seed=True)
    if settings.data_source_mode == DataSourceMode.GOOGLE_SHEET:
        client = GoogleSheetClient(settings)
        return GoogleSheetLeadRepository(client)
    raise ValueError(f"Unknown data source mode: {settings.data_source_mode}")


def _build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == LLMProviderName.OLLAMA:
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model_name=settings.llm_model_name,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if settings.llm_provider == LLMProviderName.OPENROUTER:
        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY must be set when LLM_PROVIDER=openrouter")
        return OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            model_name=settings.llm_model_name,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")


class Container:
    """Composition root. One instance lives for the lifetime of the app
    (see get_container / lru_cache below) so the prototype repository's
    in-memory data persists across requests within a single run."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.repository: LeadRepository = _build_repository(settings)
        self.rules = LeadBusinessRules(settings)
        self.llm_provider: LLMProvider = _build_llm_provider(settings)
        self.rag_provider: RAGProvider = FileRAGProvider(settings.knowledge_base_dir)
        self.quota = HourlyQuota(max_calls_per_hour=settings.llm_max_calls_per_hour)

        self.automation_service = AutomationService(settings)
        self.notification_service = NotificationService(self.automation_service)
        self.duplicate_service = DuplicateService(self.repository, self.rules)
        self.task_service = TaskService(self.repository)
        self.catalog_repository = CatalogRepository(data_dir="data")
        self.qualification_service = QualificationService(
            rules=self.rules,
            llm_provider=self.llm_provider,
            rag_provider=self.rag_provider,
            quota=self.quota,
            catalog_repo=self.catalog_repository,
        )
        self.priority_service = PriorityService(self.repository, self.rules, self.catalog_repository)
        self.communication_service = CommunicationService(
            llm_provider=self.llm_provider,
            rules=self.rules,
            quota=self.quota,
        )

        self.lead_service = LeadService(
            repository=self.repository,
            rules=self.rules,
            duplicate_service=self.duplicate_service,
            qualification_service=self.qualification_service,
            priority_service=self.priority_service,
            task_service=self.task_service,
            notification_service=self.notification_service,
            automation_service=self.automation_service,
        )
        self.reporting_service = ReportingService(self.repository)
        self.sdr_copilot_service = SDRCopilotService(self.repository, self.llm_provider, self.catalog_repository)
        self.hub_integration_service = HubIntegrationService(
            settings=self.settings,
            lead_service=self.lead_service,
            sdr_copilot_service=self.sdr_copilot_service,
        )
        self.content_agent_service = ContentAgentService(
            llm_provider=self.llm_provider,
            catalog_repo=self.catalog_repository,
        )
        # ── NEW: Course Recommendation & Agenda Engine ───────────────────────
        self.agenda_repo = AgendaRepository(settings)
        self.recommendation_service = RecommendationService(
            agenda_repo=self.agenda_repo,
            llm_provider=self.llm_provider,   # optional — only for reason text
        )
        self.roster_service = RosterService(agenda_repo=self.agenda_repo)
        self.control_tower_service = ControlTowerService(
            settings=self.settings,
            repository=self.repository,
            rules=self.rules,
            quota=self.quota,
        )
        
        from app.services.market_intelligence_service import MarketIntelligenceService
        self.market_intelligence_service = MarketIntelligenceService(
            llm_provider=self.llm_provider,
            agenda_repo=self.agenda_repo
        )


@lru_cache
def get_container() -> Container:
    return Container(get_settings())
