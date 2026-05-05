"""OrderEngine — rate-limited order placement, cancellation, and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from gate_trade.client.contract import GateClient
from gate_trade.guardrails.exceptions import ExchangeError
from gate_trade.guardrails.rate_limiter import RateLimiter, RateLimitExceeded
from gate_trade.order.contract import OrderEngine, RateLimiterInfo
from gate_trade.types import Order, OrderRequest, OrderType, Side

logger = structlog.get_logger(__name__)

_TAG_PREFIX = "gt"


@dataclass
class _Pending:
    """An order that has been submitted but not yet confirmed by WS."""

    client_order_id: str
    pair: str
    side: Side
    price: float
    size: float


class LiveOrderEngine(OrderEngine):
    """Concrete order engine: rate-limited placement, tag-based tracking,
    and exchange reconciliation.

    Tick alignment
        Prices are rounded to the nearest *tick_size* before submission.

    Tags
        Every order is tagged with ``gt:<pair>:<nonce>`` so the engine
        can match exchange state to internal state after reconnects.
    """

    def __init__(
        self,
        client: GateClient,
        rate_limiter: RateLimiter,
        tick_size: float = 0.01,
        min_base: float = 1.0,
        min_quote: float = 0.01,
    ) -> None:
        self._client = client
        self._rl = rate_limiter
        self._tick = tick_size
        self._min_base = min_base
        self._min_quote = min_quote

        # Local tracking
        self._open: dict[str, Order] = {}           # order_id → Order
        self._by_tag: dict[str, str] = {}           # client_order_id → order_id
        self._pending: dict[str, _Pending] = {}     # client_order_id → Pending
        self._nonce: int = 0

        # Call recording for testing
        self.place_calls: list[OrderRequest] = []
        self.cancel_calls: list[str] = []
        self.cancel_all_calls: list[str] = []
        self.reconcile_calls: list[str] = []

    # ── Lifecycle ────────────────────────────────────────────────

    async def place(self, req: OrderRequest, ref_price: float = 0.0) -> Order:
        """Submit *req* through rate limiter and tick alignment."""
        self.place_calls.append(req)

        # Validate
        self._validate(req, ref_price)

        # Align price to tick
        aligned = self._align_price(req.price)
        aligned_size = self._align_size(req.size)

        # Client order ID for tag-based tracking
        tag = req.client_order_id or self._next_tag(req.pair)

        aligned_req = OrderRequest(
            pair=req.pair,
            side=req.side,
            price=aligned,
            size=aligned_size,
            order_type=OrderType.LIMIT,
            client_order_id=tag,
        )

        # Rate limit — skip this placement if token bucket is exhausted
        if not await self._rl.acquire():
            logger.warning("rate_limit_skip", pair=req.pair, side=req.side.value)
            raise RateLimitExceeded(
                f"Token bucket exhausted after {self._rl._max_wait:.1f}s — skipping placement"
            )

        # Track as pending
        self._pending[tag] = _Pending(
            client_order_id=tag,
            pair=req.pair,
            side=req.side,
            price=aligned,
            size=aligned_size,
        )

        # Submit
        try:
            order = await self._client.submit_order(aligned_req)
        except ExchangeError:
            self._pending.pop(tag, None)
            raise

        # Confirm
        self._pending.pop(tag, None)
        self._open[order.order_id] = order
        self._by_tag[order.client_order_id] = order.order_id
        logger.info("order_placed", order_id=order.order_id, tag=tag,
                     pair=req.pair, side=req.side.value, price=aligned)
        return order

    async def cancel(self, order_id: str) -> bool:
        """Cancel by exchange order ID."""
        self.cancel_calls.append(order_id)
        order = self._open.get(order_id)
        if order is None:
            return False

        try:
            ok = await self._client.cancel_order(order_id, order.pair)
        except ExchangeError:
            return False

        if ok:
            self._open.pop(order_id, None)
            if order.client_order_id:
                self._by_tag.pop(order.client_order_id, None)
            logger.info("order_cancelled", order_id=order_id)
        return ok

    async def cancel_by_tag(self, tag: str) -> bool:
        """Cancel an order by its client_order_id tag."""
        order_id = self._by_tag.get(tag)
        if order_id is None:
            return False
        return await self.cancel(order_id)

    async def cancel_all(self, pair: str) -> int:
        """Cancel all tracked orders for a pair."""
        self.cancel_all_calls.append(pair)
        oids = [oid for oid, o in self._open.items() if o.pair == pair]
        if not oids:
            return 0

        try:
            count = await self._client.cancel_all_orders(pair)
        except ExchangeError:
            return 0

        for oid in oids:
            order = self._open.pop(oid, None)
            if order and order.client_order_id:
                self._by_tag.pop(order.client_order_id, None)

        logger.info("all_cancelled", pair=pair, count=count)
        return count

    # ── Query ───────────────────────────────────────────────────

    def open_orders(self, pair: str | None = None) -> list[Order]:
        orders = list(self._open.values())
        if pair is not None:
            orders = [o for o in orders if o.pair == pair]
        return orders

    def pending_count(self, pair: str | None = None) -> int:
        if pair is not None:
            return sum(1 for p in self._pending.values() if p.pair == pair)
        return len(self._pending)

    def order_by_tag(self, tag: str) -> Order | None:
        """Look up a tracked order by client_order_id."""
        order_id = self._by_tag.get(tag)
        return self._open.get(order_id) if order_id else None

    # ── Reconciliation ──────────────────────────────────────────

    async def reconcile(self, pair: str) -> set[str]:
        """Fetch exchange open orders and diff against local state.

        Returns client_order_id tags for orders that exist on exchange
        but not locally (orphans that should be cancelled).
        """
        self.reconcile_calls.append(pair)

        try:
            exchange_orders = await self._client.fetch_open_orders(pair)
        except ExchangeError:
            logger.exception("reconcile_fetch_failed", pair=pair)
            return set()

        exchange_ids = {o.order_id for o in exchange_orders}
        local_ids = {o.order_id for o in self._open.values() if o.pair == pair}

        # Orphans: on exchange but not in local tracking
        orphans = exchange_ids - local_ids

        # Stale: in local tracking but not on exchange
        stale = local_ids - exchange_ids
        for oid in stale:
            order = self._open.pop(oid, None)
            if order and order.client_order_id:
                self._by_tag.pop(order.client_order_id, None)

        # Update local state with exchange data
        for xo in exchange_orders:
            self._open[xo.order_id] = xo
            if xo.client_order_id:
                self._by_tag[xo.client_order_id] = xo.order_id

        if orphans:
            logger.warning("reconcile_orphans", pair=pair, count=len(orphans))
        if stale:
            logger.info("reconcile_stale_removed", pair=pair, count=len(stale))

        # Return orphan tags so caller can cancel them
        orphan_tags: set[str] = set()
        for xo in exchange_orders:
            if xo.order_id in orphans and xo.client_order_id:
                orphan_tags.add(xo.client_order_id)
        return orphan_tags

    # ── Rate limiter ────────────────────────────────────────────

    @property
    def rate_limiter(self) -> RateLimiterInfo:
        return _RateLimiterInfoProxy(self._rl)

    # ── Internal: tick alignment ─────────────────────────────────

    def _align_price(self, price: float) -> float:
        tick = self._tick
        return round(round(price / tick) * tick, 8)

    def _align_size(self, size: float) -> float:
        # Truncate to 6 decimal places (typical base precision)
        return round(size, 6)

    # ── Internal: validation ────────────────────────────────────

    def _validate(self, req: OrderRequest, ref_price: float = 0.0) -> None:
        if req.price <= 0:
            raise ValueError(f"Invalid price: {req.price}")
        if req.size <= 0:
            raise ValueError(f"Invalid size: {req.size}")
        if self._align_price(req.price) != req.price:
            logger.debug("price_misaligned", requested=req.price,
                         aligned=self._align_price(req.price))

        # Price boundary protection (±20% from reference price)
        if ref_price > 0.0:
            max_price = ref_price * 1.20
            min_price = ref_price * 0.80
            if req.price > max_price:
                raise ValueError(
                    f"Price {req.price} above max {max_price:.2f} (ref={ref_price:.2f})"
                )
            if req.price < min_price:
                raise ValueError(
                    f"Price {req.price} below min {min_price:.2f} (ref={ref_price:.2f})"
                )

    # ── Internal: tags ──────────────────────────────────────────

    def _next_tag(self, pair: str) -> str:
        self._nonce += 1
        return f"{_TAG_PREFIX}:{pair}:{self._nonce}"


class _RateLimiterInfoProxy(RateLimiterInfo):
    """Read-only view of the token bucket for monitoring."""

    __slots__ = ("_rl",)

    def __init__(self, rl: RateLimiter) -> None:
        self._rl = rl

    @property
    def tokens(self) -> float:
        return self._rl.available

    @property
    def capacity(self) -> float:
        return self._rl.capacity
