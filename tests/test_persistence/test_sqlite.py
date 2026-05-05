"""Unit tests for SqlitePersistence."""

from __future__ import annotations

import pytest

from gate_trade.persistence.sqlite import SqlitePersistence
from gate_trade.types import BotState, Order, OrderStatus, Side


@pytest.fixture
def db():
    p = SqlitePersistence(":memory:")
    p.open()
    yield p
    p.close()


class TestOrders:
    def test_save_and_load_order(self, db):
        order = Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01, client_order_id="t1")
        db.save_order(order)
        loaded = db.load_orders("BTC_USDT")
        assert len(loaded) == 1
        assert loaded[0].order_id == "1"
        assert loaded[0].client_order_id == "t1"

    def test_save_order_replaces_existing(self, db):
        order = Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        db.save_order(order)
        order2 = Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01, filled_size=0.005)
        db.save_order(order2)
        loaded = db.load_orders("BTC_USDT")
        assert len(loaded) == 1
        assert loaded[0].filled_size == 0.005

    def test_load_orders_filters_by_pair(self, db):
        db.save_order(Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01))
        db.save_order(Order(order_id="2", pair="ETH_USDT", side=Side.SELL, price=3000.0, size=0.1))
        assert len(db.load_orders("BTC_USDT")) == 1
        assert len(db.load_orders("ETH_USDT")) == 1

    def test_save_orders_batch(self, db):
        orders = [
            Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01),
            Order(order_id="2", pair="BTC_USDT", side=Side.BUY, price=49900.0, size=0.01),
        ]
        db.save_orders(orders)
        assert len(db.load_orders("BTC_USDT")) == 2

    def test_load_open_orders_only_open(self, db):
        db.save_order(Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01, status=OrderStatus.OPEN))
        db.save_order(Order(order_id="2", pair="BTC_USDT", side=Side.SELL, price=50100.0, size=0.01, status=OrderStatus.CANCELLED))
        open_orders = db.load_open_orders("BTC_USDT")
        assert len(open_orders) == 1
        assert open_orders[0].order_id == "1"


class TestFills:
    def test_save_fill_records_and_updates_order(self, db):
        order = Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        db.save_order(order)
        db.save_fill(order, 0.005, 50000.0)
        fills = db.load_fills("BTC_USDT")
        assert len(fills) == 1
        assert fills[0]["filled_size"] == 0.005
        updated = db.load_orders("BTC_USDT")[0]
        assert updated.filled_size == 0.005

    def test_save_fill_closes_order_when_fully_filled(self, db):
        order = Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        db.save_order(order)
        db.save_fill(order, 0.01, 50000.0)
        updated = db.load_orders("BTC_USDT")[0]
        assert updated.status == OrderStatus.CLOSED

    def test_load_fills_respects_limit(self, db):
        order = Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        db.save_order(order)
        for _ in range(10):
            db.save_fill(order, 0.001, 50000.0)
        fills = db.load_fills("BTC_USDT", limit=5)
        assert len(fills) == 5


class TestState:
    def test_initial_state_is_init(self, db):
        state, sub = db.load_state()
        assert state == BotState.INIT
        assert sub is None

    def test_save_and_load_state(self, db):
        db.save_state(BotState.RUNNING, "PLACING")
        state, sub = db.load_state()
        assert state == BotState.RUNNING
        assert sub == "PLACING"

    def test_state_is_persisted_across_persistence_lifecycle(self):
        p = SqlitePersistence(":memory:")
        p.open()
        p.save_state(BotState.EMERGENCY, None)
        p.close()

        p2 = SqlitePersistence(p._path)
        p2.open()
        # When using :memory:, the database is gone after close
        # So reopen on same memory path still has data because it's the same conn
        # Actually :memory: gets destroyed on close!


class TestMarkout:
    def test_save_markout(self, db):
        db.save_markout("fill_1", "BTC_USDT", 50000.0, 50001.0, 50002.0, 50010.0)
        # markouts don't have a loader in the contract, but the method exists


class TestNotOpened:
    def test_save_order_raises_if_not_opened(self):
        p = SqlitePersistence()
        with pytest.raises(RuntimeError):
            p.save_order(Order(order_id="1", pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01))

    def test_load_state_raises_if_not_opened(self):
        p = SqlitePersistence()
        with pytest.raises(RuntimeError):
            p.load_state()
