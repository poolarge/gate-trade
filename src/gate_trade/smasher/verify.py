"""SmasherVerifier — verifies that smasher actions improved markout.

Phase 7.4: Collects markout samples before and after a smasher
intervention, then compares means to determine if the action
had a positive effect.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Verdict:
    improved: bool
    mean_before: float
    mean_after: float
    delta_bps: float
    samples_before: int
    samples_after: int


class SmasherVerifier:
    """Collect markout samples and compare before/after intervention.

    Uses Welch's t-test to assess whether mean markout improved
    after the smasher action.
    """

    def __init__(self, min_samples: int = 20, significance: float = 0.05) -> None:
        self._min_samples = min_samples
        self._significance = significance

        self._before: list[float] = []
        self._after: list[float] = []

    @property
    def samples_before(self) -> int:
        return len(self._before)

    @property
    def samples_after(self) -> int:
        return len(self._after)

    def add_before(self, markout_bps: float) -> None:
        self._before.append(markout_bps)

    def add_after(self, markout_bps: float) -> None:
        self._after.append(markout_bps)

    def compare(self) -> Verdict | None:
        """Compare markout distributions before and after.

        Returns None if either sample set is too small.
        Positive delta means markout improved after intervention.
        """
        if len(self._before) < self._min_samples or len(self._after) < self._min_samples:
            return None

        mean_b = sum(self._before) / len(self._before)
        mean_a = sum(self._after) / len(self._after)
        delta = mean_a - mean_b

        # Welch's t-test
        var_b = self._variance(self._before, mean_b)
        var_a = self._variance(self._after, mean_a)
        n_b, n_a = len(self._before), len(self._after)

        se = math.sqrt(var_b / n_b + var_a / n_a)
        if se <= 0:
            return Verdict(
                improved=delta > 0,
                mean_before=mean_b, mean_after=mean_a,
                delta_bps=delta,
                samples_before=n_b, samples_after=n_a,
            )

        t_stat = delta / se

        # Welch-Satterthwaite degrees of freedom
        num = (var_b / n_b + var_a / n_a) ** 2
        den = (var_b / n_b) ** 2 / (n_b - 1) + (var_a / n_a) ** 2 / (n_a - 1)
        df = num / den if den > 0 else 1.0

        # One-tailed critical value approximation for alpha=0.05
        critical = self._t_critical(df, self._significance)
        improved = t_stat > critical

        logger.info("smasher_verdict",
                    improved=improved, delta_bps=round(delta, 2),
                    t_stat=round(t_stat, 3), df=round(df, 1),
                    samples_before=n_b, samples_after=n_a)

        return Verdict(
            improved=improved,
            mean_before=mean_b, mean_after=mean_a,
            delta_bps=delta,
            samples_before=n_b, samples_after=n_a,
        )

    def reset(self) -> None:
        self._before.clear()
        self._after.clear()

    @staticmethod
    def _variance(samples: list[float], mean: float) -> float:
        if len(samples) < 2:
            return 0.0
        return sum((x - mean) ** 2 for x in samples) / (len(samples) - 1)

    @staticmethod
    def _t_critical(df: float, alpha: float) -> float:
        """Approximate one-tailed t critical value.

        Uses a simple rational approximation for df >= 1.
        Accurate enough for verification purposes.
        """
        if df <= 0:
            return 10.0
        # For large df, approximate with normal distribution
        if df > 100:
            # z-score for one-tailed alpha=0.05 is ~1.645
            z_scores: dict[float, float] = {0.05: 1.645, 0.01: 2.326, 0.10: 1.282}
            return z_scores.get(alpha, 1.645)

        # Approximation formula for t-distribution
        z = SmasherVerifier._t_critical(200.0, alpha)  # normal approx as baseline
        correction = (z**3 + z) / (4 * df)
        return z + correction
