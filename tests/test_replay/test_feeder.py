"""Tests for DataFeeder — Phase 9.2."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from gate_trade.replay.feeder import DataFeeder, MarketSnapshot

SAMPLE_CSV = """timestamp,best_bid,best_ask,bid_size,ask_size,last_price
0.0,50000.0,50010.0,1.5,0.8,50005.0
1.0,50001.0,50011.0,1.2,1.0,50006.0
2.0,50002.0,50012.0,1.0,0.9,50007.0
"""


class TestFromList:
    def test_basic(self):
        snaps = [MarketSnapshot(0.0, 100.0, 101.0, 1.0, 0.5, 100.5)]
        feeder = DataFeeder.from_list(snaps)
        assert len(feeder) == 1

    def test_iteration(self):
        snaps = [
            MarketSnapshot(0.0, 100.0, 101.0, 1.0, 0.5, 100.5),
            MarketSnapshot(1.0, 101.0, 102.0, 2.0, 1.0, 101.5),
        ]
        feeder = DataFeeder.from_list(snaps)
        items = list(feeder)
        assert len(items) == 2
        assert items[0].mid_price == 100.5
        assert items[1].mid_price == 101.5

    def test_progress(self):
        snaps = [MarketSnapshot(float(i), 100.0, 101.0, 1.0, 0.5, 100.5) for i in range(10)]
        feeder = DataFeeder.from_list(snaps)
        assert feeder.progress == 0.0
        next(feeder)
        assert feeder.progress == 0.1

    def test_empty(self):
        feeder = DataFeeder.from_list([])
        assert list(feeder) == []
        assert feeder.progress == 1.0


class TestFromCsv:
    def test_loads_all_rows(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(SAMPLE_CSV)
            tmp = f.name

        try:
            feeder = DataFeeder.from_csv(tmp)
            assert len(feeder) == 3
            snaps = list(feeder)
            assert snaps[0].timestamp == 0.0
            assert snaps[0].best_bid == 50000.0
            assert snaps[0].mid_price == 50005.0
            assert snaps[2].last_price == 50007.0
        finally:
            Path(tmp).unlink()

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            DataFeeder.from_csv("/nonexistent/path.csv")


class TestMarketSnapshot:
    def test_mid_price_normal(self):
        snap = MarketSnapshot(0.0, 100.0, 102.0, 1.0, 1.0, 101.0)
        assert snap.mid_price == 101.0

    def test_mid_price_falls_back_to_last(self):
        snap = MarketSnapshot(0.0, 0.0, 0.0, 1.0, 1.0, 101.0)
        assert snap.mid_price == 101.0
