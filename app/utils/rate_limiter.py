"""In-memory hourly quota guard for LLM calls.

This is the "budget control" guardrail: if a bug causes a workflow to loop
and call the LLM far more than any real lead volume would justify, this
stops the bleeding automatically instead of relying on someone noticing an
API bill at the end of the month. Sliding window, reset by wall-clock hour
buckets — good enough for a single-process MVP; swap for Redis if this
service is ever horizontally scaled.
"""
from __future__ import annotations

import time
from collections import deque

from app.exceptions.custom_exceptions import BudgetExceededError


class HourlyQuota:
    def __init__(self, max_calls_per_hour: int):
        self._max_calls = max_calls_per_hour
        self._timestamps: deque[float] = deque()

    def _prune(self, now: float) -> None:
        one_hour_ago = now - 3600
        while self._timestamps and self._timestamps[0] < one_hour_ago:
            self._timestamps.popleft()

    def check_and_record(self) -> None:
        now = time.time()
        self._prune(now)
        if len(self._timestamps) >= self._max_calls:
            raise BudgetExceededError(
                f"LLM hourly quota exceeded ({self._max_calls} calls/hour). "
                "Pausing automatic calls — a human must review before this resumes."
            )
        self._timestamps.append(now)

    @property
    def calls_in_current_window(self) -> int:
        self._prune(time.time())
        return len(self._timestamps)
