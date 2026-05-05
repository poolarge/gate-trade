"""Toxic Detector — boolean conjunction of toxic counterparty signals.

Phase 6.2: Combines multiple weak signals into a single toxicity flag.
All signals must be true for a fill to be marked toxic (conservative).

Signals:
    adverse_markout  — markout P&L is significantly negative
    large_size       — fill size exceeds typical maker flow
    fast_reversal    — mid moved against us rapidly after fill
"""

from __future__ import annotations

from collections import deque

import structlog

from gate_trade.markout.recorder import MarkoutRecord, MarkoutRecorder

logger = structlog.get_logger(__name__)


class ToxicDetector:
    """Conservative toxic counterparty detector.

    All signals must fire simultaneously (boolean AND) to flag a fill
    as toxic. This avoids false positives from normal market noise.
    """

    def __init__(
        self,
        adverse_markout_bps: float = -20.0,
        large_size_multiple: float = 3.0,
        fast_reversal_bps: float = 10.0,
        window_fills: int = 20,
    ) -> None:
        self._adverse_threshold = adverse_markout_bps
        self._large_size_multiple = large_size_multiple
        self._fast_reversal_threshold = fast_reversal_bps
        self._window = window_fills

        # Rolling statistics
        self._fill_sizes: deque[float] = deque(maxlen=window_fills)

        # Toxic fill tracking
        self._toxic_count: int = 0
        self._total_count: int = 0

    @property
    def toxic_ratio(self) -> float:
        if self._total_count == 0:
            return 0.0
        return self._toxic_count / self._total_count

    @property
    def total_count(self) -> int:
        return self._total_count

    @property
    def toxic_count(self) -> int:
        return self._toxic_count

    def evaluate(self, record: MarkoutRecord) -> bool:
        """Evaluate a completed markout record for toxicity.

        Returns True if the fill is flagged as toxic.
        """
        self._total_count += 1
        self._fill_sizes.append(record.fill_size)

        signals: dict[str, bool] = {
            "adverse_markout": self._check_adverse_markout(record),
            "large_size": self._check_large_size(record),
            "fast_reversal": self._check_fast_reversal(record),
        }

        is_toxic = all(signals.values())
        if is_toxic:
            self._toxic_count += 1
            logger.warning("toxic_fill_detected",
                          order_id=record.order_id,
                          signals=signals,
                          markout_bps=round(MarkoutRecorder._compute_markout_bps(record), 2))

        return is_toxic

    # ── Signal checks ────────────────────────────────────────────

    def _check_adverse_markout(self, record: MarkoutRecord) -> bool:
        bps = MarkoutRecorder._compute_markout_bps(record)
        return bps <= self._adverse_threshold

    def _check_large_size(self, record: MarkoutRecord) -> bool:
        if len(self._fill_sizes) < 4:
            return False
        avg = sum(self._fill_sizes) / len(self._fill_sizes)
        if avg <= 0:
            return False
        return record.fill_size >= avg * self._large_size_multiple

    def _check_fast_reversal(self, record: MarkoutRecord) -> bool:
        mid_1s = record.mids_after.get(1.0)
        if mid_1s is None or record.mid_at_fill <= 0:
            return False
        reversal = abs(mid_1s - record.mid_at_fill) / record.mid_at_fill * 10000.0
        return reversal >= self._fast_reversal_threshold

    def reset(self) -> None:
        self._fill_sizes.clear()
        self._toxic_count = 0
        self._total_count = 0
