"""MarketData contract — orderbook maintenance + derived indicators."""

from __future__ import annotations

from typing import Protocol

from gate_trade.types import MarketSignal, OrderBook, OrderBookLevel


class MarketData(Protocol):
    """Maintains local orderbook and computes market-structure signals.

    Updated via WebSocket incremental deltas. All properties are
    non-blocking snapshots of current state.
    """

    # ── Order book state ─────────────────────────────────────

    @property
    def book(self) -> OrderBook:
        """Current best-bid/best-ask snapshot."""
        ...

    @property
    def bids(self) -> list[OrderBookLevel]:
        """Depth-sorted bids (descending price)."""
        ...

    @property
    def asks(self) -> list[OrderBookLevel]:
        """Depth-sorted asks (ascending price)."""
        ...

    def best_bid(self) -> float:
        """Highest bid price, or 0.0 if empty."""
        ...

    def best_ask(self) -> float:
        """Lowest ask price, or 0.0 if empty."""
        ...

    def spread_bps(self) -> float:
        """Spread in basis points (relative to mid)."""
        ...

    def mid_price(self) -> float:
        """Midpoint of best bid/ask."""
        ...

    # ── Order book depth ─────────────────────────────────────

    def depth_at_price(self, side: str, price: float) -> float:
        """Cumulative size on *side* up to (or down to) *price*."""
        ...

    def vwap(self, side: str, depth_notional: float) -> float:
        """VWAP for executing *depth_notional* USD on *side*."""
        ...

    # ── Mutators (called by WS feed) ─────────────────────────

    def apply_snapshot(self, book: OrderBook) -> None:
        """Replace the entire local book with a full snapshot."""
        ...

    def apply_delta(self, side: str, price: float, size: float) -> None:
        """Apply a single price-level update from an incremental feed."""
        ...

    # ── Market signals ───────────────────────────────────────

    def compute_signals(self) -> MarketSignal:
        """Run all indicator checks and return a signal bundle."""
        ...

    @property
    def flash_crash(self) -> bool:
        """True when recent price action suggests a flash crash."""
        ...

    @property
    def depth_wall(self) -> bool:
        """True when a large depth wall is detected on either side."""
        ...
