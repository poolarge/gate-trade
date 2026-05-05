"""GateClient contract — exchange API wrapper."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from gate_trade.types import Balance, Order, OrderBook, OrderRequest


class GateClient(Protocol):
    """Async exchange API facade — REST + WebSocket.

    All methods are async. Implementations must handle auth, request
    signing, connection pooling, and WS lifecycle internally.
    """

    # ── REST: Orders ─────────────────────────────────────────

    async def submit_order(self, req: OrderRequest) -> Order:
        """Place a new limit (or market) order. Returns the exchange-confirmed Order."""
        ...

    async def cancel_order(self, order_id: str, pair: str) -> bool:
        """Cancel a single order by exchange ID. Returns True on success."""
        ...

    async def cancel_all_orders(self, pair: str) -> int:
        """Cancel all open orders for a pair. Returns count of cancelled orders."""
        ...

    async def fetch_open_orders(self, pair: str) -> list[Order]:
        """Return all currently open orders for a pair."""
        ...

    async def fetch_order(self, order_id: str, pair: str) -> Order:
        """Fetch a single order by exchange ID."""
        ...

    # ── REST: Account ────────────────────────────────────────

    async def fetch_balance(self, currency: str) -> Balance:
        """Return available + locked balance for a currency."""
        ...

    async def fetch_all_balances(self) -> list[Balance]:
        """Return all non-zero balances."""
        ...

    # ── WebSocket subscriptions ──────────────────────────────

    def subscribe_orderbook(
        self, pair: str, depth: int = 20, interval_ms: int = 100
    ) -> AsyncIterator[OrderBook]:
        """Yield incremental orderbook snapshots for *pair*."""
        ...

    def subscribe_orders(self, pair: str) -> AsyncIterator[list[Order]]:
        """Yield order-update batches (own orders) for *pair*."""
        ...

    def subscribe_balance(self) -> AsyncIterator[list[Balance]]:
        """Yield balance updates when available."""
        ...
