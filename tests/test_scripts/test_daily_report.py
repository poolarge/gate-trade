"""Unit tests for daily_report — Phase 4.2."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from scripts.daily_report import generate  # type: ignore[import-not-found]


def test_empty_report() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        con = sqlite3.connect(db_path)
        con.execute("CREATE TABLE fills (side TEXT, price REAL, filled_size REAL, created_at INTEGER)")
        con.commit()
        con.close()

        report = generate("2026-01-01", db_path)
        assert "No fills recorded" in report
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_report_with_fills() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        con = sqlite3.connect(db_path)
        con.execute("CREATE TABLE fills (side TEXT, price REAL, filled_size REAL, created_at INTEGER)")
        # 2026-01-01 00:00 UTC = 1767225600
        con.execute("INSERT INTO fills VALUES ('buy', 50000.0, 0.5, 1767225600)")
        con.execute("INSERT INTO fills VALUES ('sell', 51000.0, 0.3, 1767225660)")
        con.commit()
        con.close()

        report = generate("2026-01-01", db_path)
        assert "Fills: 2" in report
        assert "Buy volume:" in report
        assert "Sell volume:" in report
    finally:
        Path(db_path).unlink(missing_ok=True)
