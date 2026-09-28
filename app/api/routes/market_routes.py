from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from app.core.container import Container, get_container

router = APIRouter(prefix="/market", tags=["market"])


@router.post("/refresh")
async def refresh_market_trends(container: Container = Depends(get_container)):
    """Trigger the Market Intelligence Agent.

    For each active course:
    1. Collects real evidence from 4 sources: Remotive, Arbeitnow, ArXiv, DuckDuckGo
    2. Sends collected snippets to the local LLM (qwen2.5:1.5b via Ollama) for analysis
    3. Writes computed scores to the Google Sheets Market_Trends tab
    4. Invalidates the cache so /recommendations reflects new data immediately

    Takes 2-5 minutes for 12 courses (network + LLM inference per course).

    Response includes:
      - status, processed, errors, model_used
      - results: per-course summary with market_demand, industry_trend, confidence
    """
    svc = container.market_intelligence_service
    result = await svc.refresh_all_market_trends()
    return JSONResponse(content=result)


@router.get("/status")
def get_market_status(container: Container = Depends(get_container)):
    """Return the current market trend data (what is in the Google Sheet right now).

    Useful for checking scores without triggering a full refresh.
    Includes confidence, evidence_count, and last_updated fields added by MI v2.
    """
    trends = container.agenda_repo.get_market_trends()
    return [
        {
            "course_id": t.course_id,
            "title": t.title,
            "market_demand": t.market_demand,
            "industry_trend": t.industry_trend,
            "business_priority": t.business_priority,
            "confidence": t.confidence,
            "evidence_count": t.evidence_count,
            "last_updated": t.last_updated,
            "notes": t.notes,
        }
        for t in trends
    ]
