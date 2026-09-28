"""Structured logging setup.

Every log line is JSON so it can later be shipped to any log aggregator
without changing the code. Each of the categories the spec asked for
(api_call, business_rule, llm_call, google_sheet_update, error) is logged
through a dedicated helper so grepping/filtering logs is trivial.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from app.core.config import get_settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            payload["data"] = record.extra_data  # type: ignore[attr-defined]
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, category: str, message: str, **data: Any) -> None:
    """Category is one of: api_call, business_rule, llm_call, google_sheet_update, error.
    This is the single function every layer should call, so log shape stays consistent.
    """
    data["category"] = category
    data["latency_ms"] = data.get("latency_ms")
    logger.info(message, extra={"extra_data": data})


class Timer:
    """Small context manager to measure and log latency around any block."""

    def __init__(self) -> None:
        self.start = 0.0
        self.elapsed_ms = 0.0

    def __enter__(self) -> "Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed_ms = round((time.perf_counter() - self.start) * 1000, 2)
