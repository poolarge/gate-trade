#!/usr/bin/env python3
"""replay — backtest strategy against historical market data.

Usage::

    python scripts/replay.py --data data/snapshots.csv [--pair BTC_USDT]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gate_trade.replay.engine import ReplayEngine
from gate_trade.replay.feeder import DataFeeder
from gate_trade.strategy.accum import Accumulator


def fmt_usd(amount: float) -> str:
    return f"${amount:,.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate Trade Historical Replay")
    parser.add_argument("--data", required=True, help="Path to CSV snapshots file")
    parser.add_argument("--pair", default="BTC_USDT", help="Trading pair")
    args = parser.parse_args()

    if not Path(args.data).exists():
        print(f"Data file not found: {args.data}", file=sys.stderr)
        sys.exit(1)

    # Build a simple accumulator strategy for replay
    strategy = Accumulator(
        pair=args.pair,
        tick_size=0.01,
        order_size=0.001,
        ladder_rungs=5,
        rung_spacing_ticks=5,
        start_offset_ticks=3,
        collapse_threshold_pct=5.0,
        collapse_recovery_pct=2.0,
    )

    engine = ReplayEngine(strategy)
    feeder = DataFeeder.from_csv(args.data)
    result = engine.run(feeder)

    # Print report
    print(f"# Replay Report — {args.pair}")
    print(f"  Snapshots processed: {result.total_snapshots}")
    print(f"  Total fills: {result.total_fills}")
    print(f"  Buy volume:  {fmt_usd(result.buy_volume)} ({result.buy_count} fills)")
    print(f"  Sell volume: {fmt_usd(result.sell_volume)} ({result.sell_count} fills)")
    print(f"  Net volume:  {fmt_usd(result.net_volume)}")
    print(f"  Net inventory: {result.net_inventory:.6f}")
    print(f"  Peak inventory: {result.peak_inventory:.6f}")
    print(f"  Avg buy price:  {fmt_usd(result.avg_buy_price)}")
    print(f"  Avg sell price: {fmt_usd(result.avg_sell_price)}")
    print(f"  Avg markout: {result.avg_markout_bps:+.2f} bps")
    print(f"  Toxic fills: {result.toxic_fill_count}/{result.total_fills}"
          f" ({result.toxic_ratio:.1%})")


if __name__ == "__main__":
    main()
