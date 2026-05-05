#!/usr/bin/env python3
"""run — launch the Gate Trade bot.

Usage::

    # Dry-run with synthetic market data (safe, no API keys needed)
    python scripts/run.py --pair BTC_USDT --duration-min 5

    # Live mode with Gate.io API keys
    GATE_EXCHANGE__API_KEY=xxx GATE_EXCHANGE__API_SECRET=yyy \\
        python scripts/run.py --live --pair BTC_USDT

    # Dry-run with custom configuration
    python scripts/run.py --config config/local.yaml --pair BTC_USDT --tick-interval 0.25
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import math
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

import structlog
import uvicorn

from gate_trade.alert.manager import AlertManager
from gate_trade.bot import Bot
from gate_trade.client.gate_client import GateIoClient
from gate_trade.config.schema import AppConfig, MonitoringConfig
from gate_trade.guardrails.logging import setup_logging
from gate_trade.guardrails.rate_limiter import RateLimiter
from gate_trade.market.market_data import LiveMarketData
from gate_trade.markout.recorder import MarkoutRecorder
from gate_trade.markout.response import ToxicResponse
from gate_trade.markout.toxic import ToxicDetector
from gate_trade.order.order_engine import LiveOrderEngine
from gate_trade.persistence.sqlite import SqlitePersistence
from gate_trade.price.ref_price_engine import LiveRefPriceEngine
from gate_trade.risk.risk_manager import LiveRiskManager
from gate_trade.state.state_machine import LiveStateMachine
from gate_trade.strategy.accum import Accumulator
from gate_trade.types import OrderBook, OrderBookLevel

logger = structlog.get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
_DEFAULT_CONFIG = str(_PROJECT_ROOT / "config" / "default.yaml")
_LOCAL_CONFIG = str(_PROJECT_ROOT / "config" / "local.yaml")

_PREFLIGHT_TIMEOUT_SEC = 30


def build_config(args: argparse.Namespace) -> AppConfig:
    """Load config with local overrides and environment variables.

    Priority (high → low):
      1. Environment variables GATE_*
      2. config/local.yaml (optional)
      3. config/default.yaml
    """
    base_config = args.config or _DEFAULT_CONFIG
    local_config = _LOCAL_CONFIG if Path(_LOCAL_CONFIG).exists() else None
    config = AppConfig.from_yaml_merged(base_config, local_config)

    # Environment variable overrides
    overrides: dict[str, object] = {}
    for key, value in os.environ.items():
        if key.startswith("GATE_"):
            field_path = key[5:].lower().replace("__", ".")
            if field_path:
                overrides[field_path] = value
    if overrides:
        config = config.model_validate(
            AppConfig._apply_overrides(config.model_dump(), overrides)
        )
    if args.pair:
        config.trading.target_pair = args.pair
    return config


def _tick_size_for_pair(pair: str) -> float:
    tick_map: dict[str, float] = {
        "BTC_USDT": 0.01,
        "ETH_USDT": 0.01,
        "SOL_USDT": 0.01,
        "DOGE_USDT": 0.00001,
    }
    for prefix, tick in tick_map.items():
        if pair.startswith(prefix):
            return tick
    return 0.01


# ── Preflight ───────────────────────────────────────────────────


class PreflightError(Exception):
    """Raised when a preflight check fails and the bot should not start."""


async def _preflight(
    client: GateIoClient,
    md: LiveMarketData,
    oe: LiveOrderEngine,
    pair: str,
    timeout_sec: float = _PREFLIGHT_TIMEOUT_SEC,
) -> list[Any]:
    """Run startup checks before entering the main bot loop.

    Returns the list of balances retrieved.
    """
    logger.info("preflight_start", pair=pair)

    # 1. Wait for WS connection
    deadline = time.monotonic() + timeout_sec
    while not client.ws.connected:
        if time.monotonic() > deadline:
            raise PreflightError(
                f"WebSocket connection not established within {timeout_sec}s"
            )
        await asyncio.sleep(0.5)
    logger.info("preflight_ws_ready")

    # 2. Wait for first valid market data
    while md.mid_price() <= 0:
        if time.monotonic() > deadline:
            raise PreflightError(
                f"No market data received within {timeout_sec}s"
            )
        await asyncio.sleep(0.5)
    logger.info("preflight_market_data_ready", mid=round(md.mid_price(), 2))

    # 3. Fetch balances
    balances: list[Any] = []
    try:
        balances = await client.fetch_all_balances()
        logger.info("preflight_balances", count=len(balances))
    except Exception:
        logger.warning("preflight_balance_fetch_failed")

    # 4. Reconcile orders
    try:
        orphans = await oe.reconcile(pair)
        if orphans:
            logger.warning("preflight_orphans", count=len(orphans))
        else:
            logger.info("preflight_orders_clean")
    except Exception:
        logger.warning("preflight_reconcile_failed")

    logger.info("preflight_passed")
    return balances


# ── Web Panel ───────────────────────────────────────────────────


async def _start_web_panel(
    bot: Bot,
    host: str | None = None,
    port: int = 39120,
) -> uvicorn.Server:
    from gate_trade.web import panel

    panel.bind_bot(bot)
    if host is None:
        host = os.environ.get("GATE_WEB_HOST", "127.0.0.1")
    config = uvicorn.Config(app=panel.app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    logger.info("web_panel_starting", host=host, port=port)
    await server.serve()
    return server


# ── Synthetic feed ──────────────────────────────────────────────


async def _run_synthetic_feed(
    md: LiveMarketData,
    tick_interval: float,
    start_price: float = 50000.0,
) -> None:
    """Feed synthetic random-walk order book snapshots for dry-run mode."""
    mid = start_price
    spread = 10 * 0.01  # 10-tick bid-ask spread
    step_std = 10.0 / 10000.0  # 10 bps per tick in proportion terms

    while True:
        log_return = random.gauss(0, step_std)
        reversion = (math.log(start_price) - math.log(max(mid, 1))) * 0.001
        mid *= math.exp(log_return + reversion)
        mid = max(mid, 1.0)

        half = spread / 2
        ts = int(time.time() * 1000)
        book = OrderBook(
            bids=[OrderBookLevel(price=round(mid - half, 6), size=round(random.uniform(0.1, 5.0), 4))],
            asks=[OrderBookLevel(price=round(mid + half, 6), size=round(random.uniform(0.1, 5.0), 4))],
            timestamp_ms=ts,
        )
        md.apply_snapshot(book)
        await asyncio.sleep(tick_interval)


# ── WS feeds ────────────────────────────────────────────────────


async def _run_ws_orderbook_feed(
    client: GateIoClient,
    md: LiveMarketData,
    pair: str,
) -> None:
    """Feed live WebSocket order book data into the market data store."""
    async for book in client.subscribe_orderbook(pair):
        md.apply_snapshot(book)


async def _run_ws_orders_feed(
    client: GateIoClient,
    oe: LiveOrderEngine,
    pair: str,
) -> None:
    """Feed live WebSocket order updates into the order engine."""
    async for _orders in client.subscribe_orders(pair):
        pass  # Reconciliation happens via REST, WS orders are informational


# ── Alert setup ─────────────────────────────────────────────────


def _build_alert(cfg: MonitoringConfig) -> AlertManager:
    """Wire up alert channels based on configuration."""
    alert = AlertManager()

    if cfg.telegram_bot_token and cfg.telegram_chat_id:
        from gate_trade.alert.manager import TelegramChannel
        alert.add(TelegramChannel(
            bot_token=cfg.telegram_bot_token,
            chat_id=cfg.telegram_chat_id,
        ))

    if cfg.alert_webhook_url:
        from gate_trade.alert.manager import WebhookChannel
        alert.add(WebhookChannel(url=cfg.alert_webhook_url))

    return alert


# ── Live mode ───────────────────────────────────────────────────


async def _run_live(
    config: AppConfig,
    pair: str,
    tick_interval: float,
    duration_sec: float,
    db_path: str,
) -> None:
    logger.info("live_mode_initializing", pair=pair)

    # Validate API keys
    if not config.exchange.api_key or config.exchange.api_key == "REPLACE_ME":
        print("ERROR: API key not configured. Set GATE_EXCHANGE__API_KEY and GATE_EXCHANGE__API_SECRET.")
        print("       Or set exchange.api_key / exchange.api_secret in config/local.yaml")
        sys.exit(1)

    client = GateIoClient(config)
    await client.connect()

    md = LiveMarketData(flash_crash_threshold_pct=config.risk.flash_crash_threshold_pct)
    rl = RateLimiter(
        burst=config.rate_limit.burst,
        rate=config.rate_limit.rate,
        max_wait_sec=config.rate_limit.max_wait_sec,
    )
    tick_size = _tick_size_for_pair(pair)
    oe = LiveOrderEngine(client=client, rate_limiter=rl, tick_size=tick_size)

    ref = LiveRefPriceEngine()
    risk = LiveRiskManager(
        max_position_notional=config.risk.max_position_notional,
        max_order_size_notional=config.risk.max_order_size_notional,
        max_open_orders=config.risk.max_open_orders,
        flash_crash_threshold_pct=config.risk.flash_crash_threshold_pct,
        hit_cap_cooldown_ms=config.risk.cooldown_fill_ms,
        pair=pair,
    )

    sm = LiveStateMachine()
    accum = Accumulator(
        pair=pair,
        tick_size=tick_size,
        order_size=0.001,
        ladder_rungs=5,
        rung_spacing_ticks=5,
        start_offset_ticks=3,
        collapse_threshold_pct=5.0,
        collapse_recovery_pct=2.0,
    )

    markout = MarkoutRecorder()
    toxic = ToxicDetector()
    tox_resp = ToxicResponse()

    alert = _build_alert(config.monitoring)

    persistence = SqlitePersistence(db_path)
    persistence.open()

    bot = Bot(
        state_machine=sm,
        market_data=md,
        ref_price=ref,
        strategies=[accum],
        order_engine=oe,
        risk_manager=risk,
        markout=markout,
        toxic=toxic,
        toxic_response=tox_resp,
        alert=alert,
        persistence=persistence,
        client=client,
        pair=pair,
        dry_run=False,
        tick_interval=tick_interval,
    )

    # Preflight checks
    try:
        balances = await _preflight(client, md, oe, pair)
        bot._balances = balances
    except PreflightError as exc:
        logger.critical("preflight_failed", error=str(exc))
        print(f"FATAL: {exc}")
        persistence.close()
        await client.close()
        sys.exit(1)

    feed_tasks = [
        asyncio.create_task(_run_ws_orderbook_feed(client, md, pair)),
        asyncio.create_task(_run_ws_orders_feed(client, oe, pair)),
    ]
    panel_task = asyncio.create_task(_start_web_panel(bot))

    try:
        if duration_sec > 0:
            logger.info("live_duration_limited", seconds=duration_sec)
            run_task = asyncio.create_task(bot.run())
            await asyncio.sleep(duration_sec)
            await bot.shutdown()
            await asyncio.wait_for(run_task, timeout=30)
        else:
            await bot.run()
    finally:
        for task in feed_tasks:
            task.cancel()
        panel_task.cancel()
        await asyncio.gather(*feed_tasks, return_exceptions=True)
        with contextlib.suppress(asyncio.CancelledError):
            await panel_task
        with contextlib.suppress(Exception):
            await client.close()
        with contextlib.suppress(Exception):
            persistence.close()


# ── Dry-run mode ────────────────────────────────────────────────


async def _run_dry(
    config: AppConfig,
    pair: str,
    tick_interval: float,
    duration_sec: float,
    db_path: str,
) -> None:
    logger.info("dry_run_initializing", pair=pair)

    md = LiveMarketData(flash_crash_threshold_pct=config.risk.flash_crash_threshold_pct)
    tick_size = _tick_size_for_pair(pair)

    from mocks.mock_order_engine import MockOrderEngine

    oe = MockOrderEngine()

    ref = LiveRefPriceEngine()
    risk = LiveRiskManager(
        max_position_notional=config.risk.max_position_notional,
        max_order_size_notional=config.risk.max_order_size_notional,
        max_open_orders=config.risk.max_open_orders,
        flash_crash_threshold_pct=config.risk.flash_crash_threshold_pct,
        pair=pair,
    )

    sm = LiveStateMachine()
    accum = Accumulator(
        pair=pair,
        tick_size=tick_size,
        order_size=0.001,
        ladder_rungs=5,
        rung_spacing_ticks=5,
        start_offset_ticks=3,
        collapse_threshold_pct=5.0,
        collapse_recovery_pct=2.0,
    )

    markout = MarkoutRecorder()
    toxic = ToxicDetector()
    tox_resp = ToxicResponse()
    alert = _build_alert(config.monitoring)

    persistence = SqlitePersistence(db_path)
    persistence.open()

    bot = Bot(
        state_machine=sm,
        market_data=md,
        ref_price=ref,
        strategies=[accum],
        order_engine=oe,
        risk_manager=risk,
        markout=markout,
        toxic=toxic,
        toxic_response=tox_resp,
        alert=alert,
        persistence=persistence,
        pair=pair,
        dry_run=True,
        tick_interval=tick_interval,
    )

    # Prime market data with one snapshot so the first tick has a valid mid
    fake_book = OrderBook(
        bids=[OrderBookLevel(price=49999.99, size=1.0)],
        asks=[OrderBookLevel(price=50000.01, size=1.0)],
        timestamp_ms=int(time.time() * 1000),
    )
    md.apply_snapshot(fake_book)

    feed_task = asyncio.create_task(_run_synthetic_feed(md, tick_interval, start_price=50000.0))
    panel_task = asyncio.create_task(_start_web_panel(bot))

    try:
        if duration_sec > 0:
            logger.info("dry_run_duration_limited", seconds=duration_sec)
            run_task = asyncio.create_task(bot.run())
            await asyncio.sleep(duration_sec)
            await bot.shutdown()
            await asyncio.wait_for(run_task, timeout=30)
        else:
            await bot.run()
    finally:
        feed_task.cancel()
        panel_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await feed_task
        with contextlib.suppress(asyncio.CancelledError):
            await panel_task
        with contextlib.suppress(Exception):
            persistence.close()

    # Print summary
    print()
    print("=" * 56)
    print("  DRY-RUN SESSION COMPLETE")
    print("=" * 56)
    print(f"  Ticks processed:  {bot.tick_count:>8,}")
    print(f"  Uptime:           {bot.uptime_seconds:>7.1f}s")
    print(f"  Strategies:       {', '.join(s.name for s in bot._strategies)}")
    print(f"  DB:               {db_path}")
    print("=" * 56)


# ── Main ────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate Trade Bot")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="Path to config YAML")
    parser.add_argument("--pair", default="", help="Trading pair (e.g. BTC_USDT)")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Run with synthetic market data (default, safe)")
    parser.add_argument("--live", action="store_true", default=False,
                        help="Place real orders on Gate.io (DANGER)")
    parser.add_argument("--tick-interval", type=float, default=0.5,
                        help="Seconds between ticks")
    parser.add_argument("--duration", type=float, default=0,
                        help="Stop after N seconds (0 = run forever)")
    parser.add_argument("--data-dir", default="data",
                        help="Directory for SQLite database and log files")
    args = parser.parse_args()

    if args.live:
        print()
        print("  WARNING: LIVE MODE — will place REAL orders on Gate.io")
        print(f"     Pair: {args.pair or '(from config)'}")
        print("  Type 'yes' to confirm:", end=" ", flush=True)
        if input().strip().lower() != "yes":
            print("  Aborted.")
            sys.exit(1)
        print()

    config = build_config(args)
    pair = args.pair or config.trading.target_pair
    if not pair or pair == "TARGET_USDT":
        print("ERROR: No trading pair specified. Use --pair BTC_USDT")
        sys.exit(1)

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    log_file = str(data_dir / "bot.log")
    db_path = str(data_dir / "gate_trade.db")

    setup_logging(level=config.logging.level, json_format=config.logging.json_format,
                  log_file=log_file)

    print(f"Gate Trade Bot — {'LIVE' if args.live else 'DRY-RUN'} mode")
    print(f"  Pair:           {pair}")
    print(f"  Tick interval:  {args.tick_interval}s")
    print(f"  Config:         {args.config}")
    print(f"  Data dir:       {data_dir}")
    if args.duration:
        print(f"  Duration:       {args.duration}s")
    print()

    if args.live:
        asyncio.run(_run_live(config, pair, args.tick_interval, args.duration, db_path))
    else:
        asyncio.run(_run_dry(config, pair, args.tick_interval, args.duration, db_path))


if __name__ == "__main__":
    main()
