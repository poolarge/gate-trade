"""Persistence contract — order/fill/state storage and recovery."""

from __future__ import annotations

from typing import Protocol

from gate_trade.types import BotState, Order


class Persistence(Protocol):
    """SQLite-backed persistence for bot state, orders, fills, and markouts.

    All writes are synchronous (the bot is single-threaded). The persistence
    layer is designed for crash recovery, not analytics.
    """

    # ── Lifecycle ────────────────────────────────────────────

    def open(self) -> None:
        """Create or migrate the database and prepare statements."""
        ...

    def close(self) -> None:
        """Flush and close the database connection."""
        ...

    # ── Orders ───────────────────────────────────────────────

    def save_order(self, order: Order) -> None:
        """Insert or update an order record."""
        ...

    def save_orders(self, orders: list[Order]) -> None:
        """Batch insert/update orders."""
        ...

    def load_orders(self, pair: str) -> list[Order]:
        """Return all known orders for *pair* from the database."""
        ...

    def load_open_orders(self, pair: str) -> list[Order]:
        """Return only orders with status OPEN for *pair*."""
        ...

    # ── Fills ────────────────────────────────────────────────

    def save_fill(self, order: Order, filled_size: float, price: float) -> None:
        """Record a fill event."""
        ...

    def load_fills(self, pair: str, limit: int = 500) -> list[dict[str, object]]:
        """Return recent fills for *pair*."""
        ...

    # ── State ────────────────────────────────────────────────

    def save_state(self, state: BotState, sub_state: str | None) -> None:
        """Persist current bot state for crash recovery."""
        ...

    def load_state(self) -> tuple[BotState, str | None]:
        """Return the last saved bot state, or (INIT, None) if no record."""
        ...

    # ── Markout (Phase 6) ────────────────────────────────────

    def save_markout(
        self,
        fill_id: str,
        pair: str,
        fill_price: float,
        ref_5s: float,
        ref_30s: float,
        ref_5min: float,
    ) -> None:
        """Append a markout record for later toxicity analysis."""
        ...

    # ── Maintenance ──────────────────────────────────────────

    def vacuum(self) -> None:
        """Reclaim disk space from deleted records."""
        ...
