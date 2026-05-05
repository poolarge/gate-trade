"""Unit tests for DepthKeeper — Phase 2.4."""

from __future__ import annotations

import time

import pytest

from gate_trade.strategy.depth import DepthKeeper
from gate_trade.types import Side


@pytest.fixture
def dk() -> DepthKeeper:
    return DepthKeeper(
        pair="BTC_USDT",
        tick_size=0.01,
        tier_sizes=(1.0, 2.0, 5.0),
        tier_spread_ticks=(5, 15, 30),
        anti_spoof_window_sec=30.0,
        anti_spoof_flash_threshold=3,
        dormant_cooldown_sec=60.0,
    )


class TestQuotePlacement:
    def test_three_tiers_both_sides(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        orders = dk.desired_orders()
        # 3 tiers * 2 sides = 6 orders
        assert len(orders) == 6
        buys = [o for o in orders if o.side == Side.BUY]
        sells = [o for o in orders if o.side == Side.SELL]
        assert len(buys) == 3
        assert len(sells) == 3

    def test_tiers_are_symmetric(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        orders = dk.desired_orders()
        buys = sorted([o for o in orders if o.side == Side.BUY], key=lambda o: o.price, reverse=True)
        sells = sorted([o for o in orders if o.side == Side.SELL], key=lambda o: o.price)
        # Corresponding tiers: buy[i] and sell[i] should be equidistant from ref
        for b, s in zip(buys, sells, strict=True):
            assert abs(50000.0 - b.price) == pytest.approx(abs(s.price - 50000.0), rel=1e-6)

    def test_buy_prices_below_ref(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        orders = dk.desired_orders()
        for o in orders:
            if o.side == Side.BUY:
                assert o.price < 50000.0

    def test_sell_prices_above_ref(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        orders = dk.desired_orders()
        for o in orders:
            if o.side == Side.SELL:
                assert o.price > 50000.0

    def test_tick_alignment(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.03)
        orders = dk.desired_orders()
        for o in orders:
            assert round(o.price / 0.01, 6) == round(o.price / 0.01)

    def test_empty_when_no_ref(self, dk: DepthKeeper) -> None:
        assert dk.desired_orders() == []

    def test_tier_sizes_match_config(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        orders = dk.desired_orders()
        sizes = {1.0, 2.0, 5.0}
        for side in (Side.BUY, Side.SELL):
            side_sizes = {o.size for o in orders if o.side == side}
            assert side_sizes == sizes


class TestActiveDormantToggle:
    def test_starts_active(self, dk: DepthKeeper) -> None:
        assert dk.active is True
        assert dk.dormant is False

    def test_flash_threshold_triggers_dormant(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        for _ in range(3):
            dk.report_flash(50000.0, Side.BUY)
        assert dk.dormant is True
        assert dk.active is False

    def test_dormant_returns_empty_orders(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        for _ in range(3):
            dk.report_flash(50000.0, Side.BUY)
        assert dk.desired_orders() == []

    def test_dormant_expires_after_cooldown(self, dk: DepthKeeper) -> None:
        dk2 = DepthKeeper(pair="BTC_USDT", dormant_cooldown_sec=0.01)
        dk2.update_market(50000.0)
        for _ in range(3):
            dk2.report_flash(50000.0, Side.BUY)
        assert dk2.dormant is True
        time.sleep(0.02)
        orders = dk2.desired_orders()
        assert len(orders) > 0
        assert dk2.dormant is False

    def test_flash_below_threshold_no_trigger(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        dk.report_flash(50000.0, Side.BUY)
        dk.report_flash(50000.0, Side.BUY)
        assert dk.dormant is False
        assert len(dk.desired_orders()) > 0


class TestAntiSpoof:
    def test_acceptance_normal_cancel_no_dormant_trigger(self, dk: DepthKeeper) -> None:
        """Core acceptance: normal on_cancel does NOT trigger DORMANT.
        Only explicit report_flash (from Smasher) triggers it."""
        dk.update_market(50000.0)
        # on_cancel is a no-op — it must not affect dormant state
        from gate_trade.types import Order, OrderStatus
        order = Order(order_id="x", pair="BTC_USDT", side=Side.BUY,
                      price=50000.0, size=1.0, status=OrderStatus.CANCELLED)
        for _ in range(10):
            dk.on_cancel(order)
        assert dk.dormant is False
        assert len(dk.desired_orders()) > 0

    def test_old_flashes_pruned(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        old_ts = time.monotonic() - 60  # well outside the 30s window
        dk.report_flash(50000.0, Side.BUY, timestamp=old_ts)
        dk.report_flash(50000.0, Side.BUY, timestamp=old_ts)
        # Only 1 fresh flash, 2 old ones pruned → below threshold
        dk.report_flash(50000.0, Side.SELL)
        assert dk.dormant is False

    def test_fresh_flashes_accumulate(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        for i in range(3):
            dk.report_flash(50000.0 + i, Side.BUY)
        assert dk.dormant is True


class TestSpikeInteraction:
    def test_spike_suppresses_orders(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        assert len(dk.desired_orders()) > 0
        dk.update_market(50000.0, spike_active=True)
        assert dk.desired_orders() == []

    def test_orders_resume_after_spike_clears(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        dk.update_market(50000.0, spike_active=True)
        dk.desired_orders()
        dk.update_market(50000.0, spike_active=False)
        assert len(dk.desired_orders()) > 0


class TestConfig:
    def test_disabled_returns_empty(self) -> None:
        dk2 = DepthKeeper(pair="BTC_USDT", enabled=False)
        dk2.update_market(50000.0)
        assert dk2.desired_orders() == []
        assert dk2.active is False

    def test_custom_tier_config(self) -> None:
        dk2 = DepthKeeper(
            pair="ETH_USDT", tick_size=0.10,
            tier_sizes=(0.5, 1.0, 3.0),
            tier_spread_ticks=(3, 10, 20),
        )
        dk2.update_market(3000.0)
        orders = dk2.desired_orders()
        assert len(orders) == 6
        sizes = {0.5, 1.0, 3.0}
        side_sizes = {o.size for o in orders if o.side == Side.BUY}
        assert side_sizes == sizes


class TestReset:
    def test_reset_clears_dormant(self, dk: DepthKeeper) -> None:
        dk.update_market(50000.0)
        for _ in range(3):
            dk.report_flash(50000.0, Side.BUY)
        assert dk.dormant is True
        dk.reset()
        assert dk.dormant is False
        assert dk.active is True
