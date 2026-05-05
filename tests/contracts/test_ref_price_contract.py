"""Contract tests for RefPriceEngine protocol."""

from __future__ import annotations

import pytest

from mocks.mock_ref_price import MockRefPriceEngine


@pytest.fixture
def rpe():
    return MockRefPriceEngine(ref=50000.0, spread_ticks=5, tick_size=0.01)


class TestRefPriceEngineContract:
    def test_ref_price_default(self, rpe):
        assert rpe.ref_price == 50000.0

    def test_ref_bid_below_ref(self, rpe):
        assert rpe.ref_bid < rpe.ref_price

    def test_ref_ask_above_ref(self, rpe):
        assert rpe.ref_ask > rpe.ref_price

    def test_spread_symmetric(self, rpe):
        half_spread = rpe.ref_ask - rpe.ref_price
        assert rpe.ref_price - rpe.ref_bid == pytest.approx(half_spread)

    def test_update_recomputes_ref(self, rpe):
        rpe.update(best_bid=49900.0, best_ask=50100.0, own_bids=[], own_asks=[])
        assert rpe.ref_price == 50000.0

    def test_update_excludes_own_bids(self, rpe):
        # Our bid is the best bid; exclude it, fall back to ask side only
        rpe.update(best_bid=50000.0, best_ask=50100.0, own_bids=[50000.0], own_asks=[])
        # ref = ask only = 50100.0
        assert rpe.ref_price == pytest.approx(50100.0)

    def test_spike_protection_defaults_false(self, rpe):
        assert rpe.spike_protection_active is False
        assert rpe.spike_cooldown_remaining_ms == 0

    def test_reset_clears_spike(self, rpe):
        rpe.set_spike(True, remaining_ms=5000)
        rpe.reset()
        assert rpe.spike_protection_active is False

    def test_set_ref_updates_ref(self, rpe):
        rpe.set_ref(60000.0)
        assert rpe.ref_price == 60000.0
