"""Retrieval interfaces and a lightweight local knowledge-base provider."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
import re


class RAGProvider(ABC):
    @abstractmethod
    def search(self, query: str, *, top_k: int = 3) -> list[str]:
        """Return the top_k most relevant document chunks for `query`.
        Not implemented in this sprint — see ChromaDBProvider (future)."""


class NullRAGProvider(RAGProvider):
    """No-op implementation used until ChromaDB is wired in. Always returns
    an empty context so QualificationService can call it unconditionally
    without an if/else scattered through the service layer."""

    def search(self, query: str, *, top_k: int = 3) -> list[str]:
        return []


class FileRAGProvider(RAGProvider):
    """Small, deterministic retrieval layer for approved internal documents.

    It deliberately uses no external vector database: the current knowledge
    base is small, and transparent lexical ranking is easier to validate. A
    future vector provider can keep the same ``RAGProvider`` contract.
    """

    def __init__(self, directory: str):
        self._directory = Path(directory)

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-zA-Z0-9]{3,}", value.lower())
            if token not in {"avec", "pour", "dans", "the", "and", "les", "des", "une"}
        }

    def _chunks(self) -> list[tuple[str, str]]:
        if not self._directory.exists():
            return []
        chunks: list[tuple[str, str]] = []
        for path in sorted(self._directory.rglob("*.md")):
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            paragraphs = re.split(r"\n\s*\n", content)
            index = 0
            while index < len(paragraphs):
                chunk = paragraphs[index]
                # A heading alone is not usable context. Join it with its
                # following paragraph so the returned citation contains the
                # actual policy, script, or programme information.
                if chunk.lstrip().startswith("#") and index + 1 < len(paragraphs):
                    chunk = f"{chunk}\n{paragraphs[index + 1]}"
                    index += 1
                clean_chunk = " ".join(chunk.split())
                if clean_chunk:
                    chunks.append((f"{path.name}#{index + 1}", clean_chunk))
                index += 1
        return chunks

    def search(self, query: str, *, top_k: int = 3) -> list[str]:
        query_tokens = self._tokens(query)
        if not query_tokens:
            return []
        scored = []
        for source, chunk in self._chunks():
            score = len(query_tokens & self._tokens(chunk))
            if score:
                scored.append((score, source, chunk))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [f"Source: {source}\n{chunk}" for _, source, chunk in scored[:top_k]]
