#!/usr/bin/env python3
"""daily-report — generate a daily operations summary for the Gate Trade bot.

Phase 4.2: Reads the SQLite persistence database and prints a Markdown
report suitable for Telegram, email, or human review.

Usage::

    python scripts/daily_report.py [--db data/gate_trade.db] [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_DB = "data/gate_trade.db"


def _conn(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _where_day(day: str) -> str:
    return f"date(created_at, 'unixepoch') = '{day}'"


def fmt_usd(amount: float) -> str:
    return f"${amount:,.2f}"


def query_fills(con: sqlite3.Connection, day: str) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT side, price, filled_size, created_at FROM fills WHERE "
        + _where_day(day) + " ORDER BY created_at"
    ).fetchall()


def query_summary(con: sqlite3.Connection, day: str) -> dict[str, float]:
    row = con.execute(
        "SELECT"
        "  COALESCE(SUM(CASE WHEN side='buy' THEN price*filled_size ELSE 0 END),0) AS buy_volume,"
        "  COALESCE(SUM(CASE WHEN side='sell' THEN price*filled_size ELSE 0 END),0) AS sell_volume,"
        "  COALESCE(SUM(CASE WHEN side='buy' THEN filled_size ELSE 0 END),0) AS total_bought,"
        "  COALESCE(SUM(CASE WHEN side='sell' THEN filled_size ELSE 0 END),0) AS total_sold,"
        "  COUNT(*) AS fill_count"
        " FROM fills WHERE " + _where_day(day)
    ).fetchone()
    return {k: row[k] for k in row.keys()} if row else {}  # noqa: SIM118


def generate(day: str, db_path: str) -> str:
    con = _conn(db_path)
    fills = query_fills(con, day)
    summary = query_summary(con, day)

    lines: list[str] = []
    lines.append(f"# Gate Trade Daily Report — {day}")
    lines.append("")

    if not fills:
        lines.append("No fills recorded today.")
        return "\n".join(lines)

    lines.append("## Summary")
    lines.append(f"- Fills: {summary['fill_count']}")
    lines.append(f"- Buy volume: {fmt_usd(summary['buy_volume'])}")
    lines.append(f"- Sell volume: {fmt_usd(summary['sell_volume'])}")
    lines.append(f"- Net: {fmt_usd(summary['sell_volume'] - summary['buy_volume'])}")
    lines.append(f"- Bought: {summary['total_bought']:.4f}")
    lines.append(f"- Sold: {summary['total_sold']:.4f}")
    avg_buy = summary['buy_volume'] / summary['total_bought'] if summary['total_bought'] > 0 else 0
    avg_sell = summary['sell_volume'] / summary['total_sold'] if summary['total_sold'] > 0 else 0
    lines.append(f"- Avg buy price: {fmt_usd(avg_buy)}")
    lines.append(f"- Avg sell price: {fmt_usd(avg_sell)}")
    lines.append("")

    lines.append("## Fills")
    for f in fills:
        ts = datetime.fromtimestamp(f["created_at"]).strftime("%H:%M:%S")
        lines.append(f"- {ts}  {f['side'].upper():4s}  {f['filled_size']:>8.4f}  @  {f['price']:>12.2f}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate Trade daily report")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database")
    parser.add_argument("--date", help="Report date (YYYY-MM-DD, default: yesterday)")
    args = parser.parse_args()

    day = args.date or (date.today() - timedelta(days=1)).isoformat()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    report = generate(day, args.db)
    print(report)


if __name__ == "__main__":
    main()
