"""Tests for ProbeDetector — Phase 7.1."""

from __future__ import annotations

from gate_trade.smasher.probe import ProbeDetector
from gate_trade.types import Side


class TestOnFill:
    def test_no_detection_without_min_samples(self):
        det = ProbeDetector(min_samples=10)
        for _ in range(9):
            assert det.on_fill(Side.BUY, 0.5) is False

    def test_small_fill_not_flagged_alone(self):
        det = ProbeDetector(min_samples=5, small_quantile=0.3, large_multiple=3.0)
        # Build up mean with 5 fills of size 1.0
        for _ in range(5):
            det.on_fill(Side.BUY, 1.0)
        # Small fill is <= 0.3 * mean = 0.3
        assert det.on_fill(Side.BUY, 0.2) is False

    def test_large_fill_without_probe_not_flagged(self):
        det = ProbeDetector(min_samples=5, window_sec=10.0, large_multiple=3.0)
        for _ in range(5):
            det.on_fill(Side.BUY, 1.0)
        # No prior probe, so should not flag
        assert det.on_fill(Side.BUY, 4.0) is False

    def test_probe_then_attack_flagged(self):
        det = ProbeDetector(min_samples=5, window_sec=60.0,
                            small_quantile=0.3, large_multiple=3.0)
        for _ in range(5):
            det.on_fill(Side.BUY, 1.0, timestamp=0.0)
        # Probe: small fill
        det.on_fill(Side.BUY, 0.2, timestamp=1.0)
        # Attack: large fill on same side
        assert det.on_fill(Side.BUY, 4.0, timestamp=2.0) is True

    def test_probe_opposite_side_not_flagged(self):
        det = ProbeDetector(min_samples=5, window_sec=60.0,
                            small_quantile=0.3, large_multiple=3.0)
        for _ in range(5):
            det.on_fill(Side.BUY, 1.0, timestamp=0.0)
        # Probe on BUY side
        det.on_fill(Side.BUY, 0.2, timestamp=1.0)
        # Large fill on SELL side — different side, should not flag
        assert det.on_fill(Side.SELL, 4.0, timestamp=2.0) is False

    def test_probe_expired_out_of_window(self):
        det = ProbeDetector(min_samples=5, window_sec=5.0,
                            small_quantile=0.3, large_multiple=3.0)
        for _ in range(5):
            det.on_fill(Side.BUY, 1.0, timestamp=0.0)
        # Probe at t=1
        det.on_fill(Side.BUY, 0.2, timestamp=1.0)
        # Attack at t=10, outside 5s window
        assert det.on_fill(Side.BUY, 4.0, timestamp=10.0) is False

    def test_mean_size_zero_returns_false(self):
        det = ProbeDetector(min_samples=5, large_multiple=3.0)
        for _ in range(5):
            det.on_fill(Side.BUY, 0.0)
        assert det.on_fill(Side.BUY, 1.0) is False


class TestMeanSize:
    def test_empty(self):
        det = ProbeDetector()
        assert det.mean_size == 0.0

    def test_computed_correctly(self):
        det = ProbeDetector(min_samples=1)
        for size in [1.0, 2.0, 3.0]:
            det.on_fill(Side.BUY, size)
        assert det.mean_size == 2.0


class TestReset:
    def test_clears_all_state(self):
        det = ProbeDetector(min_samples=5, large_multiple=3.0)
        for _ in range(5):
            det.on_fill(Side.BUY, 1.0)
        det.on_fill(Side.BUY, 0.2)
        det.reset()
        assert det.mean_size == 0.0
        assert len(det._sizes) == 0
        assert len(det._probes) == 0
