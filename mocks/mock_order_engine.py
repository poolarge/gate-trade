"""Mock OrderEngine — records calls, returns canned orders."""

from __future__ import annotations

from gate_trade.order.contract import OrderEngine, RateLimiterInfo
from gate_trade.types import Order, OrderRequest


class _MockRateLimiterInfo(RateLimiterInfo):
    def __init__(self) -> None:
        self._tokens = 10.0
        self._capacity = 10.0

    @property
    def tokens(self) -> float:
        return self._tokens

    @property
    def capacity(self) -> float:
        return self._capacity


class MockOrderEngine(OrderEngine):
    """Records all calls and returns canned orders for testing."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._next_id = 1
        self._rl = _MockRateLimiterInfo()
        self.place_calls: list[OrderRequest] = []
        self.cancel_calls: list[str] = []
        self.cancel_all_calls: list[str] = []
        self.reconcile_calls: list[str] = []

    async def place(self, req: OrderRequest) -> Order:
        self.place_calls.append(req)
        oid = str(self._next_id)
        self._next_id += 1
        order = Order(
            order_id=oid,
            pair=req.pair,
            side=req.side,
            price=req.price,
            size=req.size,
            client_order_id=req.client_order_id or "",
        )
        self._orders[oid] = order
        return order

    async def cancel(self, order_id: str) -> bool:
        self.cancel_calls.append(order_id)
        return self._orders.pop(order_id, None) is not None

    async def cancel_all(self, pair: str) -> int:
        self.cancel_all_calls.append(pair)
        to_remove = [oid for oid, o in self._orders.items() if o.pair == pair]
        for oid in to_remove:
            del self._orders[oid]
        return len(to_remove)

    def open_orders(self, pair: str | None = None) -> list[Order]:
        orders = list(self._orders.values())
        if pair is not None:
            orders = [o for o in orders if o.pair == pair]
        return orders

    def pending_count(self, pair: str | None = None) -> int:
        return 0

    async def reconcile(self, pair: str) -> set[str]:
        self.reconcile_calls.append(pair)
        return set()

    @property
    def rate_limiter(self) -> RateLimiterInfo:
        return self._rl
