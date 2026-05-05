"""Contract tests for GateClient protocol."""

from __future__ import annotations

import pytest

from gate_trade.types import OrderRequest, Side
from mocks import MockGateClient


@pytest.fixture
def client():
    return MockGateClient()


class TestGateClientContract:
    """Every GateClient implementation must pass these."""

    async def test_submit_order_returns_order_with_id(self, client):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        order = await client.submit_order(req)
        assert order.order_id
        assert order.pair == req.pair
        assert order.side == req.side

    async def test_submit_order_is_recorded(self, client):
        req = OrderRequest(pair="BTC_USDT", side=Side.SELL, price=51000.0, size=0.01)
        await client.submit_order(req)
        assert len(client.submit_calls) == 1

    async def test_cancel_order_returns_true_for_known_order(self, client):
        req = OrderRequest(pair="ETH_USDT", side=Side.BUY, price=3000.0, size=0.1)
        order = await client.submit_order(req)
        result = await client.cancel_order(order.order_id, "ETH_USDT")
        assert result is True

    async def test_cancel_order_returns_false_for_unknown(self, client):
        result = await client.cancel_order("nonexistent", "BTC_USDT")
        assert result is False

    async def test_cancel_all_orders_returns_count(self, client):
        await client.submit_order(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01))
        await client.submit_order(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=49900.0, size=0.01))
        await client.submit_order(OrderRequest(pair="ETH_USDT", side=Side.SELL, price=3100.0, size=0.1))
        count = await client.cancel_all_orders("BTC_USDT")
        assert count == 2

    async def test_fetch_open_orders_filters_by_pair(self, client):
        await client.submit_order(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01))
        await client.submit_order(OrderRequest(pair="ETH_USDT", side=Side.SELL, price=3100.0, size=0.1))
        btc_orders = await client.fetch_open_orders("BTC_USDT")
        assert len(btc_orders) == 1
        assert btc_orders[0].pair == "BTC_USDT"

    async def test_fetch_order_returns_correct_order(self, client):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        created = await client.submit_order(req)
        fetched = await client.fetch_order(created.order_id, "BTC_USDT")
        assert fetched.order_id == created.order_id
        assert fetched.price == req.price

    async def test_fetch_balance_returns_default_for_unknown_currency(self, client):
        bal = await client.fetch_balance("XYZ")
        assert bal.currency == "XYZ"
        assert bal.available == 0.0

    async def test_fetch_all_balances_reflects_set_balances(self, client):
        client.set_balance("USDT", 10000.0)
        client.set_balance("BTC", 0.5, locked=0.1)
        balances = await client.fetch_all_balances()
        assert len(balances) == 2
