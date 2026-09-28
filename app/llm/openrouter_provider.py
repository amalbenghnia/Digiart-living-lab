"""OpenRouter provider — used only if/when a task needs a stronger model than
what Ollama can run locally. Not used by the Lead Agent by default (see
model-selection table: Lead Agent = Qwen3 8B / Ollama), but implemented so
swapping providers is a one-line config change, never a code change."""
from __future__ import annotations

import httpx

from app.core.logging import Timer, get_logger, log_event
from app.exceptions.custom_exceptions import LLMTimeoutError
from app.llm.base_provider import LLMProvider, LLMResponse

logger = get_logger(__name__)


class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model_name: str, timeout_seconds: int):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout = timeout_seconds

    def generate(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 512) -> LLMResponse:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        payload = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
        }
        with Timer() as t:
            try:
                resp = httpx.post(
                    f"{self._base_url}/chat/completions",
                    json=payload, headers=headers, timeout=self._timeout,
                )
                resp.raise_for_status()
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError(
                    f"OpenRouter did not respond within {self._timeout}s (model={self._model_name})"
                ) from exc
            except httpx.HTTPError as exc:
                raise LLMTimeoutError(
                    f"OpenRouter unreachable (model={self._model_name}): {exc}"
                ) from exc

        data = resp.json()
        text = data["choices"][0]["message"]["content"]

        log_event(
            logger, "llm_call", "OpenRouter generation complete",
            provider="openrouter", model=self._model_name, latency_ms=t.elapsed_ms,
        )
        return LLMResponse(text=text, model=self._model_name, latency_ms=t.elapsed_ms, raw=data)
