"""Central configuration, loaded once from environment variables (.env).

Nothing in this project should hardcode a threshold, a sheet name, or a
provider choice — everything lives here so a non-developer can retune the
agent by editing .env instead of touching Python code.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DataSourceMode(str, Enum):
    """Which repository implementation to use. This is the switch that lets
    us start with 'prototype' (in-memory, seeded fake data) and flip to
    'google_sheet' later without changing a single line of service code."""

    PROTOTYPE = "prototype"
    GOOGLE_SHEET = "google_sheet"


class LLMProviderName(str, Enum):
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "lead-agent"
    environment: str = "development"
    log_level: str = "INFO"

    # --- Data source ---
    data_source_mode: DataSourceMode = DataSourceMode.PROTOTYPE
    google_sheet_id: str | None = None
    google_sheet_worksheet_name: str = "Leads"
    google_service_account_json_path: str | None = None

    # --- LLM ---
    llm_provider: LLMProviderName = LLMProviderName.OLLAMA
    llm_model_name: str = "qwen3:8b"
    llm_timeout_seconds: int = 20
    ollama_base_url: str = "http://localhost:11434"
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # --- Business rules thresholds (all overridable) ---
    lead_hot_response_hours: float = Field(default=2.0, description="P0 threshold: call within N hours")
    payment_overdue_days: int = Field(default=3, description="Flag unpaid confirmed leads after N days")
    follow_up_offset_days: int = Field(default=1, description="J+1 default follow-up offset")
    duplicate_check_enabled: bool = True

    priority_p0_score_threshold: float = 75.0
    priority_p1_score_threshold: float = 40.0

    # --- Budget / quota guardrail ---
    llm_max_calls_per_hour: int = 50

    # --- Automation (n8n) ---
    n8n_webhook_base_url: str | None = Field(
        default=None, description="e.g. https://n8n.digiart.local/webhook"
    )
    n8n_webhook_secret: str | None = None
    automation_enabled: bool = True

    # --- Internal knowledge base ---
    knowledge_base_dir: str = "app/data"

    # --- Existing Task Manager integration ---
    # This records the intended Hub endpoint. The current adapter delivers
    # task events through n8n until the Hub's authenticated task API is known.
    task_manager_api_base_url: str | None = None
    hub_integration_secret: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Settings are read once and cached — avoids re-parsing .env on every request."""
    return Settings()
