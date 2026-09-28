"""Secure inbound contract used by the existing Task Manager Hub.

The Hub owns its task records. Once an SDR completes a Hub task, it calls this
service so the Lead Agent can update lead history and create the next action.
"""
from __future__ import annotations

import hmac

from app.core.config import Settings
from app.services.lead_service import LeadService
from app.services.sdr_copilot_service import SDRCopilotService


class HubIntegrationService:
    def __init__(
        self,
        settings: Settings,
        lead_service: LeadService,
        sdr_copilot_service: SDRCopilotService,
    ):
        self._settings = settings
        self._lead_service = lead_service
        self._sdr_copilot_service = sdr_copilot_service

    def verify_secret(self, presented_secret: str | None) -> None:
        expected_secret = self._settings.hub_integration_secret
        if not expected_secret:
            raise RuntimeError("HUB_INTEGRATION_SECRET is not configured")
        if not presented_secret or not hmac.compare_digest(presented_secret, expected_secret):
            raise PermissionError("Invalid Hub integration secret")

    def mark_task_completed(
        self,
        lead_id: str,
        actor_id: str,
        outcome: str | None,
        notes: str | None,
    ) -> dict:
        """Apply a human-completed Hub task to the lead lifecycle."""
        if outcome:
            from app.api.schemas.sdr_schema import CallOutcomeRequest

            result = self._sdr_copilot_service.process_call_outcome(
                CallOutcomeRequest(lead_id=lead_id, outcome=outcome, call_notes=notes)
            )
            return {
                "lead_id": lead_id,
                "actor_id": actor_id,
                "status": result.new_status,
                "next_followup_date": result.next_followup_date,
                "next_action": result.suggested_next_action,
            }

        lead = self._lead_service.mark_lead_called(lead_id, actor_id)
        return {
            "lead_id": lead.id,
            "actor_id": actor_id,
            "status": lead.status,
            "next_followup_date": lead.next_followup_date,
            "next_action": lead.next_action,
        }
