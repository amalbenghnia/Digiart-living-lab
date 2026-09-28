"""RosterService — live enrollment view: Agenda × Leads.

MATCHING STRATEGY (3 tiers, most reliable first):
  Tier 1 — Exact course_id match (lead.training == "C001")
  Tier 2 — Exact full title match (lead.training == "Design and Deploy Multi-Agent AI Systems")
  Tier 3 — Multi-word fuzzy: if ≥3 significant words from training appear in session title

REGISTERED STATUSES (case-insensitive):
  paid, confirmed_unpaid, confirmed, registered, inscrit, not_applicable (temporary workaround)

DESIGN: Roster is never stored. Always computed on-the-fly.
"""
from __future__ import annotations

import re
from typing import List, Optional

from app.core.logging import get_logger, log_event
from app.models.course import RosterEntry, SessionModel
from app.repositories.agenda_repository import AgendaRepository

logger = get_logger(__name__)

# Statuses that count as "registered" — normalised to lowercase
_REGISTERED_STATUSES = {
    "paid", "confirmed_unpaid", "confirmed", "registered",
    "inscrit", "inscrits", "not_applicable",  # fallback for demo
}

# Common words to ignore during fuzzy matching
_STOP_WORDS = {
    "and", "with", "for", "the", "a", "an", "in", "on", "of", "to",
    "design", "deploy", "create", "build", "learn", "using", "your",
    "how", "practical", "advanced", "introduction", "intro",
}


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).strip()


def _significant_words(text: str) -> set:
    return {w for w in _normalise(text).split() if w not in _STOP_WORDS and len(w) >= 3}


class RosterService:
    """Computes the live enrollment state for each scheduled session."""

    def __init__(self, agenda_repo: AgendaRepository):
        self._agenda_repo = agenda_repo

    @staticmethod
    def _is_registered(lead) -> bool:
        """Check if the lead status counts as enrolled."""
        raw_status = str(getattr(lead, "status", "") or "").strip().lower()
        raw_payment = str(getattr(lead, "payment_status", "") or "").strip().lower()
        return raw_status in _REGISTERED_STATUSES or raw_payment in _REGISTERED_STATUSES

    @staticmethod
    def _lead_matches_session(lead, session: SessionModel) -> bool:
        """3-tier matching: exact course_id → exact title → fuzzy keywords."""
        training_raw = str(getattr(lead, "training", "") or "").strip()
        if not training_raw:
            return False

        # Tier 1: Exact course_id
        if training_raw == session.course_id:
            return True

        # Tier 2: Exact full title (case-insensitive)
        if _normalise(training_raw) == _normalise(session.title):
            return True

        # Tier 3: Fuzzy — ≥3 significant shared words
        lead_words = _significant_words(training_raw)
        sess_words = _significant_words(session.title)
        shared = lead_words & sess_words
        if len(shared) >= 3:
            return True

        return False

    def _count_registrations(self, session: SessionModel, all_leads: list) -> tuple[int, list]:
        """Count enrolled leads. Returns (count, debug_list)."""
        enrolled = []
        for lead in all_leads:
            if self._is_registered(lead) and self._lead_matches_session(lead, session):
                enrolled.append({
                    "lead_id": getattr(lead, "id", "?"),
                    "name": getattr(lead, "fullname", "?"),
                    "training": getattr(lead, "training", ""),
                    "status": getattr(lead, "status", ""),
                    "payment": getattr(lead, "payment_status", ""),
                })
        return len(enrolled), enrolled

    def get_roster(self, all_leads: list) -> List[RosterEntry]:
        """Compute roster for all active sessions."""
        sessions = self._agenda_repo.get_all_sessions()
        active = [s for s in sessions if s.status not in ("cancelled", "completed")]

        entries: list[RosterEntry] = []
        for session in active:
            registered, _ = self._count_registrations(session, all_leads)
            available = max(session.capacity - registered, 0)
            fill_rate = round(
                (registered / session.capacity * 100) if session.capacity > 0 else 100.0, 1
            )
            fill_status = RosterEntry.compute_fill_status(registered, session.capacity)
            entries.append(RosterEntry(
                session_id=session.session_id,
                course_id=session.course_id,
                title=session.title,
                date=session.date,
                format=session.format,
                capacity=session.capacity,
                registered=registered,
                available=available,
                fill_rate=fill_rate,
                fill_status=fill_status,
            ))

        entries.sort(key=lambda e: e.date)
        log_event(
            logger, "api_call", "Roster computed",
            sessions=len(entries),
            total_registered=sum(e.registered for e in entries),
            full=sum(1 for e in entries if e.fill_status == "Full"),
        )
        return entries

    def get_roster_debug(self, all_leads: list) -> list:
        """Debug view: for each session, show exactly which leads matched and why."""
        sessions = self._agenda_repo.get_all_sessions()
        active = [s for s in sessions if s.status not in ("cancelled", "completed")]

        debug = []
        for session in active:
            count, enrolled = self._count_registrations(session, all_leads)
            # Also show leads that almost-matched (for diagnostics)
            near_misses = []
            for lead in all_leads:
                if not self._is_registered(lead):
                    continue
                training_raw = str(getattr(lead, "training", "") or "").strip()
                if not training_raw:
                    continue
                lead_words = _significant_words(training_raw)
                sess_words = _significant_words(session.title)
                shared = lead_words & sess_words
                if 1 <= len(shared) < 3:
                    near_misses.append({
                        "name": getattr(lead, "fullname", "?"),
                        "training": training_raw,
                        "shared_words": list(shared),
                        "reason": "Too few shared words (need ≥3)",
                    })

            debug.append({
                "session_id": session.session_id,
                "title": session.title,
                "date": session.date,
                "capacity": session.capacity,
                "registered_count": count,
                "enrolled_leads": enrolled,
                "near_misses": near_misses[:5],
            })
        return debug

    def get_session_roster(self, session_id: str, all_leads: list) -> RosterEntry | None:
        for entry in self.get_roster(all_leads):
            if entry.session_id == session_id:
                return entry
        return None
