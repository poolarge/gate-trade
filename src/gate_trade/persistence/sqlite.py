"""SQLite persistence — orders, fills, state, and markout storage."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import structlog

from gate_trade.persistence.contract import Persistence
from gate_trade.types import BotState, Order, OrderStatus, Side

logger = structlog.get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id      TEXT PRIMARY KEY,
    pair          TEXT NOT NULL,
    side          TEXT NOT NULL,
    price         REAL NOT NULL,
    size          REAL NOT NULL,
    filled_size   REAL NOT NULL DEFAULT 0.0,
    status        TEXT NOT NULL DEFAULT 'open',
    tag           TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fills (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      TEXT NOT NULL,
    pair          TEXT NOT NULL,
    fill_price    REAL NOT NULL,
    filled_size   REAL NOT NULL,
    created_at_ms INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000)
);

CREATE TABLE IF NOT EXISTS bot_state (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    state         TEXT NOT NULL DEFAULT 'INIT',
    sub_state     TEXT
);

CREATE TABLE IF NOT EXISTS markouts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fill_id       TEXT NOT NULL,
    pair          TEXT NOT NULL,
    fill_price    REAL NOT NULL,
    ref_5s        REAL NOT NULL DEFAULT 0.0,
    ref_30s       REAL NOT NULL DEFAULT 0.0,
    ref_5min      REAL NOT NULL DEFAULT 0.0,
    recorded_at_ms INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000)
);

CREATE INDEX IF NOT EXISTS idx_orders_pair ON orders(pair);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id);
CREATE INDEX IF NOT EXISTS idx_fills_pair ON fills(pair);
CREATE INDEX IF NOT EXISTS idx_markouts_pair ON markouts(pair);
"""


class SqlitePersistence(Persistence):
    """SQLite-backed persistence for bot state, orders, fills, and markouts.

    Uses WAL mode for concurrent reads during development. All writes
    are synchronous — the bot is single-threaded.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._path = Path(path)
        self._conn: sqlite3.Connection | None = None

    @property
    def _db(self) -> sqlite3.Connection:
        """Access the database connection, raising if not open."""
        if self._conn is None:
            raise RuntimeError("Persistence not opened — call open() first")
        return self._conn

    # ── Lifecycle ────────────────────────────────────────────────

    def open(self) -> None:
        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info("persistence_opened", path=str(self._path))

    def close(self) -> None:
        if self._conn:
            self._conn.commit()
            self._conn.close()
            self._conn = None
            logger.info("persistence_closed")

    # ── Orders ────────────────────────────────────────────────────

    def save_order(self, order: Order) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO orders "
            "(order_id, pair, side, price, size, filled_size, status, tag, created_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order.order_id, order.pair, order.side.value,
                order.price, order.size, order.filled_size,
                order.status.value, order.client_order_id, order.created_at_ms,
            ),
        )
        self._db.commit()

    def save_orders(self, orders: list[Order]) -> None:
        rows = [
            (o.order_id, o.pair, o.side.value, o.price, o.size,
             o.filled_size, o.status.value, o.client_order_id, o.created_at_ms)
            for o in orders
        ]
        self._db.executemany(
            "INSERT OR REPLACE INTO orders "
            "(order_id, pair, side, price, size, filled_size, status, tag, created_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._db.commit()

    def load_orders(self, pair: str) -> list[Order]:
        rows = self._db.execute(
            "SELECT order_id, pair, side, price, size, filled_size, status, tag, created_at_ms "
            "FROM orders WHERE pair = ?", (pair,)
        ).fetchall()
        return [self._row_to_order(row) for row in rows]

    def load_open_orders(self, pair: str) -> list[Order]:
        rows = self._db.execute(
            "SELECT order_id, pair, side, price, size, filled_size, status, tag, created_at_ms "
            "FROM orders WHERE pair = ? AND status = 'open'", (pair,)
        ).fetchall()
        return [self._row_to_order(row) for row in rows]

    # ── Fills ────────────────────────────────────────────────────

    def save_fill(self, order: Order, filled_size: float, price: float) -> None:
        self._db.execute(
            "INSERT INTO fills (order_id, pair, fill_price, filled_size) VALUES (?, ?, ?, ?)",
            (order.order_id, order.pair, price, filled_size),
        )
        self._db.execute(
            "UPDATE orders SET filled_size = filled_size + ?, status = CASE "
            "WHEN filled_size + ? >= size THEN 'closed' ELSE 'open' END "
            "WHERE order_id = ?",
            (filled_size, filled_size, order.order_id),
        )
        self._db.commit()

    def load_fills(self, pair: str, limit: int = 500) -> list[dict[str, object]]:
        rows = self._db.execute(
            "SELECT order_id, pair, fill_price, filled_size, created_at_ms "
            "FROM fills WHERE pair = ? ORDER BY id DESC LIMIT ?",
            (pair, limit),
        ).fetchall()
        return [
            {
                "order_id": r[0], "pair": r[1], "fill_price": r[2],
                "filled_size": r[3], "created_at_ms": r[4],
            }
            for r in rows
        ]

    # ── State ────────────────────────────────────────────────────

    def save_state(self, state: BotState, sub_state: str | None) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO bot_state (id, state, sub_state) VALUES (1, ?, ?)",
            (state.value, sub_state),
        )
        self._db.commit()

    def load_state(self) -> tuple[BotState, str | None]:
        row = self._db.execute(
            "SELECT state, sub_state FROM bot_state WHERE id = 1"
        ).fetchone()
        if row is None:
            return (BotState.INIT, None)
        return (BotState(row[0]), row[1])

    # ── Markout (Phase 6) ────────────────────────────────────────

    def save_markout(
        self, fill_id: str, pair: str, fill_price: float,
        ref_5s: float, ref_30s: float, ref_5min: float,
    ) -> None:
        self._db.execute(
            "INSERT INTO markouts (fill_id, pair, fill_price, ref_5s, ref_30s, ref_5min) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (fill_id, pair, fill_price, ref_5s, ref_30s, ref_5min),
        )
        self._db.commit()

    # ── Maintenance ──────────────────────────────────────────────

    def vacuum(self) -> None:
        self._db.execute("VACUUM")

    # ── Internal ─────────────────────────────────────────────────

    @staticmethod
    def _row_to_order(row: sqlite3.Row | tuple[Any, ...]) -> Order:
        return Order(
            order_id=str(row[0]),
            pair=str(row[1]),
            side=Side(str(row[2])),
            price=float(str(row[3])),
            size=float(str(row[4])),
            filled_size=float(str(row[5])),
            status=OrderStatus(str(row[6])),
            client_order_id=str(row[7]) if row[7] else "",
            created_at_ms=int(str(row[8])),
        )
