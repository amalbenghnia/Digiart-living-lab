"""FastAPI application entrypoint.

Run with:
    uvicorn app.main:app --reload --port 8000

Or via Docker:
    docker compose up
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api.routes.dashboard_routes import router as dashboard_router
from app.api.routes.lead_routes import router as lead_router
from app.api.routes.report_routes import router as report_router
from app.api.routes.sdr_routes import router as sdr_router
from app.api.routes.content_routes import router as content_router

from app.api.routes.recommendation_routes import router as recommendation_router
from app.api.routes.agenda_routes import router as agenda_router
from app.api.routes.roster_routes import router as roster_router
from app.api.routes.operations_routes import router as operations_router
from app.api.routes.hub_integration_routes import router as hub_integration_router
from app.api.routes.knowledge_routes import router as knowledge_router
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.core.container import get_container
from app.core.logging import get_logger, log_event, setup_logging
from app.exceptions.custom_exceptions import LeadAgentError

logger = get_logger(__name__)


def _warm_up_llm() -> None:
    """Warm up the LLM provider to avoid cold-start timeouts on the first request."""
    settings = get_settings()
    try:
        container = get_container()
        container.llm_provider.generate(
            system_prompt="You are a warm-up ping.", user_prompt="ping", max_tokens=4
        )
        log_event(logger, "llm_call", "LLM warm-up succeeded", provider=settings.llm_provider)
    except Exception as exc:  # noqa: BLE001 — warm-up must never crash startup
        log_event(
            logger, "error", "LLM warm-up failed (will retry lazily on first real request)",
            provider=settings.llm_provider, error=str(exc),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    log_event(
        logger, "api_call", "Lead Agent starting up",
        environment=settings.environment,
        data_source_mode=settings.data_source_mode,
        llm_provider=settings.llm_provider,
    )
    # Fire-and-forget: don't await, so startup completes immediately even if
    # Ollama takes 30-60s to load the model into GPU/CPU memory.
    asyncio.get_event_loop().run_in_executor(None, _warm_up_llm)
    yield
    log_event(logger, "api_call", "Lead Agent shutting down")


app = FastAPI(
    title="DigiArt Living Lab — Lead Agent",
    description=(
        "AI Lead Agent MVP: qualifies leads, computes priority, detects duplicates, and prepares SDR work."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lead_router)
app.include_router(dashboard_router)
app.include_router(report_router)
app.include_router(sdr_router)
app.include_router(content_router)

app.include_router(recommendation_router)
app.include_router(agenda_router)
app.include_router(roster_router)
app.include_router(operations_router)
app.include_router(hub_integration_router)
app.include_router(knowledge_router)

# Market Intelligence & Evidence
from app.api.routes.market_routes import router as market_router
from app.api.routes.evidence_routes import router as evidence_router
app.include_router(market_router)
app.include_router(evidence_router)

_static_dir = Path(__file__).parent.parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

_dashboard_dir = Path(__file__).parent.parent / "dashboard"
_dashboard_dir.mkdir(exist_ok=True)
app.mount("/dashboard", StaticFiles(directory=str(_dashboard_dir), html=True), name="dashboard")


# Hub Dashboard (HTML served by FastAPI)
_templates_dir = Path(__file__).parent.parent / "templates"
_templates_dir.mkdir(exist_ok=True)
_templates = Jinja2Templates(directory=str(_templates_dir))


@app.get("/hub", tags=["hub"])
def hub_dashboard(request: Request):
    """Serve the DigiArt AI Management Hub — Course Recommendation, Agenda & Roster."""
    return _templates.TemplateResponse(request=request, name="hub.html")


@app.get("/control-tower", tags=["hub"])
def control_tower_dashboard(request: Request):
    """Serve the operational view intended for the existing Hub navigation."""
    return _templates.TemplateResponse(request=request, name="control_tower.html")





@app.exception_handler(LeadAgentError)
async def lead_agent_error_handler(request: Request, exc: LeadAgentError) -> JSONResponse:
    """Catch-all for any unhandled domain exception."""
    log_event(logger, "error", "Unhandled domain exception", path=str(request.url), error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc), "type": type(exc).__name__},
    )


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok"}
