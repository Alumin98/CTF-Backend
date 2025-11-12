"""Simple in-memory rate limiter utilities."""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from typing import Deque, Dict


class RateLimitExceeded(Exception):
    """Raised when a caller exceeds the configured rate limit."""


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = max(1, int(limit))
        self.window = max(0.1, float(window_seconds))
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> None:
        """Record an attempt for ``key`` and raise if it exceeds the limit."""

        now = time.monotonic()
        cutoff = now - self.window
        async with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                raise RateLimitExceeded(f"Rate limit exceeded ({self.limit}/{self.window}s)")
            bucket.append(now)


_submission_limiter: RateLimiter | None = None


def get_submission_rate_limiter() -> RateLimiter:
    global _submission_limiter
    if _submission_limiter is None:
        limit = int(os.getenv("FLAG_SUBMISSION_RATE_LIMIT", "10"))
        window = float(os.getenv("FLAG_SUBMISSION_RATE_WINDOW", "60"))
        _submission_limiter = RateLimiter(limit=limit, window_seconds=window)
    return _submission_limiter
