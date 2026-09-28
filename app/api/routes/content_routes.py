"""Content Agent endpoints.

POST /content/generate-post          -> generate a social media post for one platform
POST /content/generate-both          -> generate posts for LinkedIn + Instagram
GET  /content/upcoming-courses       -> list courses starting within N days
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.schemas.content_schema import (
    BothPlatformsRequest,
    BothPlatformsResponse,
    SocialPostRequest,
    SocialPostResponse,
    UpcomingCoursesListResponse,
)
from app.core.container import Container, get_container
from app.core.logging import get_logger, log_event
from app.exceptions.custom_exceptions import (
    BudgetExceededError,
    LLMTimeoutError,
    LLMValidationError,
)

router = APIRouter(tags=["content"])
logger = get_logger(__name__)


@router.post("/content/generate-post", response_model=SocialPostResponse)
def generate_social_post(
    payload: SocialPostRequest,
    container: Container = Depends(get_container),
) -> SocialPostResponse:
    """Generate a social media post for a specific course and platform."""
    log_event(
        logger, "api_call", "POST /content/generate-post",
        course=payload.course_title, platform=payload.platform,
    )
    try:
        result = container.content_agent_service.generate_social_post(
            course_title=payload.course_title,
            platform=payload.platform,
        )
    except LLMValidationError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BudgetExceededError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    return SocialPostResponse(**result)


@router.post("/content/generate-both", response_model=BothPlatformsResponse)
def generate_both_platforms(
    payload: BothPlatformsRequest,
    container: Container = Depends(get_container),
) -> BothPlatformsResponse:
    """Generate posts for both LinkedIn and Instagram for a course."""
    log_event(
        logger, "api_call", "POST /content/generate-both",
        course=payload.course_title,
    )
    try:
        result = container.content_agent_service.generate_both_platforms(
            course_title=payload.course_title,
        )
    except LLMValidationError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BudgetExceededError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    return BothPlatformsResponse(**result)


@router.get("/content/upcoming-courses", response_model=UpcomingCoursesListResponse)
def upcoming_courses(
    days_ahead: int = Query(default=14, ge=1, le=90, description="Nombre de jours à venir"),
    container: Container = Depends(get_container),
) -> UpcomingCoursesListResponse:
    """List courses with upcoming sessions (for auto-content generation)."""
    log_event(logger, "api_call", "GET /content/upcoming-courses", days_ahead=days_ahead)
    courses = container.content_agent_service.get_upcoming_courses(days_ahead=days_ahead)
    return UpcomingCoursesListResponse(count=len(courses), courses=courses)
