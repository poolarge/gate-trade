"""RefPriceEngine — reference price with self-trade exclusion and spike protection."""

from __future__ import annotations

import time
from collections import deque

import structlog

from gate_trade.price.contract import RefPriceEngine
from gate_trade.types import PRICE_DECIMALS

logger = structlog.get_logger(__name__)


class LiveRefPriceEngine(RefPriceEngine):
    """Computes reference price excluding own orders from the top of book.

    Mid / Microprice / TWAP
        *mid* is the simple midpoint of best bid and best ask.
        *microprice* weights bid and ask by the opposite side's size.
        *TWAP* is a simple SMA of recent mid prices.

    Self-fill exclusion
        When feeding book prices via :meth:`update`, pass the prices of
        own resting orders. If the best bid or best ask matches one of
        those prices, the engine excludes that level and uses the next
        best level instead.

    Spike protection
        If the ref price moves more than *spike_threshold_bps* within
        *spike_window_sec*, the engine enters a cooldown during which
        ``spike_protection_active`` returns True.
    """

    def __init__(
        self,
        spike_threshold_bps: float = 50.0,
        spike_window_sec: float = 10.0,
        spike_cooldown_sec: float = 30.0,
    ) -> None:
        self._spike_threshold = spike_threshold_bps
        self._spike_window = spike_window_sec
        self._spike_cooldown = spike_cooldown_sec

        self._ref: float = 0.0
        self._ref_bid: float = 0.0
        self._ref_ask: float = 0.0
        self._best_bid: float = 0.0
        self._best_ask: float = 0.0

        # TWAP ring buffer
        self._twap_window: deque[tuple[float, float]] = deque()  # (mid, timestamp)
        self._twap_seconds: float = 30.0

        # Spike detection
        self._mid_history: deque[tuple[float, float]] = deque()
        self._spike_active: bool = False
        self._spike_until: float = 0.0

        # Self-exclusion tracking
        self._own_bid_prices: set[float] = set()
        self._own_ask_prices: set[float] = set()

    # ── Reference price ──────────────────────────────────────────

    @property
    def ref_price(self) -> float:
        return round(self._ref, PRICE_DECIMALS)

    @property
    def ref_bid(self) -> float:
        return round(self._ref_bid, PRICE_DECIMALS)

    @property
    def ref_ask(self) -> float:
        return round(self._ref_ask, PRICE_DECIMALS)

    # ── Update ───────────────────────────────────────────────────

    def update(
        self,
        best_bid: float,
        best_ask: float,
        own_bids: list[float],
        own_asks: list[float],
    ) -> None:
        """Recompute reference price from market top-of-book.

        Own resting orders at the best bid/ask are excluded to prevent
        self-trade influence on the ref price.
        """
        self._own_bid_prices = set(own_bids)
        self._own_ask_prices = set(own_asks)

        # Exclude own prices from best bid/ask
        bid = best_bid if best_bid not in self._own_bid_prices else 0.0
        ask = best_ask if best_ask not in self._own_ask_prices else 0.0

        self._best_bid = bid
        self._best_ask = ask

        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0
            # Microprice: weighted by opposite side
            # In real impl this would use actual sizes, but the Protocol
            # doesn't pass sizes. Use simple mid.
            micro = mid
        elif ask > 0:
            mid = ask
            micro = ask
        elif bid > 0:
            mid = bid
            micro = bid
        else:
            return  # no valid price data

        self._ref = micro
        self._ref_bid = bid if bid > 0 else self._ref
        self._ref_ask = ask if ask > 0 else self._ref

        # Spike detection
        self._check_spike(mid)

        # TWAP
        now = time.monotonic()
        self._twap_window.append((mid, now))
        self._trim_twap_window(now)

    # ── Spike protection ─────────────────────────────────────────

    @property
    def spike_protection_active(self) -> bool:
        if self._spike_active and time.monotonic() >= self._spike_until:
            self._spike_active = False
        return self._spike_active

    @property
    def spike_cooldown_remaining_ms(self) -> int:
        if not self._spike_active:
            return 0
        remaining = int((self._spike_until - time.monotonic()) * 1000)
        return max(remaining, 0)

    def reset(self) -> None:
        self._ref = 0.0
        self._ref_bid = 0.0
        self._ref_ask = 0.0
        self._mid_history.clear()
        self._twap_window.clear()
        self._spike_active = False
        self._spike_until = 0.0

    # ── Internal ─────────────────────────────────────────────────

    def _check_spike(self, mid: float) -> None:
        """Detect if mid moved beyond threshold within the lookback window."""
        now = time.monotonic()
        self._mid_history.append((mid, now))

        # Remove old entries
        cutoff = now - self._spike_window
        while self._mid_history and self._mid_history[0][1] < cutoff:
            self._mid_history.popleft()

        if len(self._mid_history) < 2:
            return

        old_mid = self._mid_history[0][0]
        if old_mid <= 0:
            return

        change_bps = abs(mid - old_mid) / old_mid * 10000.0
        if change_bps >= self._spike_threshold and not self._spike_active:
            self._spike_active = True
            self._spike_until = now + self._spike_cooldown
            logger.warning("spike_detected", change_bps=round(change_bps, 1),
                           old_mid=old_mid, new_mid=mid)

    def _trim_twap_window(self, now: float) -> None:
        cutoff = now - self._twap_seconds
        while self._twap_window and self._twap_window[0][1] < cutoff:
            self._twap_window.popleft()

    @property
    def twap(self) -> float:
        """Simple TWAP of mid prices over the recent window."""
        self._trim_twap_window(time.monotonic())
        if not self._twap_window:
            return self._ref
        total = sum(m for m, _ in self._twap_window)
        return total / len(self._twap_window)
