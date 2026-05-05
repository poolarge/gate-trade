"""Contract tests for RiskManager protocol."""

from __future__ import annotations

import pytest

from mocks.mock_risk_manager import MockRiskManager
from gate_trade.types import Balance, Order, OrderStatus, Side


@pytest.fixture
def rm():
    return MockRiskManager()


class TestRiskManagerContract:
    def test_can_trade_defaults_true(self, rm):
        assert rm.can_trade is True

    def test_halted_defaults_false(self, rm):
        assert rm.halted is False

    def test_set_can_trade(self, rm):
        rm.set_can_trade(False)
        assert rm.can_trade is False

    def test_set_halted(self, rm):
        rm.set_halted(True)
        assert rm.halted is True

    def test_position_limit_breached_defaults_false(self, rm):
        assert rm.position_limit_breached is False

    def test_order_count_breached_defaults_false(self, rm):
        assert rm.order_count_breached is False

    def test_flash_crash_detected_defaults_false(self, rm):
        assert rm.flash_crash_detected is False

    def test_set_flash_crash(self, rm):
        rm.set_flash_crash(True)
        assert rm.flash_crash_detected is True

    def test_should_resume_defaults_true(self, rm):
        assert rm.should_resume() is True

    def test_reset_clears_halt(self, rm):
        rm.set_halted(True)
        rm.set_can_trade(False)
        rm.reset()
        assert rm.halted is False
        assert rm.can_trade is True

    def test_evaluate_accepts_empty_lists(self, rm):
        rm.evaluate([], [], 50000.0)
        assert len(rm.eval_calls) == 1

    def test_evaluate_records_arguments(self, rm):
        orders = [Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)]
        balances = [Balance(currency="USDT", available=10000.0)]
        rm.evaluate(orders, balances, 50000.0)
        assert rm.eval_calls[0][2] == 50000.0
