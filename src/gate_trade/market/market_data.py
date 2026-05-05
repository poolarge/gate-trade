"""MarketData — WebSocket-driven orderbook with derived indicators."""

from __future__ import annotations

from bisect import bisect_left

import structlog

from gate_trade.market.contract import MarketData
from gate_trade.types import MarketSignal, OrderBook, OrderBookLevel

logger = structlog.get_logger(__name__)

# Price-history ring buffer sizing
_PRICE_HISTORY_CAPACITY = 128


class LiveMarketData(MarketData):
    """Real-time orderbook maintained via WS full-snapshot + incremental deltas.

    Bids are kept sorted descending (highest price first).
    Asks are kept sorted ascending (lowest price first).

    A ring buffer of recent mid-prices drives flash-crash and depth-wall
    detection. All public methods are non-blocking O(log N) or O(N) where
    N is the number of book levels.
    """

    def __init__(self) -> None:
        self._bids: list[OrderBookLevel] = []
        self._asks: list[OrderBookLevel] = []
        self._bids_by_price: dict[float, float] = {}
        self._asks_by_price: dict[float, float] = {}
        self._timestamp_ms: int = 0

        # Derived-indicator state
        self._mid_history: list[float] = []         # ring buffer
        self._history_idx: int = 0
        self._history_count: int = 0
        self._cached_signals: MarketSignal | None = None
        self._signals_stale: bool = True

    # ── Order book state ─────────────────────────────────────────

    @property
    def book(self) -> OrderBook:
        return OrderBook(
            bids=list(self._bids),
            asks=list(self._asks),
            timestamp_ms=self._timestamp_ms,
        )

    @property
    def bids(self) -> list[OrderBookLevel]:
        return list(self._bids)

    @property
    def asks(self) -> list[OrderBookLevel]:
        return list(self._asks)

    def best_bid(self) -> float:
        return self._bids[0].price if self._bids else 0.0

    def best_ask(self) -> float:
        return self._asks[0].price if self._asks else 0.0

    def spread_bps(self) -> float:
        mid = self.mid_price()
        spread = self.best_ask() - self.best_bid()
        if mid <= 0 or spread <= 0:
            return 0.0
        return (spread / mid) * 10000.0

    def mid_price(self) -> float:
        bb = self.best_bid()
        ba = self.best_ask()
        if bb <= 0 or ba <= 0:
            return 0.0
        return (bb + ba) / 2.0

    # ── Depth queries ────────────────────────────────────────────

    def depth_at_price(self, side: str, price: float) -> float:
        """Cumulative size from the best price down to (or up to) *price*.

        For bids: includes all levels with price >= *price*.
        For asks: includes all levels with price <= *price*.
        """
        levels = self._bids if side == "buy" else self._asks
        if not levels:
            return 0.0
        total = 0.0
        for lvl in levels:
            if side == "buy":
                if lvl.price < price:
                    break
            else:
                if lvl.price > price:
                    break
            total += lvl.size
        return total

    def vwap(self, side: str, depth_notional: float) -> float:
        """VWAP for executing *depth_notional* USD worth of base currency."""
        levels = self._bids if side == "buy" else self._asks
        if depth_notional <= 0 or not levels:
            return 0.0
        remaining = depth_notional
        total_cost = 0.0
        total_size = 0.0
        for lvl in levels:
            available = lvl.size * lvl.price  # notional at this level
            if available >= remaining:
                total_cost += remaining
                total_size += remaining / lvl.price
                break
            total_cost += available
            total_size += lvl.size
            remaining -= available
        return total_cost / total_size if total_size > 0 else 0.0

    # ── Mutators ─────────────────────────────────────────────────

    def apply_snapshot(self, book: OrderBook) -> None:
        """Full replacement of the local orderbook."""
        self._bids = sorted(book.bids, key=lambda level: level.price, reverse=True)
        self._asks = sorted(book.asks, key=lambda level: level.price)
        self._bids_by_price = {lv.price: lv.size for lv in self._bids}
        self._asks_by_price = {lv.price: lv.size for lv in self._asks}
        self._timestamp_ms = book.timestamp_ms
        self._signals_stale = True
        self._record_mid()

    def apply_delta(self, side: str, price: float, size: float) -> None:
        """Apply a single price-level update.

        If *size* is 0, the level is removed. Otherwise the level is
        inserted or updated, keeping the internal lists sorted.
        """
        levels = self._bids if side == "buy" else self._asks
        lookup = self._bids_by_price if side == "buy" else self._asks_by_price
        reverse_order = side == "buy"

        old_size = lookup.get(price)
        if old_size is not None:
            levels.remove(OrderBookLevel(price=price, size=old_size))
            del lookup[price]

        if size > 0:
            lookup[price] = size
            entry = OrderBookLevel(price=price, size=size)
            if reverse_order:
                idx = bisect_left([-lv.price for lv in levels], -price)
            else:
                idx = bisect_left([lv.price for lv in levels], price)
            levels.insert(idx, entry)

        self._signals_stale = True
        self._record_mid()

    # ── Market signals ───────────────────────────────────────────

    def compute_signals(self) -> MarketSignal:
        """Compute all market indicator checks and cache the result."""
        if not self._signals_stale and self._cached_signals is not None:
            return self._cached_signals

        sig = MarketSignal(
            flash_crash=self._detect_flash_crash(),
            depth_wall_bid=self._detect_depth_wall("buy"),
            depth_wall_ask=self._detect_depth_wall("sell"),
            spread_bps=self.spread_bps(),
            imbalance=self._compute_imbalance(),
        )
        self._cached_signals = sig
        self._signals_stale = False
        return sig

    @property
    def flash_crash(self) -> bool:
        return self._detect_flash_crash()

    @property
    def depth_wall(self) -> bool:
        return self._detect_depth_wall("buy") or self._detect_depth_wall("sell")

    # ── Internal: flash crash ────────────────────────────────────

    def _detect_flash_crash(self) -> bool:
        """True if the mid price dropped > 5% in the last window."""
        if self._history_count < 2:
            return False
        recent = self._recent_mids()
        if not recent:
            return False
        high = max(recent)
        low = min(recent)
        if high <= 0:
            return False
        return (high - low) / high >= 0.05  # 5% threshold

    def _recent_mids(self) -> list[float]:
        """Return non-zero entries from the ring buffer."""
        if self._history_count == 0:
            return []
        cap = _PRICE_HISTORY_CAPACITY
        count = min(self._history_count, cap)
        result: list[float] = []
        for i in range(count):
            idx = (self._history_idx - 1 - i) % cap
            val = self._mid_history[idx] if idx < len(self._mid_history) else 0.0
            result.append(val)
        return [v for v in result if v > 0]

    def _record_mid(self) -> None:
        mid = self.mid_price()
        if mid <= 0:
            return
        cap = _PRICE_HISTORY_CAPACITY
        if len(self._mid_history) < cap:
            self._mid_history.append(mid)
        else:
            self._mid_history[self._history_idx] = mid
        self._history_idx = (self._history_idx + 1) % cap
        self._history_count += 1

    # ── Internal: depth wall ─────────────────────────────────────

    def _detect_depth_wall(self, side: str) -> bool:
        """True when a single price level has ≥ 5× the average size of
        the surrounding 10 levels on this side."""
        levels = self._bids if side == "buy" else self._asks
        if len(levels) < 5:
            return False
        sizes = [lv.size for lv in levels[:10]]
        avg = sum(sizes) / len(sizes)
        if avg <= 0:
            return False
        return max(sizes) >= avg * 5.0

    # ── Internal: imbalance ──────────────────────────────────────

    def _compute_imbalance(self) -> float:
        """Orderbook imbalance: (bid_volume - ask_volume) / (bid_volume + ask_volume).

        Returns -1..1: negative = sell pressure, positive = buy pressure.
        """
        top_n = 10
        bid_vol = sum(lv.size for lv in self._bids[:top_n])
        ask_vol = sum(lv.size for lv in self._asks[:top_n])
        total = bid_vol + ask_vol
        if total <= 0:
            return 0.0
        return (bid_vol - ask_vol) / total
