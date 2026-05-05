"""Unit tests for LiveRiskManager — Phase 2.6."""

from __future__ import annotations

import time

import pytest

from gate_trade.risk.risk_manager import LiveRiskManager
from gate_trade.types import Balance, Order, OrderStatus, Side


def _buy_order(price: float, size: float = 1.0, filled: float = 0.0) -> Order:
    return Order(
        order_id="test", pair="BTC_USDT", side=Side.BUY,
        price=price, size=size, filled_size=filled, status=OrderStatus.OPEN,
    )


def _usdt_balance(amount: float) -> Balance:
    return Balance(currency="USDT", available=amount)


def _btc_balance(amount: float) -> Balance:
    return Balance(currency="BTC", available=amount)


@pytest.fixture
def rm() -> LiveRiskManager:
    return LiveRiskManager(
        max_position_notional=100.0,
        max_order_size_notional=50.0,
        max_open_orders=5,
        flash_crash_threshold_pct=5.0,
        hit_cap_cooldown_ms=5000,
    )


class TestPositionLimit:
    def test_position_below_limit(self, rm: LiveRiskManager) -> None:
        rm.evaluate([], [_btc_balance(1.0)], 50.0)  # 1 BTC * 50 = 50 notional
        assert rm.position_limit_breached is False
        assert rm.halted is False

    def test_position_above_limit_halt(self, rm: LiveRiskManager) -> None:
        rm.evaluate([], [_btc_balance(3.0)], 50.0)  # 3 * 50 = 150 > 100
        assert rm.position_limit_breached is True
        assert rm.halted is True
        assert rm.can_trade is False

    def test_pending_buys_counted_in_position(self, rm: LiveRiskManager) -> None:
        orders = [_buy_order(50000.0, size=1.0)]
        rm.evaluate(orders, [_btc_balance(1.0)], 50.0)  # (1+1) * 50 = 100 → not breached
        assert rm.position_limit_breached is False
        rm.evaluate(orders, [_btc_balance(1.0)], 51.0)  # (1+1) * 51 = 102 > 100
        assert rm.position_limit_breached is True

    def test_filled_size_excluded_from_pending(self, rm: LiveRiskManager) -> None:
        orders = [_buy_order(50000.0, size=1.0, filled=0.5)]
        rm.evaluate(orders, [_btc_balance(1.0)], 50.0)  # (1+0.5)*50 = 75
        assert rm.position_limit_breached is False

    def test_zero_price_skips_position_check(self, rm: LiveRiskManager) -> None:
        rm.evaluate([], [_btc_balance(100.0)], 0.0)
        assert rm.position_limit_breached is False


class TestOrderCountLimit:
    def test_order_count_below_limit(self, rm: LiveRiskManager) -> None:
        orders = [_buy_order(50000.0) for _ in range(4)]
        rm.evaluate(orders, [], 50000.0)
        assert rm.order_count_breached is False

    def test_order_count_at_limit_halt(self, rm: LiveRiskManager) -> None:
        orders = [_buy_order(50000.0) for _ in range(5)]
        rm.evaluate(orders, [], 50000.0)
        assert rm.order_count_breached is True
        assert rm.halted is True


class TestFlashCrash:
    def test_no_flash_crash_normal(self, rm: LiveRiskManager) -> None:
        rm.evaluate([], [], 50000.0)
        rm.evaluate([], [], 49000.0)  # 2% drop
        assert rm.flash_crash_detected is False

    def test_flash_crash_detected(self, rm: LiveRiskManager) -> None:
        rm.evaluate([], [], 50000.0)  # peak = 50000
        rm.evaluate([], [], 47000.0)  # 6% drop > 5%
        assert rm.flash_crash_detected is True
        assert rm.halted is True

    def test_peak_tracks_high(self, rm: LiveRiskManager) -> None:
        rm.evaluate([], [], 50000.0)
        rm.evaluate([], [], 52000.0)  # new peak
        rm.evaluate([], [], 49000.0)  # drop from 52000 → 5.7% > 5%
        assert rm.flash_crash_detected is True


class TestHaltResume:
    def test_resume_when_conditions_clear(self, rm: LiveRiskManager) -> None:
        rm.evaluate([], [_btc_balance(3.0)], 50.0)
        assert rm.halted is True
        # Conditions clear → halt clears, cap cooldown starts
        rm.evaluate([], [_btc_balance(1.0)], 50.0)
        assert rm.halted is False
        assert rm.cap_cooldown_remaining_ms > 0  # cooldown active

    def test_cap_cooldown_after_halt(self, rm: LiveRiskManager) -> None:
        rm.evaluate([], [_btc_balance(3.0)], 50.0)
        assert rm.halted is True
        # Clear → enters cap cooldown
        rm.evaluate([], [_btc_balance(1.0)], 50.0)
        assert rm.halted is False
        assert rm.can_trade is False  # cooldown active
        assert rm.cap_cooldown_remaining_ms > 0

    def test_cap_cooldown_expires(self, rm: LiveRiskManager) -> None:
        rm2 = LiveRiskManager(
            max_position_notional=100.0,
            hit_cap_cooldown_ms=1,
        )
        rm2.evaluate([], [_btc_balance(3.0)], 50.0)
        rm2.evaluate([], [_btc_balance(1.0)], 50.0)
        assert rm2.can_trade is False
        time.sleep(0.01)
        assert rm2.can_trade is True

    def test_no_cooldown_without_cap_breach(self, rm: LiveRiskManager) -> None:
        """Order count breach without position breach -> no cap cooldown."""
        # Use sell orders so position is not affected (only buys count)
        sell_orders = [
            Order(order_id="s", pair="BTC_USDT", side=Side.SELL,
                  price=50000.0, size=1.0, status=OrderStatus.OPEN)
            for _ in range(5)
        ]
        rm.evaluate(sell_orders, [], 50000.0)
        assert rm.order_count_breached is True
        assert rm.halted is True
        # Clear
        rm.evaluate([], [], 50000.0)
        assert rm.halted is False
        assert rm.can_trade is True  # no cap cooldown (position not breached)

    def test_acceptance_trigger_halt_resume(self, rm: LiveRiskManager) -> None:
        """Acceptance: manual trigger injection -> halt -> cooldown -> resume."""
        # Inject position breach
        rm.evaluate([], [_btc_balance(3.0)], 50.0)
        assert rm.halted is True
        assert rm.can_trade is False
        assert "position_limit" in rm.halt_reason
        # Clear → halt clears, enters cap cooldown
        rm.evaluate([], [_btc_balance(1.0)], 50.0)
        assert rm.halted is False
        assert rm.cap_cooldown_remaining_ms > 0  # cooldown active
        assert rm.can_trade is False  # cannot trade during cooldown


class TestReset:
    def test_reset_clears_all(self, rm: LiveRiskManager) -> None:
        rm.evaluate([], [_btc_balance(3.0)], 50.0)
        assert rm.halted is True
        rm.reset()
        assert rm.halted is False
        assert rm.position_limit_breached is False
        assert rm.can_trade is True
        assert rm.halt_reason == ""
