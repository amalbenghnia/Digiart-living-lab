"""Request/response schemas for the /content/* endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SocialPostRequest(BaseModel):
    course_title: str = Field(..., min_length=1, examples=["XR Development"])
    platform: str = Field(
        default="linkedin",
        description="Target platform: 'linkedin' or 'instagram'",
        examples=["linkedin", "instagram"],
    )


class BothPlatformsRequest(BaseModel):
    course_title: str = Field(..., min_length=1, examples=["XR Development"])


class SocialPostResponse(BaseModel):
    course_title: str
    platform: str
    hook: str
    body: str
    cta: str
    hashtags: str
    image_prompt: str
    image_url: str = ""
    image_local_path: str = ""
    full_post: str
    generated_at: str
    model: str
    latency_ms: float


class BothPlatformsResponse(BaseModel):
    course_title: str
    linkedin: SocialPostResponse
    instagram: SocialPostResponse


class UpcomingCourseResponse(BaseModel):
    course_title: str
    next_session_date: str
    days_to_start: int
    format: str
    available_seats: str | int
    instructor: str
    description: str


class UpcomingCoursesListResponse(BaseModel):
    count: int
    courses: list[UpcomingCourseResponse]
