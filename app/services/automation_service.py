"""AutomationService: the ONLY place in the codebase that knows n8n exists.

 n8n itself is not implemented in this sprint — but the four
trigger functions are fully functional: if N8N_WEBHOOK_BASE_URL is set in
.env, they POST a JSON payload to the matching webhook. If it is not set
(the default in prototype mode), they log the event instead of failing —
so the rest of the application behaves identically whether or not n8n is
actually running yet. This is what "assurer la cohérence de l'agent" means
in practice: the business logic never needs to know whether n8n exists.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger, log_event

logger = get_logger(__name__)


class AutomationService:
    def __init__(self, settings: Settings):
        self._settings = settings

    def _post(self, event: str, payload: dict[str, Any], idempotency_key: str | None = None) -> None:
        if not self._settings.automation_enabled:
            return

        if not self._settings.n8n_webhook_base_url:
            # Prototype mode: no n8n instance configured yet — log only.
            # Payload is passed as a single nested field (not **unpacked) because
            # a payload key can legitimately be named "message" (e.g. the
            # notification text itself), which would otherwise collide with
            # log_event's own `message` positional argument.
            log_event(logger, "business_rule", f"[automation stub] {event}", payload=payload)
            return

        url = f"{self._settings.n8n_webhook_base_url.rstrip('/')}/{event}"
        headers = {}
        if self._settings.n8n_webhook_secret:
            headers["X-Webhook-Secret"] = self._settings.n8n_webhook_secret
        if idempotency_key:
            # n8n and the Task Manager adapter can use this to upsert an event
            # after a retry instead of creating a second task.
            headers["X-Idempotency-Key"] = idempotency_key

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=5.0)
            response.raise_for_status()
            log_event(logger, "business_rule", f"n8n webhook fired: {event}", payload=payload)
        except httpx.HTTPError as exc:
            # Automation failures must never crash the main request — the
            # lead is already saved; a missed notification is recoverable,
            # a lost lead is not.
            log_event(logger, "error", f"n8n webhook failed: {event}", error=str(exc), payload=payload)

    def trigger_create_task(self, lead_id: str, task_id: str, assigned_to: str, priority: str) -> None:
        self._post(
            "create-task",
            {
                "lead_id": lead_id,
                "task_id": task_id,
                "assigned_to": assigned_to,
                "priority": priority,
                "idempotency_key": task_id,
            },
            idempotency_key=task_id,
        )

    def trigger_notification(self, channel: str, message: str, lead_id: str) -> None:
        self._post("notification", {"channel": channel, "message": message, "lead_id": lead_id})

    def trigger_dashboard(self, lead_id: str) -> None:
        self._post("dashboard-refresh", {"lead_id": lead_id})

    def trigger_reporting(self, lead_id: str, event_type: str) -> None:
        self._post("reporting-event", {"lead_id": lead_id, "event_type": event_type})
