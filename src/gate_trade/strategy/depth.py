"""Depth Keeper — 3-tier market-making with ACTIVE/DORMANT toggle and anti-spoof.

Phase 2.4: Places buy and sell quotes at three distance tiers around the
reference price. Detects counterparty spoofing (flash-and-cancel patterns)
and enters DORMANT mode to avoid being baited into disadvantageous trades.
"""

from __future__ import annotations

import structlog

from gate_trade.strategy.contract import Strategy
from gate_trade.types import Order, OrderRequest, Side

logger = structlog.get_logger(__name__)


class DepthKeeper(Strategy):
    """Places a 3-tier quote ladder on both sides of the reference price.

    Tiers
        Near (tier 0): tight spread, small size — captures tight flow.
        Mid  (tier 1): medium spread, medium size — core inventory build.
        Far  (tier 2): wide spread, large size — opportunistic fills.

    ACTIVE / DORMANT
        In ACTIVE mode the strategy places its full quote set each tick.
        When anti-spoof detects counterparty bait-and-cancel patterns the
        strategy enters DORMANT mode and stops quoting. Hysteresis prevents
        rapid toggling.
    """

    def __init__(
        self,
        pair: str,
        tick_size: float = 0.01,
        tier_sizes: tuple[float, float, float] = (1.0, 2.0, 5.0),
        tier_spread_ticks: tuple[int, int, int] = (5, 15, 30),
        anti_spoof_window_sec: float = 30.0,
        anti_spoof_flash_threshold: int = 3,
        dormant_cooldown_sec: float = 60.0,
        enabled: bool = True,
    ) -> None:
        assert len(tier_sizes) == 3
        assert len(tier_spread_ticks) == 3

        self._pair = pair
        self._tick_size = tick_size
        self._tier_sizes = tier_sizes
        self._tier_spreads = tuple(s * tick_size for s in tier_spread_ticks)
        self._anti_spoof_window = anti_spoof_window_sec
        self._anti_spoof_threshold = anti_spoof_flash_threshold
        self._dormant_cooldown = dormant_cooldown_sec
        self._enabled = enabled

        # Market context
        self._ref_price: float = 0.0
        self._spike_active: bool = False

        # ACTIVE / DORMANT state
        self._dormant: bool = False
        self._dormant_until: float = 0.0

        # Flash detection: (price, side, timestamp) entries
        self._flash_log: list[tuple[float, Side, float]] = []

        # Track placed orders
        self._active_orders: list[OrderRequest] = []

    # ── Strategy Protocol ────────────────────────────────────────

    @property
    def name(self) -> str:
        return "depth"

    @property
    def active(self) -> bool:
        return self._enabled and not self._dormant

    def desired_orders(self) -> list[OrderRequest]:
        if not self._enabled:
            return []

        if self._ref_price <= 0:
            return []

        if self._spike_active:
            return []

        # Check dormant expiry
        if self._dormant and self._dormant_expired():
            self._dormant = False
            logger.info("depth_dormant_expired")

        if self._dormant:
            return []

        orders = self._compute_quotes()
        self._active_orders = orders
        return orders

    def on_fill(self, order: Order, filled_size: float) -> None:
        pass  # DepthKeeper doesn't ratchet — it just maintains spread

    def on_state_change(self, old_state: str, new_state: str) -> None:
        if new_state in ("EMERGENCY", "SHUTDOWN"):
            self._dormant = True

    def on_cancel(self, order: Order) -> None:
        pass

    # ── Public API ───────────────────────────────────────────────

    def update_market(self, ref_price: float, spike_active: bool = False) -> None:
        self._ref_price = ref_price
        self._spike_active = spike_active

    def report_flash(self, price: float, side: Side, timestamp: float | None = None) -> None:
        """Called when an external observer detects a flash (large order
        appearing then quickly cancelled) at *price* on *side*.

        Used for anti-spoof detection.
        """
        import time
        ts = timestamp if timestamp is not None else time.monotonic()
        self._flash_log.append((price, side, ts))
        self._prune_flash_log(ts)
        if len(self._flash_log) >= self._anti_spoof_threshold:
            self._enter_dormant("anti_spoof")

    def reset(self) -> None:
        self._dormant = False
        self._dormant_until = 0.0
        self._flash_log.clear()
        self._active_orders.clear()

    # ── Properties for test introspection ────────────────────────

    @property
    def dormant(self) -> bool:
        return self._dormant

    @property
    def tier_count(self) -> int:
        return 3

    # ── Internal ─────────────────────────────────────────────────

    def _compute_quotes(self) -> list[OrderRequest]:
        orders: list[OrderRequest] = []
        for i in range(3):
            half_spread = self._tier_spreads[i]
            size = self._tier_sizes[i]
            buy_price = self._align(self._ref_price - half_spread)
            sell_price = self._align(self._ref_price + half_spread)
            if buy_price > 0:
                orders.append(OrderRequest(
                    pair=self._pair, side=Side.BUY,
                    price=buy_price, size=size,
                ))
            if sell_price > 0:
                orders.append(OrderRequest(
                    pair=self._pair, side=Side.SELL,
                    price=sell_price, size=size,
                ))
        return orders

    def _align(self, price: float) -> float:
        tick = self._tick_size
        return round(round(price / tick) * tick, 8)

    def _enter_dormant(self, reason: str) -> None:
        import time
        if self._dormant:
            return
        self._dormant = True
        self._dormant_until = time.monotonic() + self._dormant_cooldown
        logger.warning("depth_dormant", reason=reason, cooldown_s=self._dormant_cooldown)

    def _dormant_expired(self) -> bool:
        import time
        return time.monotonic() >= self._dormant_until

    def _prune_flash_log(self, now: float) -> None:
        cutoff = now - self._anti_spoof_window
        self._flash_log = [e for e in self._flash_log if e[2] >= cutoff]
