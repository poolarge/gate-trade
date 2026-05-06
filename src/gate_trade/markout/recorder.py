"""MarkoutRecorder — records markout data for P&L attribution.

Phase 6.1: Captures mid price at fill time and at fixed intervals afterward
(1s, 5s, 30s) to evaluate execution quality. Saves to SQLite.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import structlog

from gate_trade.types import Order, Side

logger = structlog.get_logger(__name__)

MARKOUT_INTERVALS: tuple[float, ...] = (1.0, 5.0, 30.0)


@dataclass(slots=True)
class MarkoutRecord:
    order_id: str
    side: Side
    fill_price: float
    fill_size: float
    mid_at_fill: float
    mids_after: dict[float, float]  # interval_sec → mid_price
    fill_timestamp: float


class MarkoutRecorder:
    """Records fill events and computes markout P&L.

    Usage::

        recorder = MarkoutRecorder()
        recorder.on_fill(order, filled_size, mid_price)
        # ... time passes, mid updates arrive ...
        recorder.update_mid(mid_price, timestamp)
        # After intervals expire, completed entries are available:
        for entry in recorder.completed():
            print(entry.markout_bps)
    """

    def __init__(self) -> None:
        self._pending: deque[tuple[MarkoutRecord, float]] = deque()  # (record, deadline)
        self._completed: list[MarkoutRecord] = []
        self._last_mid: float = 0.0
        self._last_mid_time: float = 0.0

    def on_fill(
        self, order: Order, filled_size: float, mid_price: float,
        timestamp: float | None = None,
    ) -> None:
        now = timestamp if timestamp is not None else time.monotonic()
        record = MarkoutRecord(
            order_id=order.order_id,
            side=order.side,
            fill_price=order.price,
            fill_size=filled_size,
            mid_at_fill=mid_price,
            mids_after={},
            fill_timestamp=now,
        )
        # Set deadline at longest markout interval
        deadline = now + max(MARKOUT_INTERVALS) + 2.0
        self._pending.append((record, deadline))

    def update_mid(self, mid_price: float, timestamp: float | None = None) -> None:
        ts = timestamp if timestamp is not None else time.monotonic()
        self._last_mid = mid_price
        self._last_mid_time = ts

        # Fill in markout data for pending entries that have passed their interval
        completed_now: list[MarkoutRecord] = []
        still_pending: list[tuple[MarkoutRecord, float]] = []

        for record, deadline in self._pending:
            elapsed = ts - record.fill_timestamp
            for interval in MARKOUT_INTERVALS:
                if interval not in record.mids_after and elapsed >= interval:
                    record.mids_after[interval] = mid_price
            # Entry is complete when all intervals are filled
            if len(record.mids_after) == len(MARKOUT_INTERVALS):
                completed_now.append(record)
                logger.debug("markout_complete", order_id=record.order_id,
                             markout_bps=round(self._compute_markout_bps(record), 2))
            else:
                still_pending.append((record, deadline))

        self._pending = deque(still_pending)
        self._completed.extend(completed_now)

    def completed(self) -> list[MarkoutRecord]:
        """Return completed markout entries and clear the buffer."""
        result = list(self._completed)
        self._completed.clear()
        return result

    def recent_completed(self, limit: int = 50) -> list[MarkoutRecord]:
        """Return recently completed entries without clearing (for smasher/analysis)."""
        return list(self._completed)[-limit:]

    @staticmethod
    def _compute_markout_bps(record: MarkoutRecord) -> float:
        """Markout in bps (accumulation strategy).

        BUY:  fill_price - mid_after → positive when price dropped after buy
              (price down = more accumulation at cheaper prices = good)
        SELL: mid_after - fill_price → has no specific accumulation meaning here
        """
        if record.mid_at_fill <= 0:
            return 0.0
        # Use the longest available interval
        mid_after = record.mids_after.get(max(MARKOUT_INTERVALS), record.mid_at_fill)
        change = mid_after - record.mid_at_fill
        if record.side == Side.BUY:
            change = record.fill_price - mid_after  # price drop after buy → more accumulation at better prices → favorable
        else:
            change = mid_after - record.fill_price
        return change / record.mid_at_fill * 10000.0

    def flush(self) -> list[MarkoutRecord]:
        """Force-complete all pending records with latest mid, return them.

        Called at shutdown so pending markout data is not silently discarded.
        """
        flushed: list[MarkoutRecord] = []
        for record, _deadline in self._pending:
            # Fill remaining intervals with last known mid
            for interval in MARKOUT_INTERVALS:
                if interval not in record.mids_after:
                    record.mids_after[interval] = self._last_mid
            flushed.append(record)
        self._pending.clear()
        self._completed.extend(flushed)
        logger.info("markout_flushed", count=len(flushed))
        return flushed

    def reset(self) -> None:
        self._pending.clear()
        self._completed.clear()
        self._last_mid = 0.0
        self._last_mid_time = 0.0
