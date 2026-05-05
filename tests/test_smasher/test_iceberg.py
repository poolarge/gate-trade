"""Tests for IcebergDetector — Phase 7.2."""

from __future__ import annotations

from gate_trade.smasher.iceberg import IcebergDetector


class TestUpdate:
    def test_no_signals_with_single_snapshot(self):
        det = IcebergDetector(replenish_threshold=3)
        signals = det.update(bids=[(50000.0, 1.0)], asks=[(50100.0, 0.5)], timestamp=0.0)
        assert signals == []

    def test_no_signals_when_quantity_stable(self):
        det = IcebergDetector(replenish_threshold=3, window_sec=30.0)
        for ts in range(5):
            det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=float(ts))
        assert det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=5.0) == []

    def test_detects_repeated_replenishment(self):
        det = IcebergDetector(replenish_threshold=3, window_sec=30.0)
        det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=0.0)
        det.update(bids=[(50000.0, 0.3)], asks=[], timestamp=1.0)  # consumed
        det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=2.0)  # replenished (1st)
        det.update(bids=[(50000.0, 0.3)], asks=[], timestamp=3.0)  # consumed
        det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=4.0)  # replenished (2nd)
        det.update(bids=[(50000.0, 0.3)], asks=[], timestamp=5.0)  # consumed
        signals = det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=6.0)  # 3rd replenishment
        assert len(signals) == 1
        assert signals[0].price == 50000.0
        assert signals[0].side == "bid"
        assert signals[0].replenishments >= 3

    def test_detects_ask_iceberg(self):
        det = IcebergDetector(replenish_threshold=2, window_sec=30.0)
        det.update(bids=[], asks=[(60000.0, 2.0)], timestamp=0.0)
        det.update(bids=[], asks=[(60000.0, 0.5)], timestamp=1.0)
        det.update(bids=[], asks=[(60000.0, 2.0)], timestamp=2.0)
        det.update(bids=[], asks=[(60000.0, 0.5)], timestamp=3.0)
        signals = det.update(bids=[], asks=[(60000.0, 2.0)], timestamp=4.0)
        assert len(signals) == 1
        assert signals[0].side == "ask"

    def test_no_detection_below_replenish_threshold(self):
        det = IcebergDetector(replenish_threshold=5, window_sec=30.0)
        for i in range(3):
            det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=float(i * 2))
            det.update(bids=[(50000.0, 0.5)], asks=[], timestamp=float(i * 2 + 1))
        signals = det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=7.0)
        assert signals == []

    def test_ignores_quantity_below_min_replenish_size(self):
        det = IcebergDetector(replenish_threshold=3, min_replenish_size=0.1)
        # Tiny quantities —should be ignored
        det.update(bids=[(50000.0, 0.05)], asks=[], timestamp=0.0)
        det.update(bids=[(50000.0, 0.01)], asks=[], timestamp=1.0)
        det.update(bids=[(50000.0, 0.05)], asks=[], timestamp=2.0)
        det.update(bids=[(50000.0, 0.01)], asks=[], timestamp=3.0)
        signals = det.update(bids=[(50000.0, 0.05)], asks=[], timestamp=4.0)
        assert signals == []

    def test_old_levels_cleaned_up(self):
        det = IcebergDetector(window_sec=10.0, replenish_threshold=3)
        det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=0.0)
        det.update(bids=[(50000.0, 0.5)], asks=[], timestamp=1.0)
        det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=2.0)
        # New snapshot without the level — it should be removed
        det.update(bids=[], asks=[], timestamp=3.0)
        # Bring it back — should be a fresh start
        signals = det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=4.0)
        assert signals == []

    def test_old_entries_expired_by_window(self):
        det = IcebergDetector(window_sec=2.0, replenish_threshold=3)
        det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=0.0)
        det.update(bids=[(50000.0, 0.3)], asks=[], timestamp=1.0)
        det.update(bids=[(50000.0, 1.0)], asks=[], timestamp=1.5)
        # Now everything is expired by window
        signals = det.update(bids=[(50000.0, 0.3)], asks=[], timestamp=10.0)
        assert signals == []


class TestReset:
    def test_clears_tracked_levels(self):
        det = IcebergDetector()
        det.update(bids=[(50000.0, 1.0)], asks=[(50100.0, 2.0)], timestamp=0.0)
        det.reset()
        assert det._bid_levels == {}
        assert det._ask_levels == {}
