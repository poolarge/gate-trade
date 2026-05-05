"""Contract tests for Strategy protocol."""

from __future__ import annotations

import pytest

from gate_trade.types import Order, OrderRequest, Side
from mocks.mock_strategy import MockStrategy


@pytest.fixture
def strategy():
    return MockStrategy(name="test_strat")


class TestStrategyContract:
    def test_name_property(self, strategy):
        assert strategy.name == "test_strat"

    def test_active_defaults_true(self, strategy):
        assert strategy.active is True

    def test_desired_orders_empty_initially(self, strategy):
        assert strategy.desired_orders() == []

    def test_set_orders_returns_copy(self, strategy):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        strategy.set_orders([req])
        result = strategy.desired_orders()
        assert len(result) == 1
        assert result[0].price == 50000.0

    def test_on_fill_records_event(self, strategy):
        order = Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        strategy.on_fill(order, 0.005)
        assert len(strategy.fill_events) == 1
        assert strategy.fill_events[0][1] == 0.005

    def test_on_state_change_records_event(self, strategy):
        strategy.on_state_change("IDLE", "RUNNING")
        assert len(strategy.state_change_events) == 1
        assert strategy.state_change_events[0] == ("IDLE", "RUNNING")

    def test_on_cancel_records_event(self, strategy):
        order = Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        strategy.on_cancel(order)
        assert len(strategy.cancel_events) == 1

    def test_inactive_returns_true_when_set(self, strategy):
        strategy.set_active(False)
        assert strategy.active is False

    def test_desired_orders_returns_list(self, strategy):
        result = strategy.desired_orders()
        assert isinstance(result, list)
