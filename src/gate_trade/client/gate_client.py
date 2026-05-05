"""GateClient implementation — REST + WebSocket exchange API facade."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import structlog
from gate_api import ApiClient, Configuration, SpotApi
from gate_api import Order as GateOrder
from gate_api.exceptions import ApiException as GateApiException

from gate_trade.client.contract import GateClient
from gate_trade.client.ws_manager import WsManager
from gate_trade.config.schema import AppConfig
from gate_trade.guardrails.exceptions import AuthError, ExchangeError, OrderNotFound
from gate_trade.types import (
    Balance,
    Order,
    OrderBook,
    OrderBookLevel,
    OrderRequest,
    OrderStatus,
    Side,
)

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class PairMeta:
    """Tradable pair metadata fetched from exchange."""

    pair: str
    base: str
    quote: str
    min_base_amount: str
    min_quote_amount: str
    amount_precision: int
    precision: int
    trade_status: str


class GateIoClient(GateClient):
    """Gate.io API v4 implementation.

    REST calls use the ``gate_api`` SDK (run in thread pool to avoid
    blocking the asyncio loop). WebSocket subscriptions use the
    internal ``WsManager``.
    """

    def __init__(self, config: AppConfig) -> None:
        self._cfg = config
        self._ws = WsManager(config.exchange.ws_url, config.ws)
        self._api_config = Configuration(
            host=config.exchange.base_url,
            key=config.exchange.api_key,
            secret=config.exchange.api_secret,
        )
        self._api_client = ApiClient(self._api_config)
        self._spot = SpotApi(self._api_client)

    @property
    def ws(self) -> WsManager:
        return self._ws

    # ── REST: Orders ─────────────────────────────────────────────

    async def submit_order(self, req: OrderRequest) -> Order:
        order = GateOrder(
            currency_pair=req.pair,
            side=req.side.value,
            amount=str(req.size),
            price=str(req.price),
            type="limit",
            time_in_force="gtc",
            text=req.client_order_id or "",
        )
        try:
            result = await asyncio.to_thread(
                self._spot.create_order, order
            )
        except GateApiException as exc:
            self._handle_api_error(exc, "submit_order", pair=req.pair)
        return self._from_gate_order(result)

    async def cancel_order(self, order_id: str, pair: str) -> bool:
        try:
            result = await asyncio.to_thread(
                self._spot.cancel_order, order_id, pair
            )
            return result.status == "cancelled"  # type: ignore[no-any-return]
        except GateApiException as exc:
            if exc.status == 404:
                return False
            self._handle_api_error(exc, "cancel_order", order_id=order_id, pair=pair)
            return False

    async def cancel_all_orders(self, pair: str) -> int:
        try:
            result = await asyncio.to_thread(
                self._spot.cancel_orders, pair, side=None, account="spot", action_mode=None
            )
            return len(result) if isinstance(result, list) else 1
        except GateApiException as exc:
            self._handle_api_error(exc, "cancel_all_orders", pair=pair)
        return 0

    async def fetch_open_orders(self, pair: str) -> list[Order]:
        try:
            result = await asyncio.to_thread(
                self._spot.list_orders, pair, status="open"
            )
            return [self._from_gate_order(o) for o in result]
        except GateApiException as exc:
            self._handle_api_error(exc, "fetch_open_orders", pair=pair)
        return []

    async def fetch_order(self, order_id: str, pair: str) -> Order:
        try:
            result = await asyncio.to_thread(
                self._spot.get_order, order_id, pair
            )
            return self._from_gate_order(result)
        except GateApiException as exc:
            if exc.status == 404:
                raise OrderNotFound(f"Order {order_id} ({pair}) not found") from exc
            self._handle_api_error(exc, "fetch_order", order_id=order_id, pair=pair)
            raise

    # ── REST: Account ────────────────────────────────────────────

    async def fetch_balance(self, currency: str) -> Balance:
        try:
            accounts = await asyncio.to_thread(self._spot.list_spot_accounts, currency)
        except GateApiException as exc:
            self._handle_api_error(exc, "fetch_balance", currency=currency)
        if accounts and len(accounts) > 0:
            acct = accounts[0]
            return Balance(
                currency=acct.currency,
                available=float(acct.available),
                locked=float(acct.locked),
            )
        return Balance(currency=currency, available=0.0)

    async def fetch_all_balances(self) -> list[Balance]:
        try:
            accounts = await asyncio.to_thread(self._spot.list_spot_accounts)
        except GateApiException as exc:
            self._handle_api_error(exc, "fetch_all_balances")
        balances: list[Balance] = []
        for acct in accounts:
            bal = Balance(
                currency=acct.currency,
                available=float(acct.available),
                locked=float(acct.locked),
            )
            if bal.total > 0:
                balances.append(bal)
        return balances

    # ── REST: Metadata ───────────────────────────────────────────

    async def fetch_pair_meta(self, pair: str) -> PairMeta:
        """Fetch tradable pair metadata from exchange."""
        try:
            result = await asyncio.to_thread(
                self._spot.get_currency_pair, pair
            )
        except GateApiException as exc:
            self._handle_api_error(exc, "fetch_pair_meta", pair=pair)
        return PairMeta(
            pair=result.id,
            base=result.base,
            quote=result.quote,
            min_base_amount=result.min_base_amount,
            min_quote_amount=result.min_quote_amount,
            amount_precision=int(result.amount_precision),
            precision=int(result.precision),
            trade_status=result.trade_status,
        )

    # ── WebSocket subscriptions ──────────────────────────────────

    async def subscribe_orderbook(
        self, pair: str, depth: int = 20, interval_ms: int = 100
    ) -> AsyncIterator[OrderBook]:
        topic = f"{pair}_{depth}_{interval_ms}ms"
        q = self._ws.subscribe("spot.order_book", topic)
        while True:
            msg = await q.get()
            try:
                yield self._parse_orderbook(msg, pair)
            except Exception:
                logger.exception("orderbook_parse_error", pair=pair)

    async def subscribe_orders(self, pair: str) -> AsyncIterator[list[Order]]:
        q = self._ws.subscribe("spot.orders", pair)
        while True:
            msg = await q.get()
            try:
                yield self._parse_orders(msg, pair)
            except Exception:
                logger.exception("orders_parse_error", pair=pair)

    async def subscribe_balance(self) -> AsyncIterator[list[Balance]]:
        q = self._ws.subscribe("spot.balances", "")
        while True:
            msg = await q.get()
            try:
                yield self._parse_balances(msg)
            except Exception:
                logger.exception("balances_parse_error")

    # ── Lifecycle ────────────────────────────────────────────────

    async def connect(self) -> None:
        await self._ws.connect()

    async def close(self) -> None:
        await self._ws.close()
        self._api_client.close()

    # ── Internal helpers ─────────────────────────────────────────

    @staticmethod
    def _from_gate_order(go: GateOrder) -> Order:
        """Convert gate_api Order → internal Order."""
        side = Side.BUY if go.side == "buy" else Side.SELL
        status_map: dict[str, OrderStatus] = {
            "open": OrderStatus.OPEN,
            "closed": OrderStatus.CLOSED,
            "cancelled": OrderStatus.CANCELLED,
        }
        return Order(
            order_id=str(go.id),
            pair=go.currency_pair,
            side=side,
            price=float(go.price),
            size=float(go.amount),
            filled_size=float(go.filled_total) if go.filled_total else 0.0,
            status=status_map.get(go.status, OrderStatus.OPEN),
            client_order_id=go.text or "",
            created_at_ms=int(go.create_time_ms) if go.create_time_ms else 0,
        )

    @staticmethod
    def _handle_api_error(exc: GateApiException, op: str, **ctx: object) -> None:
        extra = {"op": op, "status": exc.status, **ctx}
        if exc.status == 401 or exc.status == 403:
            logger.error("auth_error", **extra)
            raise AuthError(f"[{op}] authentication failed: {exc.body}") from exc
        if exc.status == 404:
            raise OrderNotFound(f"[{op}] resource not found") from exc
        if exc.status == 429:
            from gate_trade.guardrails.exceptions import RateLimitExceeded

            raise RateLimitExceeded(f"[{op}] exchange rate limit hit") from exc
        body_safe = str(exc.body)[:200]
        logger.error("exchange_error", body=body_safe, **extra)
        raise ExchangeError(f"[{op}] failed (HTTP {exc.status})") from exc

    # ── Parsers ──────────────────────────────────────────────────

    @staticmethod
    def _parse_orderbook(msg: dict[str, Any], pair: str) -> OrderBook:
        result = msg.get("result", msg)
        bids = [
            OrderBookLevel(price=float(b[0]), size=float(b[1]))
            for b in result.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=float(a[0]), size=float(a[1]))
            for a in result.get("asks", [])
        ]
        ts = int(result.get("t", 0))
        return OrderBook(bids=bids, asks=asks, timestamp_ms=ts)

    @staticmethod
    def _parse_orders(msg: dict[str, Any], pair: str) -> list[Order]:
        result = msg.get("result", msg)
        orders: list[Order] = []
        for raw in result if isinstance(result, list) else [result]:
            orders.append(Order(
                order_id=str(raw.get("id", "")),
                pair=pair,
                side=Side(raw.get("side", "buy")),
                price=float(raw.get("price", 0)),
                size=float(raw.get("amount", 0)),
                filled_size=float(raw.get("filled_total", 0)),
                status=OrderStatus(raw.get("status", "open")),
                client_order_id=raw.get("text", ""),
                created_at_ms=int(float(raw.get("create_time_ms", 0))),
            ))
        return orders

    @staticmethod
    def _parse_balances(msg: dict[str, Any]) -> list[Balance]:
        result = msg.get("result", msg)
        balances: list[Balance] = []
        for raw in result if isinstance(result, list) else [result]:
            bal = Balance(
                currency=str(raw.get("currency", "")),
                available=float(raw.get("available", 0)),
                locked=float(raw.get("locked", 0)),
            )
            if bal.total > 0:
                balances.append(bal)
        return balances
