"""OrderEngine contract — order lifecycle with rate limiting."""

from __future__ import annotations

from typing import Protocol

from gate_trade.types import Order, OrderRequest


class RateLimiterInfo(Protocol):
    """Read-only snapshot of token-bucket state."""

    @property
    def tokens(self) -> float: ...

    @property
    def capacity(self) -> float: ...


class OrderEngine(Protocol):
    """Creates, tracks, and cancels orders while respecting rate limits.

    Tag-based reconciliation: every order carries a client_order_id
    tag so the engine can match exchange state to internal state even
    after a reconnect.
    """

    # ── Lifecycle ────────────────────────────────────────────

    async def place(self, req: OrderRequest, ref_price: float = 0.0) -> Order:
        """Submit *req* through rate limiter. Raises RateLimitExceeded if
        the token bucket is empty and max wait time has elapsed.

        *ref_price* enables price boundary protection (±20% guard)."""
        ...

    async def cancel(self, order_id: str) -> bool:
        """Cancel an order. Returns True if the exchange confirmed cancellation."""
        ...

    async def cancel_all(self, pair: str) -> int:
        """Cancel every tracked open order for *pair*. Returns count."""
        ...

    # ── Query ────────────────────────────────────────────────

    def open_orders(self, pair: str | None = None) -> list[Order]:
        """Snapshot of currently-open orders (tracked locally)."""
        ...

    def pending_count(self, pair: str | None = None) -> int:
        """Number of orders currently in-flight (not yet confirmed)."""
        ...

    # ── Reconciliation ───────────────────────────────────────

    async def reconcile(self, pair: str) -> set[str]:
        """Fetch exchange state, diff against local state, and return
        the set of client_order_id tags for orders that were unknown
        locally (orphaned on exchange)."""
        ...

    # ── Rate limiter ─────────────────────────────────────────

    @property
    def rate_limiter(self) -> RateLimiterInfo:
        """Expose token-bucket state for monitoring."""
        ...
