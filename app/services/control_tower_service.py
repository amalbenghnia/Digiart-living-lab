"""Read-only operational control tower for the AI integration layer.

This service intentionally does not make decisions or call an LLM. It makes
the agents observable: team members can see what is automated, what still
needs human action, and which external connection is not ready yet.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.business_rules.lead_rules import LeadBusinessRules
from app.core.config import DataSourceMode, Settings
from app.models.evidence import EVIDENCE_STORE
from app.models.lead import LeadStatus
from app.repositories.base_repository import LeadRepository
from app.utils.rate_limiter import HourlyQuota


class ControlTowerService:
    def __init__(
        self,
        settings: Settings,
        repository: LeadRepository,
        rules: LeadBusinessRules,
        quota: HourlyQuota,
    ):
        self._settings = settings
        self._repository = repository
        self._rules = rules
        self._quota = quota

    def snapshot(self, now: datetime | None = None) -> dict:
        """Return a transparent, read-only health and SLA snapshot."""
        now = now or datetime.now(timezone.utc)
        leads = self._repository.get_all_leads()
        active = [
            lead
            for lead in leads
            if lead.status not in {LeadStatus.PAID.value, LeadStatus.ARCHIVED.value}
        ]
        unscored = [lead for lead in active if lead.score is None]
        p0_breaches = [
            lead
            for lead in active
            if lead.priority == "P0"
            and not lead.called
            and self._rules.is_lead_older_than_hot_threshold(lead, now)
        ]
        payment_overdue = [lead for lead in active if self._rules.is_payment_overdue(lead)]
        followups_due = [
            lead
            for lead in active
            if lead.next_followup_date and lead.next_followup_date <= now.date().isoformat()
        ]

        scored_coverage = round(100 * (len(active) - len(unscored)) / len(active), 1) if active else 100.0
        called_coverage = round(100 * sum(lead.called for lead in active) / len(active), 1) if active else 100.0
        market_evidence_count = sum(evidence.total_count() for evidence in EVIDENCE_STORE.values())

        data_source_configured = bool(
            self._settings.data_source_mode == DataSourceMode.GOOGLE_SHEET
            and self._settings.google_sheet_id
            and self._settings.google_service_account_json_path
        )
        automation_configured = bool(
            self._settings.automation_enabled and self._settings.n8n_webhook_base_url
        )
        hub_contract_declared = bool(self._settings.task_manager_api_base_url)

        agents = [
            {
                "id": "lead-agent",
                "name": "Lead Agent",
                "status": "attention" if p0_breaches else "ready",
                "metric_label": "Scored lead coverage",
                "metric_value": f"{scored_coverage}%",
                "detail": f"{len(unscored)} active lead(s) still need qualification.",
            },
            {
                "id": "sdr-copilot",
                "name": "SDR Copilot",
                "status": "attention" if p0_breaches else "ready",
                "metric_label": "Human contact coverage",
                "metric_value": f"{called_coverage}%",
                "detail": f"{len(p0_breaches)} P0 lead(s) exceed the call SLA.",
            },
            {
                "id": "market-intelligence",
                "name": "Market Intelligence",
                "status": "ready" if market_evidence_count else "waiting",
                "metric_label": "Evidence collected",
                "metric_value": str(market_evidence_count),
                "detail": "Recommendations stay evidence-based; no market score is fabricated.",
            },
            {
                "id": "reporting-agent",
                "name": "Reporting Agent",
                "status": "ready",
                "metric_label": "Operational alerts",
                "metric_value": str(len(payment_overdue) + len(followups_due)),
                "detail": "Reports are calculated from the current lead source.",
            },
        ]

        integration_status = [
            {
                "name": "Lead data source",
                "status": "configured" if data_source_configured else "prototype",
                "detail": "Google Sheets configuration is present; the runtime verifies connectivity on access." if data_source_configured else "Prototype data is active; production lead data is not yet the source of truth.",
            },
            {
                "name": "n8n automation",
                "status": "configured" if automation_configured else "not_configured",
                "detail": "Webhook configuration is present; delivery failures remain visible in the application logs." if automation_configured else "Events are logged locally until N8N_WEBHOOK_BASE_URL is configured.",
            },
            {
                "name": "Task Manager Hub",
                "status": "contract_declared" if hub_contract_declared else "needs_contract",
                "detail": "Hub endpoint is declared; complete the n8n upsert adapter and delivery acknowledgement before calling it live." if hub_contract_declared else "Needs the Hub task API contract and authentication before direct task sync can be enabled.",
            },
        ]

        return {
            "generated_at": now.isoformat(),
            "summary": {
                "active_leads": len(active),
                "p0_sla_breaches": len(p0_breaches),
                "payment_overdue": len(payment_overdue),
                "followups_due": len(followups_due),
                "llm_calls_this_hour": self._quota.calls_in_current_window,
                "llm_hourly_quota": self._settings.llm_max_calls_per_hour,
            },
            "agents": agents,
            "integrations": integration_status,
            "attention_queue": [
                {
                    "type": "p0_call_sla",
                    "lead_id": lead.id,
                    "lead_name": lead.fullname,
                    "action": "Call immediately and capture the outcome in SDR Copilot.",
                }
                for lead in p0_breaches
            ]
            + [
                {
                    "type": "payment_followup",
                    "lead_id": lead.id,
                    "lead_name": lead.fullname,
                    "action": "Review payment reminder before sending.",
                }
                for lead in payment_overdue
            ],
            "decision_policy": [
                {
                    "area": "Lead qualification",
                    "automation": "Validate, deduplicate, score and prioritize.",
                    "human_control": "Review exceptional data and make the commercial call.",
                },
                {
                    "area": "SDR follow-up",
                    "automation": "Prepare briefs, objection guidance and email drafts.",
                    "human_control": "Approve outreach and record the call outcome.",
                },
                {
                    "area": "Course planning",
                    "automation": "Rank courses from lead demand and cited market evidence.",
                    "human_control": "Approve the course launch and cohort capacity.",
                },
            ],
        }
