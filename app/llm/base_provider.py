"""LLM provider interface. Every provider (Ollama, OpenRouter, and whatever
comes next) implements this single method. Services depend on this
interface only — never on OllamaProvider or OpenRouterProvider directly."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    model: str
    latency_ms: float
    raw: dict | None = None


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 512, **kwargs) -> LLMResponse:
        """Run one completion. Must raise LLMTimeoutError on timeout —
        never let a raw requests/httpx exception escape this boundary."""
        pass
