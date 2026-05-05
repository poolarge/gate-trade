#!/usr/bin/env python3
"""dry-run — run the full bot pipeline against synthetic market data.

Generates realistic order book snapshots (random-walk mid + spread)
and feeds them through ReplayEngine with Accumulator + DepthKeeper
strategies. Produces a summary report.

Usage::

    python scripts/dry_run.py [--ticks 5000] [--interval 0.5]
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time

from gate_trade.markout.recorder import MarkoutRecorder
from gate_trade.markout.response import ToxicResponse
from gate_trade.markout.toxic import ToxicDetector
from gate_trade.replay.engine import ReplayEngine
from gate_trade.replay.feeder import DataFeeder, MarketSnapshot
from gate_trade.strategy.accum import Accumulator


def generate_snapshots(
    n: int,
    start_price: float = 50000.0,
    volatility_bps: float = 10.0,
    spread_ticks: float = 10.0,
    tick_size: float = 0.01,
) -> list[MarketSnapshot]:
    """Generate synthetic order book snapshots with random-walk mid.

    Parameters:
        n: number of snapshots
        start_price: initial mid price
        volatility_bps: per-step volatility in basis points
        spread_ticks: bid-ask spread in ticks
        tick_size: minimum price increment
    """
    snapshots: list[MarketSnapshot] = []
    mid = start_price
    spread = spread_ticks * tick_size
    step_std = volatility_bps / 10000.0 * mid  # convert bps to price stddev

    for i in range(n):
        ts = float(i)
        # Random walk with mean-reversion
        log_return = random.gauss(0, step_std / mid)
        # Light mean reversion toward start_price
        reversion = (math.log(start_price) - math.log(mid)) * 0.001
        mid *= math.exp(log_return + reversion)

        # Occasional micro spikes (1% chance per tick)
        if random.random() < 0.01:
            spike = random.uniform(-0.005, 0.005) * mid
            mid += spike

        # Occasional flash crash (0.2% chance)
        if random.random() < 0.002:
            mid *= random.uniform(0.95, 0.98)

        half_spread = spread / 2
        best_bid = round(mid - half_spread, 6)
        best_ask = round(mid + half_spread, 6)
        bid_size = round(random.uniform(0.1, 5.0), 4)
        ask_size = round(random.uniform(0.1, 5.0), 4)
        last_price = round(mid + random.gauss(0, half_spread), 6)

        snapshots.append(MarketSnapshot(
            timestamp=ts,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=bid_size,
            ask_size=ask_size,
            last_price=last_price,
        ))

    return snapshots


def fmt_usd(amount: float) -> str:
    return f"${amount:,.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate Trade Dry Run")
    parser.add_argument("--ticks", type=int, default=5000, help="Number of snapshots")
    parser.add_argument("--interval", type=float, default=0.5, help="Tick interval (seconds)")
    parser.add_argument("--price", type=float, default=50000.0, help="Starting mid price")
    parser.add_argument("--volatility", type=float, default=10.0, help="Volatility (bps per tick)")
    args = parser.parse_args()

    print(f"Generating {args.ticks} synthetic snapshots...")
    print(f"  Start price:  {fmt_usd(args.price)}")
    print(f"  Volatility:   {args.volatility} bps/tick")
    print(f"  Tick interval:{args.interval}s")
    print()

    # Generate market data
    t0 = time.monotonic()
    snapshots = generate_snapshots(
        n=args.ticks,
        start_price=args.price,
        volatility_bps=args.volatility,
    )
    gen_time = time.monotonic() - t0
    print(f"  Generated in {gen_time:.2f}s")
    print(f"  Price range: {fmt_usd(min(s.mid_price for s in snapshots))} - "
          f"{fmt_usd(max(s.mid_price for s in snapshots))}")
    print()

    # Build strategies
    accum = Accumulator(
        pair="BTC_USDT",
        tick_size=0.01,
        order_size=0.001,
        ladder_rungs=5,
        rung_spacing_ticks=5,
        start_offset_ticks=3,
        collapse_threshold_pct=5.0,
        collapse_recovery_pct=2.0,
    )

    # Build engine with full pipeline
    markout = MarkoutRecorder()
    toxic = ToxicDetector()
    tox_resp = ToxicResponse()

    engine = ReplayEngine(
        strategy=accum,
        markout=markout,
        toxic=toxic,
        response=tox_resp,
    )

    # Run
    print("Running replay...")
    feeder = DataFeeder.from_list(snapshots)
    t0 = time.monotonic()
    result = engine.run(feeder)
    run_time = time.monotonic() - t0

    # Report
    print()
    print("=" * 56)
    print("  DRY-RUN REPORT")
    print("=" * 56)
    print(f"  Snapshots:         {result.total_snapshots:>8,}")
    print(f"  Run time:          {run_time:>7.2f}s")
    print(f"  Throughput:        {result.total_snapshots/run_time:>7.0f} ticks/s")
    print()
    print(f"  Total fills:       {result.total_fills:>8,}")
    print(f"    Buys:            {result.buy_count:>8,}")
    print(f"    Sells:           {result.sell_count:>8,}")
    print(f"  Buy volume:        {fmt_usd(result.buy_volume):>12}")
    print(f"  Sell volume:       {fmt_usd(result.sell_volume):>12}")
    print(f"  Net volume:        {fmt_usd(result.net_volume):>12}")
    print(f"  Net inventory:     {result.net_inventory:>10.6f}")
    print(f"  Peak inventory:    {result.peak_inventory:>10.6f}")
    print()
    print(f"  Avg buy price:     {fmt_usd(result.avg_buy_price):>12}")
    print(f"  Avg sell price:    {fmt_usd(result.avg_sell_price):>12}")
    print(f"  Avg markout:       {result.avg_markout_bps:>+10.2f} bps")
    print()
    print(f"  Toxic fills:       {result.toxic_fill_count:>8,} / {result.total_fills}"
          f"  ({result.toxic_ratio:.1%})")
    print()
    print(f"  Toxic level:       {tox_resp.level.value}")
    print(f"  Spread multiplier: {tox_resp.spread_multiplier:.1f}x")

    # Verdict
    print()
    if result.total_fills > 0:
        print("  VERDICT:  Dry-run complete — no crashes, no hangs.")
        if result.avg_markout_bps > 0:
            print("            Positive markout — strategy is earning spread.")
        else:
            print("            Negative markout — check strategy parameters.")
    else:
        print("  VERDICT:  No fills occurred — widen price range or lower spread.")

    print("=" * 56)

    # Clean exit
    sys.exit(0 if result.total_fills > 0 else 1)


if __name__ == "__main__":
    main()
