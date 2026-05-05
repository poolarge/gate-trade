"""Token-bucket rate limiter for exchange API calls."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Asynchronous token-bucket rate limiter.

    *burst* tokens are available immediately; tokens refill at *rate* per second.
    If the bucket is empty and *max_wait_sec* > 0, the caller will wait up to
    that duration for a token. Raises ``RateLimitExceeded`` if the wait times out.
    """

    __slots__ = ("_capacity", "_rate", "_tokens", "_max_wait", "_last_refill")

    def __init__(
        self, burst: int = 10, rate: float = 8.0, max_wait_sec: float = 5.0
    ) -> None:
        if burst < 0 or rate <= 0 or max_wait_sec < 0:
            raise ValueError(f"Invalid rate-limit params: {burst=}, {rate=}, {max_wait_sec=}")
        self._capacity = float(burst)
        self._rate = rate
        self._tokens = float(burst)
        self._max_wait = max_wait_sec
        self._last_refill = time.monotonic()

    # ── public API ─────────────────────────────────────────────

    async def acquire(self) -> bool:
        """Try to consume one token.

        Returns True on success. Waits up to *max_wait_sec* before
        raising ``RateLimitExceeded``.
        """
        deadline = time.monotonic() + self._max_wait

        while True:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RateLimitExceeded(
                    f"No token available within {self._max_wait:.1f}s"
                )
            await asyncio.sleep(min(remaining, 0.05))

    def try_acquire(self) -> bool:
        """Non-blocking token consume. Returns False immediately if empty."""
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    @property
    def available(self) -> float:
        """Current token count (snapshot)."""
        self._refill()
        return self._tokens

    @property
    def capacity(self) -> float:
        """Maximum token count."""
        return self._capacity

    def reset(self) -> None:
        """Refill bucket to capacity."""
        self._tokens = self._capacity
        self._last_refill = time.monotonic()

    # ── internal ────────────────────────────────────────────────

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now


class RateLimitExceeded(Exception):
    """Raised when the token bucket stays empty past *max_wait*."""
