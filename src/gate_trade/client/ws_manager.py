"""WebSocket connection manager with auto-reconnect and message dispatch."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from gate_trade.config.schema import WsConfig
from gate_trade.guardrails.exceptions import ExchangeError

logger = structlog.get_logger()


class WsManager:
    """Manages a single WebSocket connection with automatic reconnect.

    Incoming messages are dispatched to registered *handlers* by channel/topic.

    Dispatch uses a three-tier match:
      1. Exact:  ``{channel}:{result.s}``  (pair-scoped, e.g. spot.order_book:BTC_USDT)
      2. Event:  ``{channel}:{event}``     (event-scoped, e.g. spot.order_book:update)
      3. Prefix: ``{channel}``             (channel-wide broadcast)
    """

    def __init__(self, url: str, config: WsConfig) -> None:
        self._url = url
        self._cfg = config
        self._conn: ClientConnection | None = None
        self._running = False
        self._handlers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._subscriptions: set[str] = set()

        # Background tasks
        self._conn_task: asyncio.Task[None] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._ping_task: asyncio.Task[None] | None = None

    # ── public ──────────────────────────────────────────────────

    async def connect(self) -> None:
        """Start the connection background task (non-blocking).

        The caller must await the returned coroutine, but it returns
        immediately after spawning the reconnect loop in a background task.
        """
        self._running = True
        self._conn_task = asyncio.create_task(self._reconnect())

    async def close(self) -> None:
        """Gracefully close the connection and cancel background tasks."""
        self._running = False
        for task in (self._conn_task, self._reader_task, self._ping_task):
            if task and not task.done():
                task.cancel()
                with __import__("contextlib").suppress(asyncio.CancelledError):
                    await task
        if self._conn:
            await self._conn.close()
            self._conn = None
        self._conn_task = None
        self._reader_task = None
        self._ping_task = None

    def subscribe(self, channel: str, topic: str, queue_size: int = 256) -> asyncio.Queue[dict[str, Any]]:
        """Register interest in a channel+topic. Returns an async queue of messages.

        *topic* should be a pair identifier (e.g. ``"BTC_USDT"``) or
        a topic string (e.g. ``"BTC_USDT_20_100ms"``).
        """
        key = f"{channel}:{topic}"
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
        self._handlers.setdefault(key, []).append(q)
        self._subscriptions.add(key)
        return q

    async def send(self, message: dict[str, Any]) -> None:
        """Send a JSON message on the active connection."""
        if self._conn is None:
            raise ExchangeError("WebSocket not connected")
        payload = json.dumps(message)
        await self._conn.send(payload)

    @property
    def connected(self) -> bool:
        return self._conn is not None

    # ── internal: reconnect loop ─────────────────────────────────

    async def _reconnect(self) -> None:
        """Background task: connect, resubscribe, read, retry on disconnect."""
        attempt = 0
        while self._running:
            try:
                async with websockets.connect(self._url) as conn:
                    self._conn = conn
                    attempt = 0
                    logger.info("ws_connected", url=self._url)
                    await self._resubscribe()

                    # Start reader + ping as concurrent tasks
                    self._reader_task = asyncio.create_task(self._reader_loop(conn))
                    self._ping_task = asyncio.create_task(self._ping_loop())

                    # Wait for reader to finish (blocking within this background task)
                    await self._reader_task
            except (TimeoutError, ConnectionClosed, OSError) as exc:
                self._conn = None
                attempt += 1
                if 0 < self._cfg.max_reconnect_attempts <= attempt:
                    raise ExchangeError(
                        f"Max reconnect attempts ({self._cfg.max_reconnect_attempts}) exceeded"
                    ) from exc
                delay = min(self._cfg.reconnect_delay_sec * (1.5 ** (attempt - 1)), 30.0)
                logger.warning("ws_disconnected", attempt=attempt, retry_sec=delay, error=str(exc))
                await asyncio.sleep(delay)

    async def _resubscribe(self) -> None:
        """Re-send subscription messages for all registered topics."""
        subs = list(self._subscriptions)
        if not subs:
            return
        requests: list[dict[str, Any]] = []
        for key in subs:
            channel, topic = key.split(":", 1)
            requests.append({
                "time": int(asyncio.get_event_loop().time() * 1000),
                "channel": channel,
                "event": "subscribe",
                "payload": [topic],
            })
        logger.info("ws_resubscribe", count=len(requests))
        for req in requests:
            await self.send(req)

    # ── internal: reader / dispatch ──────────────────────────────

    async def _reader_loop(self, conn: ClientConnection) -> None:
        """Read messages from *conn* and dispatch to registered handlers.

        Dispatch key construction (three-tier match):
          1. ``{channel}:{result_s}`` — pair-scoped (from ``result.s``)
          2. ``{channel}:{event}``   — event-scoped (e.g. ``update``)
          3. ``{channel}``          — channel-wide broadcast fallback
        """
        async for raw in conn:
            try:
                msg: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                continue

            channel = msg.get("channel", "")
            event = msg.get("event", "")

            if channel == "spot.pong":
                continue

            # Extract pair from result.s if present (order_book, trades, etc.)
            result_s = ""
            result = msg.get("result")
            if isinstance(result, dict):
                result_s = result.get("s", "")

            # Build dispatch keys in priority order
            dispatch_keys: list[str] = []
            if channel and result_s:
                dispatch_keys.append(f"{channel}:{result_s}")
            if channel and event:
                dispatch_keys.append(f"{channel}:{event}")
            if channel:
                dispatch_keys.append(channel)

            # Dispatch to all matching handler queues
            dispatched = False
            for dk in dispatch_keys:
                for q in self._handlers.get(dk, []):
                    try:
                        q.put_nowait(msg)
                        dispatched = True
                    except asyncio.QueueFull:
                        _ = q.get_nowait()  # drop oldest
                        q.put_nowait(msg)
                        dispatched = True
                if dispatched:
                    break  # deliver only to the most specific match

    # ── internal: ping / keepalive ────────────────────────────────

    async def _ping_loop(self) -> None:
        """Send periodic pings to keep the connection alive."""
        while self._running and self._conn:
            await asyncio.sleep(self._cfg.ping_interval_sec)
            try:
                await self.send({"channel": "spot.ping"})
            except ExchangeError:
                return
