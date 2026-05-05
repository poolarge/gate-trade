#!/usr/bin/env python3
"""web-panel — start the Gate Trade monitoring dashboard.

Usage::

    python scripts/web_panel.py [--host 127.0.0.1] [--port 39120]
"""

from __future__ import annotations

import argparse
import sys

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate Trade Web Panel")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=39120)
    parser.add_argument("--reload", action="store_true", default=False)
    args = parser.parse_args()

    try:
        uvicorn.run(
            "gate_trade.web.panel:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="info",
        )
    except KeyboardInterrupt:
        print("\nShutting down.")
        sys.exit(0)


if __name__ == "__main__":
    main()
