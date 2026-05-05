"""Contract tests for OrderEngine protocol."""

from __future__ import annotations

import pytest

from mocks.mock_order_engine import MockOrderEngine
from gate_trade.types import OrderRequest, Side


@pytest.fixture
def engine():
    return MockOrderEngine()


class TestOrderEngineContract:
    async def test_place_returns_order_with_id(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        order = await engine.place(req)
        assert order.order_id
        assert order.pair == "BTC_USDT"

    async def test_place_records_call(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.SELL, price=51000.0, size=0.01)
        await engine.place(req)
        assert len(engine.place_calls) == 1
        assert engine.place_calls[0].price == 51000.0

    async def test_cancel_known_order_returns_true(self, engine):
        req = OrderRequest(pair="ETH_USDT", side=Side.BUY, price=3000.0, size=0.1)
        order = await engine.place(req)
        result = await engine.cancel(order.order_id)
        assert result is True

    async def test_cancel_unknown_order_returns_false(self, engine):
        result = await engine.cancel("nonexistent")
        assert result is False

    async def test_cancel_all_returns_count(self, engine):
        await engine.place(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01))
        await engine.place(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=49900.0, size=0.01))
        await engine.place(OrderRequest(pair="ETH_USDT", side=Side.SELL, price=3100.0, size=0.1))
        count = await engine.cancel_all("BTC_USDT")
        assert count == 2

    async def test_open_orders_filters_by_pair(self, engine):
        await engine.place(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01))
        await engine.place(OrderRequest(pair="ETH_USDT", side=Side.SELL, price=3100.0, size=0.1))
        btc = engine.open_orders("BTC_USDT")
        assert len(btc) == 1
        assert btc[0].pair == "BTC_USDT"
        all_orders = engine.open_orders()
        assert len(all_orders) == 2

    def test_open_orders_empty_initially(self, engine):
        assert engine.open_orders() == []

    def test_pending_count_returns_int(self, engine):
        assert isinstance(engine.pending_count(), int)

    async def test_reconcile_returns_empty_set_for_mock(self, engine):
        result = await engine.reconcile("BTC_USDT")
        assert result == set()

    def test_rate_limiter_exposes_tokens_and_capacity(self, engine):
        rl = engine.rate_limiter
        assert rl.tokens >= 0
        assert rl.capacity > 0

    async def test_client_order_id_preserved(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01, client_order_id="my_tag_001")
        order = await engine.place(req)
        assert order.client_order_id == "my_tag_001"
