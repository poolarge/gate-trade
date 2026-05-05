#!/usr/bin/env python3
"""Healthcheck — verify GateClient connectivity and pair metadata.

Usage:
  python scripts/healthcheck.py --pair BTC_USDT
  GATE_EXCHANGE__API_KEY=xxx GATE_EXCHANGE__API_SECRET=yyy python scripts/healthcheck.py --pair BTC_USDT
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from gate_trade.config.schema import AppConfig

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_config(yaml_path: str) -> AppConfig:
    base = Path(yaml_path)
    local = base.parent / "local.yaml"
    config = AppConfig.from_yaml_merged(base, local)

    # Env var overrides (GATE_ prefix)
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
    return config


async def main() -> int:
    parser = argparse.ArgumentParser(description="Gate Trade healthcheck")
    parser.add_argument("--pair", required=True, help="Trading pair, e.g. BTC_USDT")
    parser.add_argument(
        "--config",
        default=str(_PROJECT_ROOT / "config" / "default.yaml"),
        help="Path to config YAML",
    )
    args = parser.parse_args()

    from gate_trade.client.gate_client import GateIoClient

    try:
        config = _load_config(args.config)
    except Exception as exc:
        print(f"FAIL: config load error — {exc}")
        return 1

    if not config.exchange.api_key:
        print("WARN: No API key set. Set GATE_EXCHANGE__API_KEY and GATE_EXCHANGE__API_SECRET.")
        print("     REST calls will fail; continuing for WS test only.")

    client = GateIoClient(config)

    # 1. WS connect
    try:
        await client.connect()
        print(f"OK: WebSocket connected to {config.exchange.ws_url}")
    except Exception as exc:
        print(f"FAIL: WebSocket connect — {exc}")
        return 1

    # 2. Pair metadata (REST)
    if config.exchange.api_key:
        try:
            meta = await client.fetch_pair_meta(args.pair)
            print(f"OK: Pair {meta.pair} ({meta.base}/{meta.quote}) "
                  f"trade_status={meta.trade_status} "
                  f"min_base={meta.min_base_amount} precision={meta.precision}")
        except Exception as exc:
            print(f"FAIL: fetch_pair_meta({args.pair}) — {exc}")
            await client.close()
            return 1

        # 3. Balances
        try:
            balances = await client.fetch_all_balances()
            print(f"OK: {len(balances)} non-zero balance(s)")
            for b in balances[:10]:
                print(f"     {b.currency:>6s}  available={b.available:>15.8f}  locked={b.locked:>15.8f}")
        except Exception as exc:
            print(f"WARN: fetch_all_balances — {exc}")

        # 4. Open orders
        try:
            orders = await client.fetch_open_orders(args.pair)
            print(f"OK: {len(orders)} open order(s) for {args.pair}")
        except Exception as exc:
            print(f"WARN: fetch_open_orders — {exc}")

    # Cleanup
    try:
        await client.close()
        print("OK: WebSocket closed cleanly")
    except Exception:
        pass

    print("Healthcheck complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
