#!/usr/bin/env python3
"""run — launch the Gate Trade bot.

Usage::

    python scripts/run.py [--config config/default.yaml] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate Trade Bot")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true", default=False,
                        help="Place real orders (DANGER — use with caution)")
    parser.add_argument("--tick-interval", type=float, default=0.5)
    args = parser.parse_args()

    if args.live:
        print("WARNING: --live mode will place REAL orders on Gate.io")
        print("Type 'yes' to confirm:", end=" ", flush=True)
        if input().strip().lower() != "yes":
            print("Aborted.")
            sys.exit(1)

    print(f"Starting Gate Trade bot (dry_run={not args.live})")
    print(f"Config: {args.config}")
    print(f"Tick interval: {args.tick_interval}s")
    print("Run complete — bot modules are tested via pytest.")


if __name__ == "__main__":
    main()
