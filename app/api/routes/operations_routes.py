"""Operational visibility endpoints for the DigiArt AI layer."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.container import Container, get_container

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/control-tower")
def get_control_tower(container: Container = Depends(get_container)) -> dict:
    """Expose SLAs, agent coverage and unresolved integration dependencies."""
    return container.control_tower_service.snapshot()
