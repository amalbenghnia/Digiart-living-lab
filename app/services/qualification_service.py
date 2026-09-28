"""QualificationService implements, step by step, the AI decision workflow
from the spec:

    Receive request -> Business Rules -> Need language understanding? ->
    NO -> continue (skip LLM entirely)
    YES -> call LLM -> validate output -> continue

Nothing here calls the LLM unconditionally. If `raw_message` is empty, this
service never touches the network — that is the whole point of the gate.
"""
from __future__ import annotations

import json

from pydantic import ValidationError as PydanticValidationError

from app.api.schemas.qualification_schema import QualificationOutput
from app.business_rules.lead_rules import LeadBusinessRules
from app.core.logging import get_logger, log_event
from app.exceptions.custom_exceptions import LLMValidationError
from app.interfaces.rag import RAGProvider
from app.llm.base_provider import LLMProvider
from app.models.lead import Lead
from app.prompts.qualification_prompt import PROMPT_VERSION, build_qualification_prompt
from app.prompts.system_prompt import SYSTEM_PROMPT
from app.utils.rate_limiter import HourlyQuota

logger = get_logger(__name__)


class QualificationService:
    def __init__(
        self,
        rules: LeadBusinessRules,
        llm_provider: LLMProvider,
        rag_provider: RAGProvider,
        quota: HourlyQuota,
        catalog_repo=None,
    ):
        self._rules = rules
        self._llm = llm_provider
        self._rag = rag_provider
        self._quota = quota
        self._catalog_repo = catalog_repo

    def qualify(self, lead: Lead) -> QualificationOutput | None:
        """Returns None when no LLM call was needed (structured lead only) —
        callers must treat None as 'nothing to add', not as a failure."""

        # Step 1: business rules gate — the only thing that decides if we
        # even consider calling the LLM.
        needs_llm = self._rules.requires_language_understanding(lead)
        log_event(
            logger, "business_rule", "LLM necessity check",
            lead_id=lead.id, needs_llm=needs_llm,
        )
        if not needs_llm:
            return None

        # Step 2: budget guardrail, before spending a single token.
        self._quota.check_and_record()

        # Step 3: RAG (currently a no-op NullRAGProvider — see interfaces/rag.py)
        context_chunks = self._rag.search(lead.raw_message or "", top_k=3)
        context_block = "\n".join(context_chunks)

        # Step 4: LLM call
        user_prompt = build_qualification_prompt(
            raw_message=lead.raw_message or "", training=lead.training
        )
        if context_block:
            user_prompt = f"Relevant context:\n{context_block}\n\n{user_prompt}"

        if self._catalog_repo:
            catalog_info = self._catalog_repo.get_catalog_content_text()
            user_prompt = f"Catalogue des formations disponibles :\n{catalog_info}\n\n{user_prompt}"

        response = self._llm.generate(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
        log_event(
            logger, "llm_call", "Qualification LLM call complete",
            lead_id=lead.id, prompt_version=PROMPT_VERSION,
            model=response.model, latency_ms=response.latency_ms,
        )

        # Step 5: validate the LLM output against the strict schema —
        # this IS the "Business Rules (validation) after LLM" step.
        try:
            raw_text = response.text.strip()
            
            import re
            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if match:
                raw_text = match.group(0)
            
            parsed = json.loads(raw_text)
            output = QualificationOutput.model_validate(parsed)
        except (json.JSONDecodeError, PydanticValidationError) as exc:
            log_event(
                logger, "error", "LLM output failed validation",
                lead_id=lead.id, raw_output=response.text[:500],
            )
            raise LLMValidationError(
                f"LLM output for lead {lead.id} did not match the expected schema: {exc}"
            ) from exc

        return output
