"""CommunicationService — generates personalised outreach emails via the LLM.

Design contract:
- This service ONLY generates email content. It never sends emails itself.
  Sending is always handled by n8n so that the CM keeps full control and
  traceability of every email that goes out.
- LLM calls here are always intentional (not gated by requires_language_understanding),
  because the whole purpose of this service is to produce human-quality prose.
- The LLM must return valid JSON matching the EmailGenerationResponse schema.
  If it doesn't, we raise LLMValidationError so n8n can surface the failure
  cleanly without silently sending a malformed email.
"""
from __future__ import annotations

import json

from pydantic import ValidationError as PydanticValidationError

from app.api.schemas.email_schema import EmailContext, EmailGenerationResponse
from app.business_rules.lead_rules import LeadBusinessRules
from app.core.logging import get_logger, log_event
from app.exceptions.custom_exceptions import LLMValidationError
from app.llm.base_provider import LLMProvider
from app.models.lead import Lead
from app.prompts.email_generation_prompt import (
    EMAIL_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_contact_p1_prompt,
    build_nurturing_p2_prompt,
    build_payment_reminder_prompt,
)
from app.utils.rate_limiter import HourlyQuota

logger = get_logger(__name__)


class CommunicationService:
    """Generates personalised email content for leads using the LLM."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        rules: LeadBusinessRules,
        quota: HourlyQuota,
    ):
        self._llm = llm_provider
        self._rules = rules
        self._quota = quota

    def generate_email(
        self, lead: Lead, context: EmailContext
    ) -> EmailGenerationResponse:
        """Call the LLM to draft a personalised email for the given lead and context.

        Returns an EmailGenerationResponse with subject, body_html and body_text.
        Raises LLMValidationError if the LLM output is not valid JSON.
        Raises BudgetExceededError (from quota.check_and_record) if the hourly
        LLM budget is exhausted.
        """
        # Guard the LLM budget before spending a single token
        self._quota.check_and_record()

        # Build the user prompt based on context
        days_overdue = self._rules.days_overdue(lead)
        if context == EmailContext.CONTACT_P1:
            user_prompt = build_contact_p1_prompt(lead)
        elif context == EmailContext.NURTURING_P2:
            user_prompt = build_nurturing_p2_prompt(lead)
        elif context == EmailContext.PAYMENT_REMINDER:
            user_prompt = build_payment_reminder_prompt(lead, days_overdue)
        else:
            user_prompt = build_contact_p1_prompt(lead)

        log_event(
            logger, "llm_call", "Email generation started",
            lead_id=lead.id, context=context, prompt_version=PROMPT_VERSION,
        )

        response = self._llm.generate(
            system_prompt=EMAIL_SYSTEM_PROMPT, 
            user_prompt=user_prompt,
            max_tokens=1024
        )

        log_event(
            logger, "llm_call", "Email generation complete",
            lead_id=lead.id, context=context,
            model=response.model, latency_ms=response.latency_ms,
        )

        # Parse and validate the LLM JSON output
        try:
            raw = response.text.strip()
            
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                raw = match.group(0)
                
            parsed = json.loads(raw)

            # Validate presence of required keys
            if not all(k in parsed for k in ("subject", "body_html", "body_text")):
                raise ValueError(f"Missing required keys in LLM output: {list(parsed.keys())}")

            return EmailGenerationResponse(
                lead_id=lead.id,
                context=context.value,
                subject=parsed["subject"],
                body_html=parsed["body_html"],
                body_text=parsed["body_text"],
            )
        except (json.JSONDecodeError, ValueError, PydanticValidationError) as exc:
            log_event(
                logger, "error", "Email LLM output failed validation",
                lead_id=lead.id, raw_output=response.text[:500],
            )
            raise LLMValidationError(
                f"LLM email output for lead {lead.id} did not match expected schema: {exc}"
            ) from exc
