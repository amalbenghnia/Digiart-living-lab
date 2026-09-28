"""Callbacks used by the existing DigiArt Task Manager Hub."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.schemas.hub_schema import HubTaskCompletionRequest, HubTaskCompletionResponse
from app.core.container import Container, get_container

router = APIRouter(prefix="/integrations/hub", tags=["hub integration"])


@router.get("/manifest")
def get_hub_manifest() -> dict:
    """Public, non-sensitive contract summary for the Hub implementation team."""
    return {
        "version": "1.0",
        "task_upsert": {
            "delivery": "n8n create-task webhook",
            "idempotency_key": "task_id / X-Idempotency-Key",
        },
        "task_completion_callback": {
            "method": "POST",
            "path": "/integrations/hub/task-completed",
            "authentication": "X-Hub-Secret",
        },
    }


@router.post("/task-completed", response_model=HubTaskCompletionResponse)
def task_completed(
    payload: HubTaskCompletionRequest,
    x_hub_secret: str | None = Header(default=None),
    container: Container = Depends(get_container),
) -> HubTaskCompletionResponse:
    service = container.hub_integration_service
    try:
        service.verify_secret(x_hub_secret)
        result = service.mark_task_completed(
            lead_id=payload.lead_id,
            actor_id=payload.actor_id,
            outcome=payload.outcome,
            notes=payload.notes,
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return HubTaskCompletionResponse(task_id=payload.task_id, **result)
