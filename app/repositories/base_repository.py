"""Abstract repository contract.

This is the single interface that BOTH the prototype (in-memory) repository
and the real Google Sheets repository implement. Every service in this
project depends on THIS interface, never on a concrete class — that is what
lets us start development against fake data today and point the same code
at production Google Sheets tomorrow by changing one setting
(DATA_SOURCE_MODE=google_sheet in .env), with zero changes to business logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.lead import Lead
from app.models.task import Task


class LeadRepository(ABC):
    @abstractmethod
    def get_all_leads(self) -> list[Lead]:
        """Return every lead currently in the source."""

    @abstractmethod
    def get_new_leads(self) -> list[Lead]:
        """Return only leads with status == NEW (not yet processed)."""

    @abstractmethod
    def get_lead_by_id(self, lead_id: str) -> Lead | None:
        ...

    @abstractmethod
    def create_lead(self, lead: Lead) -> Lead:
        ...

    @abstractmethod
    def update_lead(self, lead: Lead) -> Lead:
        """Full update — caller is responsible for building the updated Lead object."""

    @abstractmethod
    def update_priority(self, lead_id: str, priority: str, score: float | None) -> Lead:
        ...

    @abstractmethod
    def create_task(self, task: Task) -> Task:
        ...

    @abstractmethod
    def get_tasks_for_lead(self, lead_id: str) -> list[Task]:
        ...
