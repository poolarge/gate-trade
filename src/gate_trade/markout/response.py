"""Toxic Response — graduated reactions to toxic counterparty detection.

Phase 6.3: When toxicity exceeds thresholds, responds with escalating
countermeasures: widen spreads, go DORMANT, or halt trading entirely.
"""

from __future__ import annotations

from enum import Enum

import structlog

logger = structlog.get_logger(__name__)


class ToxicLevel(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"    # widen spreads
    DORMANT = "DORMANT"      # stop placing orders temporarily
    HALT = "HALT"            # all trading must stop


class ToxicResponse:
    """Graduated response to toxicity based on rolling toxic_fill ratio.

    Thresholds are tuned to avoid over-reacting to a single bad fill.
    """

    def __init__(
        self,
        elevated_ratio: float = 0.2,
        dormant_ratio: float = 0.4,
        halt_ratio: float = 0.6,
        min_samples: int = 5,
        cooldown_sec: float = 120.0,
    ) -> None:
        self._elevated_ratio = elevated_ratio
        self._dormant_ratio = dormant_ratio
        self._halt_ratio = halt_ratio
        self._min_samples = min_samples
        self._cooldown = cooldown_sec

        self._level: ToxicLevel = ToxicLevel.NORMAL
        self._elevated_since: float = 0.0
        self._last_evaluation: float = 0.0

    @property
    def level(self) -> ToxicLevel:
        return self._level

    @property
    def spread_multiplier(self) -> float:
        """How much to widen spreads: 1.0 = no change, 1.5 = 50% wider."""
        import time
        if self._level == ToxicLevel.DORMANT or self._level == ToxicLevel.HALT:
            return 999.0  # effectively no trading
        if self._level == ToxicLevel.ELEVATED:
            elapsed = time.monotonic() - self._elevated_since
            # Gradual widening: starts at 1.0, caps at 2.0 over 60 seconds
            return min(1.0 + elapsed / 60.0, 2.0)
        return 1.0

    def evaluate(self, toxic_ratio: float, total_count: int) -> ToxicLevel:
        """Update response level based on current toxicity ratio."""
        import time
        now = time.monotonic()
        self._last_evaluation = now

        if total_count < self._min_samples:
            return self._level

        if toxic_ratio >= self._halt_ratio:
            new_level = ToxicLevel.HALT
        elif toxic_ratio >= self._dormant_ratio:
            new_level = ToxicLevel.DORMANT
        elif toxic_ratio >= self._elevated_ratio:
            new_level = ToxicLevel.ELEVATED
        else:
            new_level = ToxicLevel.NORMAL

        if new_level != self._level:
            old = self._level
            self._level = new_level
            if new_level == ToxicLevel.ELEVATED:
                self._elevated_since = now
            if new_level in (ToxicLevel.DORMANT, ToxicLevel.HALT):
                logger.warning("toxic_response_escalated", old=old.value, new=new_level.value)
            elif new_level == ToxicLevel.NORMAL:
                logger.info("toxic_response_normalized", old=old.value)

        # Auto-recover from ELEVATED after cooldown
        if (self._level == ToxicLevel.ELEVATED
                and now - self._elevated_since > self._cooldown
                and toxic_ratio < self._elevated_ratio):
            self._level = ToxicLevel.NORMAL
            logger.info("toxic_response_cooldown_recovery")

        return self._level

    def reset(self) -> None:
        self._level = ToxicLevel.NORMAL
        self._elevated_since = 0.0
