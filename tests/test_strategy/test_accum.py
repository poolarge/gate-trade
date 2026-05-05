"""Unit tests for Accumulator — Phase 2.3."""

from __future__ import annotations

import pytest

from gate_trade.strategy.accum import Accumulator
from gate_trade.types import Order, OrderStatus, Side


@pytest.fixture
def acc() -> Accumulator:
    return Accumulator(
        pair="BTC_USDT",
        tick_size=0.01,
        order_size=1.0,
        ladder_rungs=5,
        rung_spacing_ticks=10,
        start_offset_ticks=5,
        collapse_threshold_pct=2.0,
        collapse_recovery_pct=1.0,
    )


def _make_order(price: float, size: float = 1.0) -> Order:
    return Order(
        order_id="test-id", pair="BTC_USDT", side=Side.BUY,
        price=price, size=size, filled_size=size, status=OrderStatus.CLOSED,
    )


class TestLadderCalculation:
    def test_ladder_rungs_and_spacing(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        orders = acc.desired_orders()
        assert len(orders) == 5
        # First rung: ref - start_offset = 50000 - 0.05 = 49999.95 → aligned 49999.95
        # Actually: start_offset = 5 ticks * 0.01 = 0.05, so 50000 - 0.05 = 49999.95
        # tick_size=0.01 → round(49999.95/0.01)*0.01 = round(4999995.0)*0.01 = 49999.95
        assert orders[0].price <= 50000.0
        # Descending order
        for i in range(len(orders) - 1):
            assert orders[i].price > orders[i + 1].price

    def test_all_orders_are_buys(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        orders = acc.desired_orders()
        assert all(o.side == Side.BUY for o in orders)

    def test_empty_when_no_ref_price(self, acc: Accumulator) -> None:
        assert acc.desired_orders() == []

    def test_tick_alignment(self, acc: Accumulator) -> None:
        acc.update_market(50000.03)  # ref with sub-tick precision
        orders = acc.desired_orders()
        for o in orders:
            # Price must be a multiple of tick_size
            assert round(o.price / 0.01, 6) == round(o.price / 0.01)


class TestRatchet:
    def test_ratchet_initialised_from_ref(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        acc.desired_orders()
        # ratchet = ref - start_offset = 50000 - 0.05 = 49999.95
        assert 49999.0 < acc.ratchet <= 50000.0

    def test_ratchet_moves_down_on_fill(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        acc.desired_orders()
        old_ratchet = acc.ratchet
        acc.on_fill(_make_order(49900.0), 1.0)
        assert acc.ratchet < old_ratchet  # moved down
        assert acc.ratchet == 49900.0

    def test_ratchet_does_not_move_up(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        acc.desired_orders()
        old_ratchet = acc.ratchet
        # Fill at a price equal to ratchet — stays
        acc.on_fill(_make_order(old_ratchet), 1.0)
        assert acc.ratchet == old_ratchet
        # Fill at a higher price (shouldn't happen in practice but be defensive)
        acc.on_fill(_make_order(old_ratchet + 10.0), 1.0)
        assert acc.ratchet == old_ratchet

    def test_entry_price_tracks_fills(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        acc.desired_orders()
        acc.on_fill(_make_order(49900.0, 1.0), 1.0)
        acc.on_fill(_make_order(49800.0, 2.0), 2.0)
        expected = (49900.0 * 1.0 + 49800.0 * 2.0) / 3.0
        assert acc.entry_price == expected

    def test_acceptance_ladder_does_not_move_upward(self, acc: Accumulator) -> None:
        """Core acceptance test: ref-spike case confirms ladder does not move up."""
        acc.update_market(50000.0)
        orders_before = acc.desired_orders()
        before = {o.price for o in orders_before}
        # Simulate a ref spike upward — ladder should NOT follow up
        acc.update_market(51000.0)
        orders_after = acc.desired_orders()
        after = {o.price for o in orders_after}
        # The ladder should be unchanged (ratchet didn't move up)
        assert before == after


class TestCollapseProtection:
    def test_suspend_when_ref_drops_below_lowest_rung(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        orders = acc.desired_orders()
        lowest = min(o.price for o in orders)
        # Drop 3% below lowest rung (threshold is 2%)
        crash_price = lowest * 0.96
        acc.update_market(crash_price)
        orders2 = acc.desired_orders()
        assert orders2 == []
        assert acc.suspended is True

    def test_recovery_after_price_comes_back(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        orders = acc.desired_orders()
        lowest = min(o.price for o in orders)
        # Trigger collapse
        crash_price = lowest * 0.96
        acc.update_market(crash_price)
        acc.desired_orders()
        assert acc.suspended is True
        # Price recovers above trigger + 1% hysteresis
        recovery_price = crash_price * 1.02
        acc.update_market(recovery_price)
        orders2 = acc.desired_orders()
        assert len(orders2) > 0
        assert acc.suspended is False

    def test_no_collapse_with_normal_movement(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        orders = acc.desired_orders()
        assert len(orders) > 0
        assert acc.suspended is False


class TestSpikeSuspension:
    def test_empty_orders_during_spike(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        orders_before = acc.desired_orders()
        assert len(orders_before) > 0
        # Spike active → no new orders
        acc.update_market(50000.0, spike_active=True)
        assert acc.desired_orders() == []

    def test_orders_resume_after_spike_clears(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        acc.desired_orders()
        acc.update_market(50000.0, spike_active=True)
        assert acc.desired_orders() == []
        acc.update_market(50000.0, spike_active=False)
        assert len(acc.desired_orders()) > 0

    def test_spike_suspension_configurable(self) -> None:
        acc2 = Accumulator(pair="BTC_USDT", suspend_on_spike=False)
        acc2.update_market(50000.0)
        acc2.update_market(50000.0, spike_active=True)
        assert len(acc2.desired_orders()) > 0


class TestActive:
    def test_active_initially(self, acc: Accumulator) -> None:
        assert acc.active is True

    def test_inactive_when_suspended(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        orders = acc.desired_orders()
        lowest = min(o.price for o in orders)
        acc.update_market(lowest * 0.96)
        acc.desired_orders()
        assert acc.active is False

    def test_active_after_recovery(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        orders = acc.desired_orders()
        lowest = min(o.price for o in orders)
        crash_price = lowest * 0.96
        acc.update_market(crash_price)
        acc.desired_orders()
        acc.update_market(crash_price * 1.02)
        acc.desired_orders()
        assert acc.active is True


class TestReset:
    def test_reset_clears_state(self, acc: Accumulator) -> None:
        acc.update_market(50000.0)
        acc.desired_orders()
        acc.on_fill(_make_order(49900.0), 1.0)
        acc.reset()
        assert acc.ratchet == 0.0
        assert acc.entry_price == 0.0
        assert acc.suspended is False
        assert acc.active is True
