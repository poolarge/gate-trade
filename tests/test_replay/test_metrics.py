"""Tests for MetricsCollector + ReplayResult — Phase 9.2."""

from __future__ import annotations

from gate_trade.replay.metrics import MetricsCollector
from gate_trade.types import Side


class TestRecordFill:
    def test_inventory_tracking(self):
        mc = MetricsCollector()
        mc.record_fill(Side.BUY, 50000.0, 0.1, 1.0)
        mc.record_fill(Side.SELL, 50100.0, 0.05, 2.0)
        result = mc.summarize()
        assert result.net_inventory == 0.05
        assert result.buy_count == 1
        assert result.sell_count == 1

    def test_peak_inventory(self):
        mc = MetricsCollector()
        mc.record_fill(Side.BUY, 50000.0, 0.5, 1.0)
        mc.record_fill(Side.SELL, 50100.0, 0.2, 2.0)
        assert mc.summarize().peak_inventory == 0.5

    def test_volume_calculations(self):
        mc = MetricsCollector()
        mc.record_fill(Side.BUY, 50000.0, 0.1, 1.0)
        mc.record_fill(Side.BUY, 49900.0, 0.1, 1.5)
        result = mc.summarize()
        assert result.buy_volume == 50000.0 * 0.1 + 49900.0 * 0.1


class TestRecordMarkout:
    def test_average_markout(self):
        mc = MetricsCollector()
        mc.record_markout(-10.0)
        mc.record_markout(20.0)
        mc.record_markout(5.0, is_toxic=True)
        result = mc.summarize()
        assert result.avg_markout_bps == 5.0
        assert result.toxic_fill_count == 1

    def test_empty_markout(self):
        mc = MetricsCollector()
        result = mc.summarize()
        assert result.avg_markout_bps == 0.0


class TestReplayResult:
    def test_toxic_ratio(self):
        mc = MetricsCollector()
        mc.record_fill(Side.BUY, 50000.0, 0.1, 1.0)
        mc.record_fill(Side.BUY, 50000.0, 0.1, 2.0)
        mc.record_markout(-5.0, is_toxic=True)
        mc.record_markout(3.0)
        result = mc.summarize()
        assert result.toxic_ratio == 0.5

    def test_empty_toxic_ratio(self):
        mc = MetricsCollector()
        assert mc.summarize().toxic_ratio == 0.0


class TestReset:
    def test_clears_all(self):
        mc = MetricsCollector()
        mc.record_snapshot()
        mc.record_fill(Side.BUY, 50000.0, 0.1, 1.0)
        mc.record_markout(5.0, is_toxic=True)
        mc.reset()
        result = mc.summarize()
        assert result.total_snapshots == 0
        assert result.total_fills == 0
        assert result.toxic_fill_count == 0
