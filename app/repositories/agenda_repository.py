"""AgendaRepository — reads and writes to the 3 new Google Sheet tabs.

Tabs managed here:
  - Courses         → CourseModel list
  - Agenda          → SessionModel list + reschedule
  - Market_Trends   → MarketTrendModel list

This repository is COMPLETELY SEPARATE from catalog_repository.py.
It does not touch any existing code. It uses the same GoogleSheetClient
pattern (open sheet by ID, access named worksheet) but targets different tabs.

For the prototype phase, Google Sheets is the data layer.
The repository interface is designed so that swapping to PostgreSQL later
only requires implementing the same method signatures against a DB driver —
all services calling this repository stay untouched.
"""
from __future__ import annotations

import time
import gspread
from google.oauth2.service_account import Credentials
from typing import List, Optional

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.cache import ttl_cache
from app.models.course import CourseModel, SessionModel, MarketTrendModel
from app.exceptions.custom_exceptions import DataSourceUnavailableError

logger = get_logger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

_TAB_COURSES = "Courses"
_TAB_AGENDA  = "Agenda"
_TAB_TRENDS  = "Market_Trends"


class AgendaRepository:
    """Reads and writes the Courses, Agenda, and Market_Trends tabs
    in the same Google Sheet used by the Lead Agent."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: gspread.Client | None = None

    # ── Internal helpers ────────────────────────────────────────────────────

    def _connect(self) -> gspread.Client:
        if self._client is not None:
            return self._client
        if not self._settings.google_service_account_json_path:
            raise DataSourceUnavailableError("GOOGLE_SERVICE_ACCOUNT_JSON_PATH not set")
        try:
            creds = Credentials.from_service_account_file(
                self._settings.google_service_account_json_path, scopes=_SCOPES
            )
            self._client = gspread.authorize(creds)
            return self._client
        except Exception as exc:
            raise DataSourceUnavailableError(f"Google Sheets auth failed: {exc}") from exc

    def _get_tab(self, tab_name: str) -> gspread.Worksheet:
        if not self._settings.google_sheet_id:
            raise DataSourceUnavailableError("GOOGLE_SHEET_ID not set")
        client = self._connect()
        try:
            sheet = client.open_by_key(self._settings.google_sheet_id)
            return sheet.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            raise DataSourceUnavailableError(
                f"Worksheet '{tab_name}' not found in the Google Sheet. "
                f"Please create it with the correct headers first."
            )
        except Exception as exc:
            raise DataSourceUnavailableError(f"Could not open tab '{tab_name}': {exc}") from exc

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    # ── Courses tab ─────────────────────────────────────────────────────────

    @ttl_cache(ttl_seconds=60)
    def get_all_courses(self) -> List[CourseModel]:
        """Read all rows from the 'Courses' tab.

        Expected headers:
        Course ID | Title | Category | Level | Capacity | Status
        """
        try:
            ws = self._get_tab(_TAB_COURSES)
            rows = ws.get_all_records()
            courses = []
            for row in rows:
                course_id = str(row.get("Course ID", "")).strip()
                title = str(row.get("Title", "")).strip()
                if not course_id or not title:
                    continue
                courses.append(CourseModel(
                    course_id=course_id,
                    title=title,
                    category=str(row.get("Category", "")).strip(),
                    level=str(row.get("Level", "")).strip(),
                    capacity=self._safe_int(row.get("Capacity", 20), 20),
                    status=str(row.get("Status", "active")).strip().lower(),
                ))
            logger.info(f"AgendaRepository: loaded {len(courses)} courses")
            return courses
        except DataSourceUnavailableError:
            logger.warning(f"'Courses' tab not accessible — returning empty list")
            return []

    def get_course_by_id(self, course_id: str) -> Optional[CourseModel]:
        courses = self.get_all_courses()
        for c in courses:
            if c.course_id == course_id:
                return c
        return None

    # ── Agenda tab ──────────────────────────────────────────────────────────

    @ttl_cache(ttl_seconds=15)
    def get_all_sessions(self) -> List[SessionModel]:
        """Read all rows from the 'Agenda' tab.

        Expected headers:
        Session ID | Course ID | Title | Date | Start Time | End Time | Capacity | Format | Status
        """
        try:
            ws = self._get_tab(_TAB_AGENDA)
            rows = ws.get_all_records()
            sessions = []
            for row in rows:
                session_id = str(row.get("Session ID", "")).strip()
                course_id = str(row.get("Course ID", "")).strip()
                if not session_id or not course_id:
                    continue
                sessions.append(SessionModel(
                    session_id=session_id,
                    course_id=course_id,
                    title=str(row.get("Title", "")).strip(),
                    date=str(row.get("Date", "")).strip(),
                    start_time=str(row.get("Start Time", "09:00")).strip(),
                    end_time=str(row.get("End Time", "17:00")).strip(),
                    capacity=self._safe_int(row.get("Capacity", 20), 20),
                    format=str(row.get("Format", "On-site")).strip(),
                    status=str(row.get("Status", "open")).strip().lower(),
                ))
            logger.info(f"AgendaRepository: loaded {len(sessions)} sessions")
            return sessions
        except DataSourceUnavailableError:
            logger.warning("'Agenda' tab not accessible — returning empty list")
            return []

    def get_sessions_by_course_id(self, course_id: str) -> List[SessionModel]:
        return [s for s in self.get_all_sessions() if s.course_id == course_id]

    def update_session_date(self, session_id: str, new_date: str) -> bool:
        """Reschedule a session. Called by PUT /agenda/{session_id}/reschedule.
        Updates the 'Date' cell in the Agenda tab. Returns True on success.

        This is the operation triggered by Drag & Drop in the Dashboard.
        """
        try:
            ws = self._get_tab(_TAB_AGENDA)
            rows = ws.get_all_records()
            headers = ws.row_values(1)

            if "Session ID" not in headers or "Date" not in headers:
                raise DataSourceUnavailableError("Agenda tab missing 'Session ID' or 'Date' columns")

            session_col_idx = headers.index("Session ID") + 1
            date_col_idx = headers.index("Date") + 1

            for i, row in enumerate(rows, start=2):  # row 1 = headers
                if str(row.get("Session ID", "")).strip() == session_id:
                    ws.update_cell(i, date_col_idx, new_date)
                    logger.info(f"Session {session_id} rescheduled to {new_date}")
                    return True

            logger.warning(f"Session {session_id} not found for reschedule")
            return False
        except DataSourceUnavailableError as e:
            logger.error(f"Reschedule failed: {e}")
            return False

    def add_session(self, session: SessionModel) -> bool:
        """Append a new session row to the Agenda tab."""
        try:
            ws = self._get_tab(_TAB_AGENDA)
            ws.append_row([
                session.session_id,
                session.course_id,
                session.title,
                session.date,
                session.start_time,
                session.end_time,
                session.capacity,
                session.format,
                session.status,
            ])
            logger.info(f"Session {session.session_id} added to Agenda tab")
            return True
        except Exception as exc:
            logger.error(f"add_session failed: {exc}")
            return False

    # ── Market_Trends tab ───────────────────────────────────────────────────

    @ttl_cache(ttl_seconds=60)
    def get_market_trends(self) -> List[MarketTrendModel]:
        """Read all rows from the 'Market_Trends' tab.

        Expected headers:
        Course ID | Title | Market Demand | Industry Trend | Business Priority | Notes
        """
        try:
            ws = self._get_tab(_TAB_TRENDS)
            rows = ws.get_all_records()
            trends = []
            for row in rows:
                if not row.get("Course ID") or not row.get("Title"):
                    continue
                trends.append(MarketTrendModel(
                    course_id=str(row["Course ID"]).strip(),
                    title=str(row["Title"]).strip(),
                    market_demand=self._safe_float(row.get("Market Demand", 50), 50),
                    industry_trend=self._safe_float(row.get("Industry Trend", 50), 50),
                    business_priority=self._safe_float(row.get("Business Priority", 50), 50),
                    notes=str(row.get("Notes", "")).strip(),
                    confidence=self._safe_float(row.get("Confidence", 0.0), 0.0),
                    evidence_count=int(self._safe_float(row.get("Evidence Count", 0), 0)),
                    last_updated=str(row.get("Last Updated", "")).strip(),
                ))
            logger.info(f"AgendaRepository: loaded {len(trends)} market trends")
            return trends
        except DataSourceUnavailableError:
            logger.warning("'Market_Trends' tab not accessible — returning empty list")
            return []

    def get_trend_by_course_id(self, course_id: str) -> Optional[MarketTrendModel]:
        for t in self.get_market_trends():
            if t.course_id == course_id:
                return t
        return None

    def invalidate_market_cache(self) -> None:
        """Force cache invalidation so the next read fetches fresh data from Sheets."""
        if hasattr(self.get_market_trends, "cache_clear"):
            self.get_market_trends.cache_clear()  # type: ignore[attr-defined]
        if hasattr(self.get_all_courses, "cache_clear"):
            self.get_all_courses.cache_clear()    # type: ignore[attr-defined]
        if hasattr(self.get_all_sessions, "cache_clear"):
            self.get_all_sessions.cache_clear()   # type: ignore[attr-defined]
        logger.info("AgendaRepository: all caches invalidated")
