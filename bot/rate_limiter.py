"""
bot/rate_limiter.py
Per-user token-bucket rate limiter using asyncio primitives.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque

from bot.config import RATE_LIMIT_CALLS, RATE_LIMIT_PERIOD


class RateLimitExceeded(Exception):
    """Raised when a user exceeds the configured rate limit."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Try again in {retry_after:.0f}s.")


class RateLimiter:
    """
    Sliding-window rate limiter.

    Keeps a deque of timestamps for each user. On each call, evicts
    entries older than `period` seconds and checks whether the user
    has exceeded `max_calls`.
    """

    def __init__(
        self,
        max_calls: int = RATE_LIMIT_CALLS,
        period: int = RATE_LIMIT_PERIOD,
    ) -> None:
        self._max_calls = max_calls
        self._period = period
        self._locks: dict[int, asyncio.Lock] = {}
        self._history: dict[int, deque[float]] = {}

    def _get_lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    async def check(self, user_id: int) -> None:
        """
        Record a request attempt for *user_id*.
        Raises :class:`RateLimitExceeded` if the quota is exhausted.
        """
        async with self._get_lock(user_id):
            now = time.monotonic()
            history = self._history.setdefault(user_id, deque())

            # Evict timestamps outside the current window
            cutoff = now - self._period
            while history and history[0] < cutoff:
                history.popleft()

            if len(history) >= self._max_calls:
                # Time until the oldest entry falls outside the window
                retry_after = self._period - (now - history[0])
                raise RateLimitExceeded(retry_after=max(retry_after, 1.0))

            history.append(now)


# Module-level singleton used by handlers
limiter = RateLimiter()
