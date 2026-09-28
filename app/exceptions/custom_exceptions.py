"""Custom exceptions. Every failure mode that the spec asked for has its own
exception class so the API layer can map each one to the right HTTP status
and the logs can be filtered by exception type."""
from __future__ import annotations


class LeadAgentError(Exception):
    """Base class for all application-specific errors."""


class DataSourceUnavailableError(LeadAgentError):
    """Raised when the underlying data source (Google Sheet, later Postgres) is unreachable."""


class DuplicateLeadError(LeadAgentError):
    """Raised when a lead with the same phone or email already exists."""

    def __init__(self, field: str, value: str, existing_lead_id: str):
        self.field = field
        self.value = value
        self.existing_lead_id = existing_lead_id
        super().__init__(
            f"Duplicate lead detected on {field}={value!r} (existing lead id={existing_lead_id})"
        )


class ValidationError(LeadAgentError):
    """Raised when a lead fails a mandatory business rule (missing fields, bad format)."""


class LeadNotFoundError(LeadAgentError):
    def __init__(self, lead_id: str):
        self.lead_id = lead_id
        super().__init__(f"Lead not found: {lead_id}")


class LLMTimeoutError(LeadAgentError):
    """Raised when the configured LLM provider does not respond in time."""


class LLMValidationError(LeadAgentError):
    """Raised when the LLM output fails post-generation business-rule validation."""


class BudgetExceededError(LeadAgentError):
    """Raised when an agent hits its configured hourly LLM call quota."""


class UnexpectedError(LeadAgentError):
    """Catch-all for anything not explicitly modeled — logged with full traceback."""
