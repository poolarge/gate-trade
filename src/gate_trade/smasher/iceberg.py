"""IcebergDetector — detects hidden iceberg orders in the order book.

Phase 7.2: Tracks per-price-level quantity replenishments. When a level
is repeatedly replenished after being consumed, it signals a hidden
iceberg order.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class IcebergSignal:
    price: float
    side: str  # 'bid' or 'ask'
    replenishments: int
    avg_replenish_size: float


class IcebergDetector:
    """Detect iceberg orders via order book level replenishment tracking.

    An iceberg is suspected when quantity at a price level is consumed
    (drops) and then refilled multiple times within a short window.
    """

    def __init__(
        self,
        window_sec: float = 30.0,
        replenish_threshold: int = 3,
        min_replenish_size: float = 0.0,
    ) -> None:
        self._window = window_sec
        self._replenish_threshold = replenish_threshold
        self._min_replenish_size = min_replenish_size

        # per-price-level tracking: price -> deque of (timestamp, size)
        self._bid_levels: dict[float, deque[tuple[float, float]]] = {}
        self._ask_levels: dict[float, deque[tuple[float, float]]] = {}

    def update(
        self,
        bids: list[tuple[float, float]],
        asks: list[tuple[float, float]],
        timestamp: float | None = None,
    ) -> list[IcebergSignal]:
        """Ingest a new order book snapshot and return detected iceberg signals."""
        ts = timestamp if timestamp is not None else time.monotonic()
        signals: list[IcebergSignal] = []

        signals.extend(self._process_side(bids, self._bid_levels, ts, "bid"))
        signals.extend(self._process_side(asks, self._ask_levels, ts, "ask"))

        for sig in signals:
            logger.info("iceberg_detected",
                        price=sig.price, side=sig.side,
                        replenishments=sig.replenishments)

        return signals

    def _process_side(
        self,
        levels: list[tuple[float, float]],
        tracker: dict[float, deque[tuple[float, float]]],
        ts: float,
        side: str,
    ) -> list[IcebergSignal]:
        signals: list[IcebergSignal] = []
        seen: set[float] = set()
        cutoff = ts - self._window

        for price, size in levels:
            seen.add(price)
            if size <= self._min_replenish_size:
                continue

            if price not in tracker:
                tracker[price] = deque()

            history = tracker[price]

            # Expire old entries
            while history and history[0][0] < cutoff:
                history.popleft()

            # Detect replenishment: size went up from previous snapshot
            replenished = history and history[-1][1] < size
            history.append((ts, size))

            if replenished:
                # Count how many replenishments in current window
                replen_count = sum(
                    1 for i in range(1, len(history))
                    if history[i][1] > history[i - 1][1]
                )
                if replen_count >= self._replenish_threshold:
                    sizes = [s for _, s in history]
                    avg = sum(sizes) / len(sizes)
                    signals.append(IcebergSignal(
                        price=price, side=side,
                        replenishments=replen_count,
                        avg_replenish_size=avg,
                    ))

        # Remove stale levels
        for price in list(tracker):
            if price not in seen:
                del tracker[price]

        return signals

    def reset(self) -> None:
        self._bid_levels.clear()
        self._ask_levels.clear()
