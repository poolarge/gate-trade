"""Mock GateClient — in-memory exchange simulator for testing."""

from __future__ import annotations

from collections.abc import AsyncIterator

from gate_trade.client.contract import GateClient
from gate_trade.types import Balance, Order, OrderBook, OrderRequest


class MockGateClient(GateClient):
    """In-memory GateClient that records calls and returns canned responses."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._balances: dict[str, Balance] = {}
        self._next_id = 1
        self.submit_calls: list[OrderRequest] = []
        self.cancel_calls: list[tuple[str, str]] = []

    # ── REST: Orders ─────────────────────────────────────────

    async def submit_order(self, req: OrderRequest) -> Order:
        self.submit_calls.append(req)
        oid = str(self._next_id)
        self._next_id += 1
        order = Order(
            order_id=oid,
            pair=req.pair,
            side=req.side,
            price=req.price,
            size=req.size,
            client_order_id=req.client_order_id,
        )
        self._orders[oid] = order
        return order

    async def cancel_order(self, order_id: str, pair: str) -> bool:
        self.cancel_calls.append((order_id, pair))
        return self._orders.pop(order_id, None) is not None

    async def cancel_all_orders(self, pair: str) -> int:
        to_remove = [oid for oid, o in self._orders.items() if o.pair == pair]
        for oid in to_remove:
            del self._orders[oid]
        return len(to_remove)

    async def fetch_open_orders(self, pair: str) -> list[Order]:
        return [o for o in self._orders.values() if o.pair == pair]

    async def fetch_order(self, order_id: str, pair: str) -> Order:
        o = self._orders.get(order_id)
        if o is None:
            raise ValueError(f"Order {order_id} not found")
        return o

    # ── REST: Account ────────────────────────────────────────

    async def fetch_balance(self, currency: str) -> Balance:
        return self._balances.get(currency, Balance(currency=currency, available=0.0))

    async def fetch_all_balances(self) -> list[Balance]:
        return list(self._balances.values())

    # ── WebSocket (sync stubs return empty) ───────────────────

    async def subscribe_orderbook(
        self, pair: str, depth: int = 20, interval_ms: int = 100
    ) -> AsyncIterator[OrderBook]:
        if False:
            yield OrderBook()

    async def subscribe_orders(self, pair: str) -> AsyncIterator[list[Order]]:
        if False:
            yield []

    async def subscribe_balance(self) -> AsyncIterator[list[Balance]]:
        if False:
            yield []

    # ── Test helpers ─────────────────────────────────────────

    def set_balance(self, currency: str, available: float, locked: float = 0.0) -> None:
        self._balances[currency] = Balance(currency=currency, available=available, locked=locked)
