"""Simple in-memory rate limiting helpers."""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional


@dataclass
class _Bucket:
    hits: Deque[float]


class RateLimiter:
    """An asyncio-friendly sliding window rate limiter."""

    def __init__(self, *, limit: int, window_seconds: float) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.limit = limit
        self.window = window_seconds
        self._lock = asyncio.Lock()
        self._buckets: Dict[str, _Bucket] = {}

    async def try_acquire(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window

        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(deque())
                self._buckets[key] = bucket

            hits = bucket.hits
            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= self.limit:
                return False

            hits.append(now)
            return True


_submission_limiter: Optional[RateLimiter] = None


def get_submission_rate_limiter() -> Optional[RateLimiter]:
    """Return the shared rate limiter for flag submissions (if configured)."""

    global _submission_limiter
    if _submission_limiter is not None:
        return _submission_limiter

    try:
        limit = int(os.getenv("FLAG_SUBMISSION_RATE_LIMIT", "0"))
        window = float(os.getenv("FLAG_SUBMISSION_RATE_WINDOW", "60"))
    except ValueError:
        limit = 0
        window = 60.0

    if limit <= 0:
        _submission_limiter = None
        return None

    _submission_limiter = RateLimiter(limit=limit, window_seconds=window)
    return _submission_limiter


__all__ = ["RateLimiter", "get_submission_rate_limiter"]
