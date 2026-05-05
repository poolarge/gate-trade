"""Unit tests for LiveMarketData implementation."""

from __future__ import annotations

import pytest

from gate_trade.market.market_data import LiveMarketData
from gate_trade.types import OrderBook, OrderBookLevel


@pytest.fixture
def md():
    return LiveMarketData()


def _snap(bids=None, asks=None):
    """Shorthand to build a full OrderBook snapshot."""
    return OrderBook(
        bids=[OrderBookLevel(price=p, size=s) for p, s in (bids or [])],
        asks=[OrderBookLevel(price=p, size=s) for p, s in (asks or [])],
    )


class TestSnapshot:
    def test_empty_book(self, md):
        assert md.best_bid() == 0.0
        assert md.best_ask() == 0.0
        assert md.mid_price() == 0.0
        assert md.spread_bps() == 0.0

    def test_snapshot_sets_book(self, md):
        md.apply_snapshot(_snap(
            bids=[(50000, 1.0), (49900, 2.0)],
            asks=[(50100, 1.5), (50200, 0.5)],
        ))
        assert md.best_bid() == 50000.0
        assert md.best_ask() == 50100.0
        assert md.mid_price() == 50050.0

    def test_snapshot_sorts_bids_desc(self, md):
        md.apply_snapshot(_snap(
            bids=[(49900, 2.0), (50000, 1.0), (49800, 3.0)],
            asks=[],
        ))
        prices = [level.price for level in md.bids]
        assert prices == [50000.0, 49900.0, 49800.0]

    def test_snapshot_sorts_asks_asc(self, md):
        md.apply_snapshot(_snap(
            bids=[],
            asks=[(50200, 0.5), (50100, 1.5), (50300, 0.3)],
        ))
        prices = [level.price for level in md.asks]
        assert prices == [50100.0, 50200.0, 50300.0]

    def test_snapshot_replaces_previous(self, md):
        md.apply_snapshot(_snap(bids=[(50000, 1.0)], asks=[(50100, 1.0)]))
        md.apply_snapshot(_snap(bids=[(60000, 2.0)], asks=[(60100, 2.0)]))
        assert md.best_bid() == 60000.0
        assert md.best_ask() == 60100.0


class TestDelta:
    def test_delta_insert_new_bid(self, md):
        md.apply_snapshot(_snap(bids=[(50000, 1.0)], asks=[(50100, 1.0)]))
        md.apply_delta("buy", 50100, 0.5)
        assert md.best_bid() == 50100.0
        assert len(md.bids) == 2

    def test_delta_update_existing_bid(self, md):
        md.apply_snapshot(_snap(bids=[(50000, 1.0)], asks=[(50100, 1.0)]))
        md.apply_delta("buy", 50000, 3.0)
        assert md.bids[0].size == 3.0
        assert len(md.bids) == 1

    def test_delta_remove_bid(self, md):
        md.apply_snapshot(_snap(bids=[(50000, 1.0), (49900, 2.0)], asks=[(50100, 1.0)]))
        md.apply_delta("buy", 50000, 0.0)
        assert md.best_bid() == 49900.0
        assert len(md.bids) == 1

    def test_delta_insert_ask(self, md):
        md.apply_snapshot(_snap(bids=[(50000, 1.0)], asks=[(50200, 1.0)]))
        md.apply_delta("sell", 50100, 2.0)
        assert md.best_ask() == 50100.0

    def test_delta_remove_ask(self, md):
        md.apply_snapshot(_snap(bids=[(50000, 1.0)], asks=[(50100, 1.0), (50200, 1.0)]))
        md.apply_delta("sell", 50100, 0.0)
        assert md.best_ask() == 50200.0

    def test_delta_on_empty_book(self, md):
        md.apply_delta("buy", 50000, 1.0)
        assert md.best_bid() == 50000.0
        md.apply_delta("sell", 50100, 1.0)
        assert md.best_ask() == 50100.0


class TestDepth:
    def test_depth_at_price_bids(self, md):
        md.apply_snapshot(_snap(
            bids=[(50000, 1.0), (49900, 2.0), (49800, 3.0)],
            asks=[],
        ))
        assert md.depth_at_price("buy", 49900) == 3.0
        assert md.depth_at_price("buy", 49800) == 6.0
        assert md.depth_at_price("buy", 50100) == 0.0

    def test_depth_at_price_asks(self, md):
        md.apply_snapshot(_snap(
            bids=[],
            asks=[(50100, 1.0), (50200, 2.0), (50300, 3.0)],
        ))
        assert md.depth_at_price("sell", 50200) == 3.0
        assert md.depth_at_price("sell", 50000) == 0.0

    def test_depth_empty_book(self, md):
        assert md.depth_at_price("buy", 50000) == 0.0
        assert md.depth_at_price("sell", 50100) == 0.0

    def test_vwap_basic(self, md):
        md.apply_snapshot(_snap(
            bids=[(50000, 1.0), (49900, 1.0)],
            asks=[(50100, 1.0)],
        ))
        vwap = md.vwap("buy", 50000.0)
        assert vwap > 0

    def test_vwap_empty_book(self, md):
        assert md.vwap("buy", 10000) == 0.0

    def test_vwap_zero_notional(self, md):
        md.apply_snapshot(_snap(bids=[(50000, 1.0)], asks=[]))
        assert md.vwap("buy", 0.0) == 0.0


class TestBookProperty:
    def test_book_returns_ordered_snapshot(self, md):
        md.apply_snapshot(_snap(
            bids=[(50000, 1.0), (49900, 2.0)],
            asks=[(50100, 1.5), (50200, 0.5)],
        ))
        b = md.book
        assert b.best_bid == 50000.0
        assert b.best_ask == 50100.0
        assert b.mid_price == 50050.0
        assert b.spread == 100.0

    def test_book_is_copy_not_ref(self, md):
        md.apply_snapshot(_snap(bids=[(50000, 1.0)], asks=[(50100, 1.0)]))
        b = md.book
        b.bids.append(OrderBookLevel(price=49900, size=99))
        assert len(md.bids) == 1  # original unchanged


class TestSignals:
    def test_flash_crash_defaults_false(self, md):
        assert md.flash_crash is False

    def test_flash_crash_on_single_snapshot(self, md):
        md.apply_snapshot(_snap(bids=[(50000, 1.0)], asks=[(50100, 1.0)]))
        assert md.flash_crash is False  # need more history

    def test_depth_wall_defaults_false(self, md):
        assert md.depth_wall is False

    def test_depth_wall_detected(self, md):
        # One giant level dwarfs others
        bids = [(50000, 100.0)] + [(p, 1.0) for p in range(49990, 49980, -1)]
        asks = [(50100, 100.0)] + [(p, 1.0) for p in range(50110, 50120)]
        md.apply_snapshot(_snap(bids=bids, asks=asks))
        assert md.depth_wall is True

    def test_depth_wall_false_when_uniform(self, md):
        bids = [(50000 - i * 10, 5.0) for i in range(10)]
        asks = [(50100 + i * 10, 5.0) for i in range(10)]
        md.apply_snapshot(_snap(bids=bids, asks=asks))
        assert md.depth_wall is False

    def test_compute_signals_returns_cached(self, md):
        md.apply_snapshot(_snap(bids=[(50000, 1.0)], asks=[(50100, 1.0)]))
        sig1 = md.compute_signals()
        sig2 = md.compute_signals()
        assert sig1 is sig2  # cached

    def test_compute_signals_stale_after_delta(self, md):
        md.apply_snapshot(_snap(bids=[(50000, 1.0)], asks=[(50100, 1.0)]))
        sig1 = md.compute_signals()
        md.apply_delta("buy", 50000, 0.0)
        sig2 = md.compute_signals()
        assert sig1 is not sig2

    def test_imbalance_returns_value_in_range(self, md):
        md.apply_snapshot(_snap(
            bids=[(50000, 1.0), (49900, 1.0)],
            asks=[(50100, 1.0), (50200, 1.0)],
        ))
        sig = md.compute_signals()
        assert -1.0 <= sig.imbalance <= 1.0
