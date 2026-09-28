"""GET /recommendations — ranked course list from the deterministic engine."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from typing import List

from app.core.container import Container, get_container
from app.models.course import RecommendationResult

router = APIRouter(tags=["recommendations"])


@router.get("/recommendations", response_model=List[RecommendationResult])
def get_recommendations(
    top: int = 0,
    container: Container = Depends(get_container),
):
    """Return all courses ranked by the deterministic scoring algorithm.

    Query params:
      top=N  → return only top N results (0 = all)
    """
    leads = container.lead_service.get_all_leads()
    results = container.recommendation_service.get_recommendations(leads)
    if top > 0:
        results = results[:top]
    return results
