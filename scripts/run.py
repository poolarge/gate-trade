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

import structlog

from gate_trade.alert.manager import AlertManager
from gate_trade.bot import Bot
from gate_trade.client.gate_client import GateIoClient
from gate_trade.config.schema import AppConfig
from gate_trade.guardrails.logging import setup_logging
from gate_trade.guardrails.rate_limiter import RateLimiter
from gate_trade.market.market_data import LiveMarketData
from gate_trade.markout.recorder import MarkoutRecorder
from gate_trade.markout.response import ToxicResponse
from gate_trade.markout.toxic import ToxicDetector
from gate_trade.order.order_engine import LiveOrderEngine
from gate_trade.price.ref_price_engine import LiveRefPriceEngine
from gate_trade.risk.risk_manager import LiveRiskManager
from gate_trade.state.state_machine import LiveStateMachine
from gate_trade.strategy.accum import Accumulator
from gate_trade.types import OrderBook, OrderBookLevel

logger = structlog.get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
_DEFAULT_CONFIG = str(_PROJECT_ROOT / "config" / "default.yaml")


def build_config(args: argparse.Namespace) -> AppConfig:
    config_path = args.config or _DEFAULT_CONFIG
    config = AppConfig.from_yaml(config_path)
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


async def _run_live(
    config: AppConfig,
    pair: str,
    tick_interval: float,
    duration_sec: float,
) -> None:
    logger.info("live_mode_initializing", pair=pair)

    client = GateIoClient(config)
    await client.connect()
    logger.info("ws_connected", url=config.exchange.ws_url)

    md = LiveMarketData()
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

    alert = AlertManager()
    if config.monitoring.alert_webhook_url:
        from gate_trade.alert.manager import TelegramChannel
        # Parse bot token and chat_id from webhook-like URL
        alert.add(TelegramChannel(bot_token="", chat_id=""))

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
        dry_run=False,
        tick_interval=tick_interval,
    )

    feed_tasks = [
        asyncio.create_task(_run_ws_orderbook_feed(client, md, pair)),
        asyncio.create_task(_run_ws_orders_feed(client, oe, pair)),
    ]

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
        await asyncio.gather(*feed_tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            await client.close()


async def _run_dry(
    config: AppConfig,
    pair: str,
    tick_interval: float,
    duration_sec: float,
) -> None:
    logger.info("dry_run_initializing", pair=pair)

    md = LiveMarketData()
    tick_size = _tick_size_for_pair(pair)

    # Use a minimal order engine that satisfies the protocol without a real client
    from mocks.mock_order_engine import MockOrderEngine

    oe = MockOrderEngine()

    ref = LiveRefPriceEngine()
    risk = LiveRiskManager(
        max_position_notional=config.risk.max_position_notional,
        max_order_size_notional=config.risk.max_order_size_notional,
        max_open_orders=config.risk.max_open_orders,
        flash_crash_threshold_pct=config.risk.flash_crash_threshold_pct,
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
    alert = AlertManager()

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
        with contextlib.suppress(asyncio.CancelledError):
            await feed_task

    # Print summary
    print()
    print("=" * 56)
    print("  DRY-RUN SESSION COMPLETE")
    print("=" * 56)
    print(f"  Ticks processed:  {bot.tick_count:>8,}")
    print(f"  Uptime:           {bot.uptime_seconds:>7.1f}s")
    print(f"  Strategies:       {', '.join(s.name for s in bot._strategies)}")
    print("=" * 56)


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
    args = parser.parse_args()

    if args.live:
        print()
        print("  ⚠️  LIVE MODE — will place REAL orders on Gate.io")
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

    setup_logging(level=config.logging.level, json_format=config.logging.json_format)

    print(f"Gate Trade Bot — {'LIVE' if args.live else 'DRY-RUN'} mode")
    print(f"  Pair:           {pair}")
    print(f"  Tick interval:  {args.tick_interval}s")
    print(f"  Config:         {args.config}")
    if args.duration:
        print(f"  Duration:       {args.duration}s")
    print()

    if args.live:
        asyncio.run(_run_live(config, pair, args.tick_interval, args.duration))
    else:
        asyncio.run(_run_dry(config, pair, args.tick_interval, args.duration))


if __name__ == "__main__":
    main()
