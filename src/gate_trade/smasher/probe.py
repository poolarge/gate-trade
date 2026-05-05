"""ProbeDetector — detects probing behaviour before large toxic fills.

Phase 7.1: Tracks fill sizes over a rolling window. When a small 'probe' fill
is followed by a large fill on the same side within a time window, the
large fill is flagged as a suspected attack.
"""

from __future__ import annotations

import time
from collections import deque

import structlog

from gate_trade.types import Side

logger = structlog.get_logger(__name__)


class ProbeDetector:
    """Detect probe-then-attack patterns from counterparties.

    A probe is a fill significantly smaller than the rolling mean.
    An attack is a fill significantly larger than the rolling mean.
    When an attack follows a probe on the same side within the window,
    the fill is flagged.
    """

    def __init__(
        self,
        window_sec: float = 60.0,
        small_quantile: float = 0.3,
        large_multiple: float = 3.0,
        min_samples: int = 10,
    ) -> None:
        self._window = window_sec
        self._small_quantile = small_quantile
        self._large_multiple = large_multiple
        self._min_samples = min_samples

        self._sizes: deque[float] = deque()
        self._probes: deque[tuple[float, Side]] = deque()  # (timestamp, side)

    @property
    def mean_size(self) -> float:
        if not self._sizes:
            return 0.0
        return sum(self._sizes) / len(self._sizes)

    def on_fill(self, side: Side, size: float, timestamp: float | None = None) -> bool:
        """Evaluate a fill for probe-attack pattern.

        Returns True if this fill looks like an attack following a probe.
        """
        ts = timestamp if timestamp is not None else time.monotonic()
        self._sizes.append(size)

        if len(self._sizes) < self._min_samples:
            return False

        mean = self.mean_size
        if mean <= 0:
            return False

        is_small = size <= mean * self._small_quantile
        is_large = size >= mean * self._large_multiple

        # Expire old probes
        cutoff = ts - self._window
        while self._probes and self._probes[0][0] < cutoff:
            self._probes.popleft()

        if is_small:
            self._probes.append((ts, side))
            return False

        if is_large:
            for _ts, probe_side in self._probes:
                if probe_side == side:
                    logger.warning("probe_attack_detected",
                                   side=side.value, probe_size=round(mean * self._small_quantile, 6),
                                   attack_size=size, mean_size=round(mean, 6))
                    return True

        return False

    def reset(self) -> None:
        self._sizes.clear()
        self._probes.clear()
