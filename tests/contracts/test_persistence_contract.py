"""Contract tests for Persistence protocol."""

from __future__ import annotations

import pytest

from gate_trade.types import BotState, Order, OrderStatus, Side
from mocks.mock_persistence import MockPersistence


@pytest.fixture
def p():
    return MockPersistence()


class TestPersistenceContract:
    def test_initial_state_is_init(self, p):
        state, sub = p.load_state()
        assert state == BotState.INIT
        assert sub is None

    def test_save_and_load_state(self, p):
        p.save_state(BotState.RUNNING, "PLACING")
        state, sub = p.load_state()
        assert state == BotState.RUNNING
        assert sub == "PLACING"

    def test_save_and_load_order(self, p):
        order = Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        p.save_order(order)
        loaded = p.load_orders("BTC_USDT")
        assert len(loaded) == 1
        assert loaded[0].order_id == "1"

    def test_load_orders_filters_by_pair(self, p):
        p.save_order(Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01))
        p.save_order(Order(order_id="2", pair="ETH_USDT", side=Side.SELL, price=3000.0, size=0.1))
        assert len(p.load_orders("BTC_USDT")) == 1
        assert len(p.load_orders("ETH_USDT")) == 1

    def test_save_orders_batch(self, p):
        orders = [
            Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01),
            Order(order_id="2", pair="BTC_USDT", side=Side.BUY, price=49900.0, size=0.01),
        ]
        p.save_orders(orders)
        assert len(p.load_orders("BTC_USDT")) == 2

    def test_load_open_orders_only_returns_open(self, p):
        p.save_order(Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01, status=OrderStatus.OPEN))
        p.save_order(Order(order_id="2", pair="BTC_USDT", side=Side.BUY, price=49900.0, size=0.01, status=OrderStatus.CANCELLED))
        open_orders = p.load_open_orders("BTC_USDT")
        assert len(open_orders) == 1
        assert open_orders[0].order_id == "1"

    def test_save_fill_is_recorded(self, p):
        order = Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        p.save_fill(order, 0.005, 50000.0)
        fills = p.load_fills("BTC_USDT")
        assert len(fills) == 1
        assert fills[0]["filled_size"] == 0.005

    def test_save_markout_is_recorded(self, p):
        p.save_markout("fill_1", "BTC_USDT", 50000.0, 50001.0, 50002.0, 50010.0)
        assert len(p._markouts) == 1

    def test_open_and_close(self, p):
        p.open()
        p.close()
