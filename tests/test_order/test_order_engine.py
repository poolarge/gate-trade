"""Unit tests for LiveOrderEngine."""

from __future__ import annotations

import pytest

from gate_trade.guardrails.rate_limiter import RateLimiter
from gate_trade.order.order_engine import LiveOrderEngine
from gate_trade.types import OrderRequest, Side
from mocks import MockGateClient


@pytest.fixture
def client():
    return MockGateClient()


@pytest.fixture
def rl():
    return RateLimiter(burst=10, rate=100.0, max_wait_sec=1.0)


@pytest.fixture
def engine(client, rl):
    return LiveOrderEngine(client, rl, tick_size=0.01, min_base=0.1, min_quote=0.01)


class TestPlace:
    async def test_place_returns_order_with_id(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        order = await engine.place(req)
        assert order.order_id
        assert order.pair == "BTC_USDT"
        assert order.side == Side.BUY

    async def test_place_aligns_price_to_tick(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.017, size=0.01)
        order = await engine.place(req)
        assert order.price == 50000.02  # rounded to nearest tick

    async def test_place_tracks_open_order(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        order = await engine.place(req)
        assert len(engine.open_orders("BTC_USDT")) == 1
        assert engine.open_orders("BTC_USDT")[0].order_id == order.order_id

    async def test_place_rejects_invalid_price(self, engine):
        with pytest.raises(ValueError):
            await engine.place(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=0.0, size=0.01))

    async def test_place_rejects_invalid_size(self, engine):
        with pytest.raises(ValueError):
            await engine.place(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.0))

    async def test_place_records_call(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        await engine.place(req)
        assert len(engine.place_calls) == 1

    async def test_place_uses_client_order_id_when_provided(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01, client_order_id="my_custom_tag")
        order = await engine.place(req)
        assert engine.order_by_tag("my_custom_tag") is not None

    async def test_place_auto_generates_tag(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        order = await engine.place(req)
        assert order.client_order_id
        assert "BTC_USDT" in order.client_order_id


class TestCancel:
    async def test_cancel_removes_from_open(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        order = await engine.place(req)
        ok = await engine.cancel(order.order_id)
        assert ok is True
        assert engine.open_orders("BTC_USDT") == []

    async def test_cancel_unknown_returns_false(self, engine):
        ok = await engine.cancel("nonexistent")
        assert ok is False

    async def test_cancel_by_tag(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01, client_order_id="t1")
        order = await engine.place(req)
        ok = await engine.cancel_by_tag("t1")
        assert ok is True

    async def test_cancel_all(self, engine):
        await engine.place(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01))
        await engine.place(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=49900.0, size=0.01))
        await engine.place(OrderRequest(pair="ETH_USDT", side=Side.SELL, price=3000.0, size=0.1))
        count = await engine.cancel_all("BTC_USDT")
        assert count >= 1
        assert len(engine.open_orders("BTC_USDT")) == 0
        assert len(engine.open_orders("ETH_USDT")) == 1


class TestQuery:
    async def test_open_orders_empty_initially(self, engine):
        assert engine.open_orders() == []

    async def test_open_orders_filters_by_pair(self, engine):
        await engine.place(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01))
        await engine.place(OrderRequest(pair="ETH_USDT", side=Side.SELL, price=3000.0, size=0.1))
        assert len(engine.open_orders("BTC_USDT")) == 1
        assert len(engine.open_orders()) == 2

    def test_pending_count_returns_int(self, engine):
        assert engine.pending_count() == 0

    def test_rate_limiter_exposes_info(self, engine):
        rl = engine.rate_limiter
        assert rl.tokens >= 0
        assert rl.capacity > 0

    async def test_order_by_tag(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01, client_order_id="findme")
        await engine.place(req)
        found = engine.order_by_tag("findme")
        assert found is not None
        assert found.client_order_id == "findme"
        assert engine.order_by_tag("nonexistent") is None


class TestReconcile:
    async def test_reconcile_returns_empty_when_aligned(self, engine):
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        await engine.place(req)
        orphans = await engine.reconcile("BTC_USDT")
        assert orphans == set()

    async def test_reconcile_cleans_stale_orders(self, engine):
        # Place an order that the mock client won't return
        req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        order = await engine.place(req)
        # Manually remove from mock client's internal state
        await engine._client.cancel_order(order.order_id, "BTC_USDT")
        orphans = await engine.reconcile("BTC_USDT")
        assert orphans == set()
        assert engine.open_orders("BTC_USDT") == []

    async def test_reconcile_records_call(self, engine):
        await engine.reconcile("BTC_USDT")
        assert len(engine.reconcile_calls) == 1


class TestRateLimiting:
    async def test_many_places_within_burst(self, client, rl):
        engine = LiveOrderEngine(client, rl, tick_size=0.01)
        for i in range(10):
            req = OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0 + i, size=0.01)
            order = await engine.place(req)
            assert order.order_id
        assert len(engine.open_orders()) == 10

    async def test_rate_limiter_depletes_tokens(self, client):
        rl = RateLimiter(burst=5, rate=100.0, max_wait_sec=1.0)
        engine = LiveOrderEngine(client, rl, tick_size=0.01)
        for _ in range(5):
            await engine.place(OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01))
        assert engine.rate_limiter.tokens < 5
