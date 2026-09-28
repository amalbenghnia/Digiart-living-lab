"""Ollama provider — runs Qwen3 8B or Mistral Small locally, no API cost.
This is the default provider for the Lead Agent: high call frequency,
low-complexity tasks (see the model-selection table in the architecture doc)."""
from __future__ import annotations

import time

import httpx

from app.core.logging import Timer, get_logger, log_event
from app.exceptions.custom_exceptions import LLMTimeoutError
from app.llm.base_provider import LLMProvider, LLMResponse

logger = get_logger(__name__)


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model_name: str, timeout_seconds: int):
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout = timeout_seconds

    def generate(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 512, **kwargs) -> LLMResponse:
        options = {"num_predict": max_tokens}
        if "temperature" in kwargs:
            options["temperature"] = kwargs["temperature"]

        payload = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": options,
        }
        with Timer() as t:
            try:
                resp = httpx.post(
                    f"{self._base_url}/api/chat", json=payload, timeout=self._timeout
                )
                resp.raise_for_status()
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError(
                    f"Ollama did not respond within {self._timeout}s (model={self._model_name})"
                ) from exc
            except httpx.HTTPError as exc:
                # Covers ConnectError (Ollama not running yet — the most common
                # failure during sprint 1 prototyping), DNS errors, etc. All
                # network failures degrade the same way: raise a typed error
                # the caller already knows how to map to HTTP 504, instead of
                # letting a raw httpx traceback reach the API boundary.
                raise LLMTimeoutError(
                    f"Ollama unreachable at {self._base_url} (model={self._model_name}): {exc}"
                ) from exc

        data = resp.json()
        text = data.get("message", {}).get("content", "")

        log_event(
            logger, "llm_call", "Ollama generation complete",
            provider="ollama", model=self._model_name, latency_ms=t.elapsed_ms,
        )
        return LLMResponse(text=text, model=self._model_name, latency_ms=t.elapsed_ms, raw=data)
