"""TrickleExecutor — splits large orders into randomized chunks.

Phase 7.3: When the bot needs to execute a large order (e.g., rebalancing),
trickle it out in randomized sizes and delays to avoid detection by
counterparty surveillance.
"""

from __future__ import annotations

import random


class TrickleExecutor:
    """Execute a large order as a sequence of randomized child orders.

    Usage::

        te = TrickleExecutor(total=1.0, min_chunk=0.01, max_chunk=0.05)
        while chunk := te.next_chunk():
            size, delay = chunk
            place_order(size)
            await asyncio.sleep(delay)
    """

    def __init__(
        self,
        total: float,
        min_chunk: float,
        max_chunk: float,
        min_delay_sec: float = 1.0,
        max_delay_sec: float = 5.0,
        jitter_pct: float = 0.05,
    ) -> None:
        if total <= 0:
            raise ValueError(f"total must be positive, got {total}")
        if min_chunk <= 0 or max_chunk < min_chunk:
            raise ValueError(f"invalid chunk range: [{min_chunk}, {max_chunk}]")
        if min_delay_sec < 0 or max_delay_sec < min_delay_sec:
            raise ValueError(f"invalid delay range: [{min_delay_sec}, {max_delay_sec}]")

        self._remaining = total
        self._min_chunk = min_chunk
        self._max_chunk = max_chunk
        self._min_delay = min_delay_sec
        self._max_delay = max_delay_sec
        self._jitter = jitter_pct
        self._total = total

    @property
    def remaining(self) -> float:
        return self._remaining

    @property
    def progress(self) -> float:
        if self._total <= 0:
            return 1.0
        return 1.0 - (self._remaining / self._total)

    def next_chunk(self) -> tuple[float, float] | None:
        """Return (size, delay_seconds) for the next child order.

        Returns None when the full quantity has been allocated.
        """
        if self._remaining <= 0:
            return None

        # Pick a random chunk size, clamped to remaining
        raw = random.uniform(self._min_chunk, self._max_chunk)

        # Apply jitter to avoid round-number detection
        jitter = raw * self._jitter * (random.random() * 2.0 - 1.0)
        size = raw + jitter

        # Clamp to remaining; floor is half min_chunk but never exceed remaining
        floor = min(self._min_chunk * 0.5, self._remaining)
        size = max(floor, min(size, self._remaining))
        size = round(size, 8)

        self._remaining = round(self._remaining - size, 8)
        if self._remaining < 0:
            self._remaining = 0.0

        # Random delay, slightly longer for larger chunks
        delay_scale = size / self._max_chunk
        min_d = self._min_delay
        max_d = self._min_delay + (self._max_delay - self._min_delay) * delay_scale
        delay = random.uniform(min_d, max_d)
        delay = round(delay, 3)

        return size, delay

    def reset(self) -> None:
        self._remaining = self._total
