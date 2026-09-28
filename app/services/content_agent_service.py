"""Content Agent Service — generates marketing content (LinkedIn & Instagram posts)
for DigiArt Living Lab courses, using real catalog and agenda data.

This service is the 4th agent in the ecosystem (after Lead, SDR Copilot, Reporting).
It never invents data: every date, tool name, and detail comes from the
CatalogRepository, ensuring marketing materials are always accurate.
"""
from __future__ import annotations

from datetime import datetime
import json
import re

from app.core.logging import get_logger, log_event
from app.exceptions.custom_exceptions import LLMTimeoutError, LLMValidationError
from app.llm.base_provider import LLMProvider
from app.prompts.content_prompt import (
    CONTENT_SYSTEM_PROMPT,
    LINKEDIN_POST_PROMPT,
    INSTAGRAM_POST_PROMPT,
    REGISTRATION_URL,
    build_course_data_block,
)
from app.repositories.catalog_repository import CatalogRepository

logger = get_logger(__name__)


class ContentAgentService:
    """Generates social media posts for DigiArt courses."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        catalog_repo: CatalogRepository,
    ):
        self._llm = llm_provider
        self._catalog = catalog_repo

    # ── Public API ──────────────────────────────────────────────

    def generate_social_post(
        self,
        course_title: str,
        platform: str = "linkedin",
    ) -> dict:
        """Generate a complete social media post for a course.

        Args:
            course_title: The name of the course (partial match supported).
            platform: "linkedin" or "instagram".

        Returns:
            A dict with keys: hook, body, cta, hashtags, image_prompt, course_title, platform.
        """
        log_event(
            logger, "api_call", "Content generation requested",
            course=course_title, platform=platform,
        )

        # 1. Fetch real course data
        course = self._catalog.get_course_details(course_title)
        if not course:
            raise LLMValidationError(
                f"Formation '{course_title}' introuvable dans le catalogue. "
                f"Formations disponibles : {', '.join(c.get('Course Title', '') for c in self._catalog.get_all_courses())}"
            )

        agenda = self._catalog.get_course_agenda(course_title)
        course_data_block = build_course_data_block(course, agenda)

        # 2. Select prompt template
        if platform.lower() == "instagram":
            user_prompt = INSTAGRAM_POST_PROMPT.format(
                course_data=course_data_block,
                registration_url=REGISTRATION_URL,
            )
        else:
            user_prompt = LINKEDIN_POST_PROMPT.format(
                course_data=course_data_block,
                registration_url=REGISTRATION_URL,
            )

        # 3. Call LLM
        try:
            response = self._llm.generate(
                system_prompt=CONTENT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=800,
            )
        except LLMTimeoutError:
            raise

        # 4. Parse structured response
        sections = self._extract_sections(response.text)

        import urllib.parse
        from app.services.image_generation_service import generate_course_image
        image_prompt = f"Branded DigiArt promotional image for: {course.get('Course Title', course_title)}"
        
        # Absolute path on disk for n8n to read
        from pathlib import Path
        import os
        base_dir = Path(__file__).parent.parent.parent
        
        try:
            image_url = generate_course_image(course.get("Course Title", course_title))
            image_filename = image_url.split("/")[-1]
            image_local_path = str(base_dir / "static" / "generated_images" / image_filename)
        except Exception as img_exc:
            log_event(logger, "error", f"Image generation failed: {img_exc}")
            # Fallback to simple Pollinations URL
            encoded_prompt = urllib.parse.quote(image_prompt)
            image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1080&nologo=true"
            image_local_path = ""

        result = {
            "course_title": course.get("Course Title", course_title),
            "platform": platform.lower(),
            "hook": str(sections.get("hook", "")),
            "body": str(sections.get("body", "")),
            "cta": str(sections.get("cta", "")),
            "hashtags": str(sections.get("hashtags", "")),
            "image_prompt": image_prompt,
            "image_url": image_url,
            "image_local_path": image_local_path,
            "full_post": self._assemble_full_post(sections),
            "generated_at": datetime.now().isoformat(),
            "model": response.model,
            "latency_ms": float(response.latency_ms) if response.latency_ms else 0.0,
        }

        log_event(
            logger, "api_call", "Content generated successfully",
            course=course_title, platform=platform,
            latency_ms=response.latency_ms,
        )
        return result

    def generate_both_platforms(self, course_title: str) -> dict:
        """Generate posts for both LinkedIn and Instagram in one call."""
        linkedin = self.generate_social_post(course_title, "linkedin")
        instagram = self.generate_social_post(course_title, "instagram")
        return {
            "course_title": linkedin["course_title"],
            "linkedin": linkedin,
            "instagram": instagram,
        }

    def get_upcoming_courses(self, days_ahead: int = 14) -> list[dict]:
        """Return courses whose next session is within `days_ahead` days."""
        if self._catalog.agenda_df is None:
            return []

        today = datetime.now().date()
        upcoming = []

        for _, row in self._catalog.agenda_df.iterrows():
            try:
                session_date = datetime.strptime(
                    str(row.get("Next Session Date", "")), "%Y-%m-%d"
                ).date()
                days_to_start = (session_date - today).days
                if 0 < days_to_start <= days_ahead:
                    course_details = self._catalog.get_course_details(
                        str(row.get("Course Title", ""))
                    )
                    upcoming.append({
                        "course_title": row.get("Course Title"),
                        "next_session_date": str(row.get("Next Session Date")),
                        "days_to_start": days_to_start,
                        "format": row.get("Format", ""),
                        "available_seats": row.get("Available Seats", ""),
                        "instructor": row.get("Instructor", ""),
                        "description": course_details.get("Short Description", "") if course_details else "",
                    })
            except (ValueError, TypeError):
                continue

        upcoming.sort(key=lambda x: x["days_to_start"])
        return upcoming

    # ── Private helpers ─────────────────────────────────────────

    def _extract_sections(self, text: str) -> dict[str, str]:
        """Extract JSON from LLM output."""
        try:
            parsed = None
            # Try to find a JSON block
            match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                parsed = json.loads(match.group(1))
            else:
                # Try parsing the raw text
                parsed = json.loads(text)
                
            if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
                parsed = parsed[0]
                
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
            
        # Fallback for small models that might mess up JSON
        hook_match = re.search(r'"hook"\s*:\s*"(.*?)"', text, re.DOTALL)
        body_match = re.search(r'"body"\s*:\s*"(.*?)"', text, re.DOTALL)
        cta_match = re.search(r'"cta"\s*:\s*"(.*?)"', text, re.DOTALL)
        hashtags_match = re.search(r'"hashtags"\s*:\s*"(.*?)"', text, re.DOTALL)
        return {
            "hook": hook_match.group(1).replace("\\n", "\n") if hook_match else "",
            "body": body_match.group(1).replace("\\n", "\n") if body_match else "",
            "cta": cta_match.group(1).replace("\\n", "\n") if cta_match else "",
            "hashtags": hashtags_match.group(1).replace("\\n", "\n") if hashtags_match else ""
        }

    def _assemble_full_post(self, sections: dict[str, str]) -> str:
        """Assemble the sections into a copy-paste-ready post."""
        parts = []
        if sections.get("hook"):
            parts.append(str(sections["hook"]))
        if sections.get("body"):
            parts.append(str(sections["body"]))
        if sections.get("cta"):
            parts.append(str(sections["cta"]))
        if sections.get("hashtags"):
            parts.append(str(sections["hashtags"]))
        return "\n\n".join(parts)
