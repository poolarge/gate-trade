"""Mock MarketData — canned orderbook for testing."""

from __future__ import annotations

from gate_trade.market.contract import MarketData
from gate_trade.types import MarketSignal, OrderBook, OrderBookLevel


class MockMarketData(MarketData):
    """MarketData that returns pre-configured snapshots."""

    def __init__(self) -> None:
        self._book = OrderBook()
        self._signals = MarketSignal()

    # ── Order book state ─────────────────────────────────────

    @property
    def book(self) -> OrderBook:
        return self._book

    @property
    def bids(self) -> list[OrderBookLevel]:
        return self._book.bids

    @property
    def asks(self) -> list[OrderBookLevel]:
        return self._book.asks

    def best_bid(self) -> float:
        return self._book.best_bid

    def best_ask(self) -> float:
        return self._book.best_ask

    def spread_bps(self) -> float:
        mid = self._book.mid_price
        if mid <= 0:
            return 0.0
        return (self._book.spread / mid) * 10000

    def mid_price(self) -> float:
        return self._book.mid_price

    # ── Depth ────────────────────────────────────────────────

    def depth_at_price(self, side: str, price: float) -> float:
        levels = self._book.bids if side == "buy" else self._book.asks
        total = 0.0
        for lvl in levels:
            if (side == "buy" and lvl.price >= price) or (side == "sell" and lvl.price <= price):
                total += lvl.size
        return total

    def vwap(self, side: str, depth_notional: float) -> float:
        levels = self._book.bids if side == "buy" else self._book.asks
        accumulated = 0.0
        total_cost = 0.0
        for lvl in levels:
            cost = lvl.price * lvl.size
            if total_cost + cost >= depth_notional:
                remaining = depth_notional - total_cost
                accumulated += remaining / lvl.price if lvl.price > 0 else 0.0
                break
            total_cost += cost
            accumulated += lvl.size
        return depth_notional / accumulated if accumulated > 0 else 0.0

    # ── Mutators ─────────────────────────────────────────────

    def apply_snapshot(self, book: OrderBook) -> None:
        self._book = book

    def apply_delta(self, side: str, price: float, size: float) -> None:
        pass

    # ── Signals ──────────────────────────────────────────────

    def compute_signals(self) -> MarketSignal:
        return self._signals

    @property
    def flash_crash(self) -> bool:
        return self._signals.flash_crash

    @property
    def depth_wall(self) -> bool:
        return self._signals.depth_wall_bid or self._signals.depth_wall_ask

    # ── Test helpers ─────────────────────────────────────────

    def set_book(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> None:
        self._book = OrderBook(
            bids=[OrderBookLevel(price=p, size=s) for p, s in bids],
            asks=[OrderBookLevel(price=p, size=s) for p, s in asks],
        )

    def set_flash_crash(self, active: bool) -> None:
        self._signals.flash_crash = active
