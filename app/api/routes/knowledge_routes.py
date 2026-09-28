"""Read-only access to the approved internal knowledge base."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.container import Container, get_container

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/search")
def search_knowledge(
    query: str = Query(min_length=3, max_length=500),
    top_k: int = Query(default=3, ge=1, le=10),
    container: Container = Depends(get_container),
) -> dict:
    """Return the cited internal text used to ground agent responses."""
    return {"query": query, "results": container.rag_provider.search(query, top_k=top_k)}
