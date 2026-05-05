"""Contract tests for MarketData protocol."""

from __future__ import annotations

import pytest

from mocks.mock_market_data import MockMarketData


@pytest.fixture
def md():
    return MockMarketData()


class TestMarketDataContract:
    def test_empty_book_returns_zero_best(self, md):
        assert md.best_bid() == 0.0
        assert md.best_ask() == 0.0
        assert md.mid_price() == 0.0

    def test_book_with_levels_returns_correct_best(self, md):
        md.set_book(
            bids=[(50000.0, 1.0), (49900.0, 2.0)],
            asks=[(50100.0, 1.5), (50200.0, 2.0)],
        )
        assert md.best_bid() == 50000.0
        assert md.best_ask() == 50100.0
        assert md.mid_price() == 50050.0

    def test_spread_bps(self, md):
        md.set_book(
            bids=[(50000.0, 1.0)],
            asks=[(50050.0, 1.0)],
        )
        assert md.spread_bps() == pytest.approx(10.0, rel=0.1)  # 50/50025*10000 ≈ 9.995

    def test_apply_snapshot_replaces_book(self, md):
        from gate_trade.types import OrderBook, OrderBookLevel

        book = OrderBook(
            bids=[OrderBookLevel(price=100.0, size=1.0)],
            asks=[OrderBookLevel(price=101.0, size=2.0)],
        )
        md.apply_snapshot(book)
        assert md.best_bid() == 100.0
        assert md.best_ask() == 101.0

    def test_flash_crash_defaults_false(self, md):
        assert md.flash_crash is False

    def test_set_flash_crash(self, md):
        md.set_flash_crash(True)
        assert md.flash_crash is True

    def test_depth_wall_defaults_false(self, md):
        assert md.depth_wall is False

    def test_depth_at_price_buy_side(self, md):
        md.set_book(
            bids=[(50000.0, 1.0), (49900.0, 2.0), (49800.0, 3.0)],
            asks=[(50100.0, 1.0)],
        )
        # Bids >= 49900 should include the top two levels
        depth = md.depth_at_price("buy", 49900.0)
        assert depth == 3.0

    def test_depth_at_price_sell_side(self, md):
        md.set_book(
            bids=[(50000.0, 1.0)],
            asks=[(50100.0, 1.0), (50200.0, 2.0), (50300.0, 3.0)],
        )
        depth = md.depth_at_price("sell", 50200.0)
        assert depth == 3.0

    def test_vwap_returns_nonzero_for_valid_depth(self, md):
        md.set_book(
            bids=[(50000.0, 1.0), (49900.0, 1.0)],
            asks=[(50100.0, 1.0)],
        )
        vwap = md.vwap("buy", 50000.0)
        assert vwap > 0

    def test_compute_signals_returns_signal_object(self, md):
        sig = md.compute_signals()
        from gate_trade.types import MarketSignal
        assert isinstance(sig, MarketSignal)
