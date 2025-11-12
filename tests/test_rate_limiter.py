import asyncio

import pytest

from app.rate_limiter import RateLimiter, RateLimitExceeded


def test_rate_limiter_enforces_limit():
    async def _run():
        limiter = RateLimiter(limit=2, window_seconds=10)
        await limiter.check("user:1")
        await limiter.check("user:1")
        with pytest.raises(RateLimitExceeded):
            await limiter.check("user:1")

    asyncio.run(_run())
