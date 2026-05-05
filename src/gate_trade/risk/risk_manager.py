"""RiskManager — halt/resume gatekeeper with position and order-count guards.

Phase 2.6: Evaluates risk each tick and gates order placement. Auto-resumes
after minimum cooldown when all conditions clear.
"""

from __future__ import annotations

import time

import structlog

from gate_trade.risk.contract import RiskManager
from gate_trade.types import Balance, Order, Side

logger = structlog.get_logger(__name__)


class LiveRiskManager(RiskManager):
    """Evaluates risk limits and controls halt/resume lifecycle.

    Triggers halt on:
        - Position notional exceeds *max_position_notional*
        - Open order count exceeds *max_open_orders*
        - Flash crash signal (mid drops beyond threshold from recent high)

    Auto-resume when all conditions clear and HIT_CAP_COOLDOWN expires.
    """

    def __init__(
        self,
        max_position_notional: float = 100.0,
        max_order_size_notional: float = 50.0,
        max_open_orders: int = 10,
        flash_crash_threshold_pct: float = 5.0,
        hit_cap_cooldown_ms: int = 30000,
    ) -> None:
        self._max_position = max_position_notional
        self._max_order_size = max_order_size_notional
        self._max_orders = max_open_orders
        self._flash_threshold = flash_crash_threshold_pct / 100.0
        self._hit_cap_cooldown_ms = hit_cap_cooldown_ms

        # State
        self._halted: bool = False
        self._halt_reason: str = ""
        self._halt_time: float = 0.0

        # Per-check flags
        self._position_breached: bool = False
        self._order_count_breached: bool = False
        self._flash_crash: bool = False

        # Flash crash tracking
        self._peak_mid: float = 0.0

        # Cooldown tracking
        self._cap_cooldown_until: float = 0.0
        self._cap_breached: bool = False

    # ── RiskManager Protocol ────────────────────────────────────

    def evaluate(
        self,
        open_orders: list[Order],
        balances: list[Balance],
        mid_price: float,
    ) -> None:
        self._check_position(open_orders, balances, mid_price)
        self._check_order_count(open_orders)
        self._check_flash_crash(mid_price)

        if self._position_breached or self._order_count_breached or self._flash_crash:
            if not self._halted:
                self._enter_halt()
        else:
            # All conditions clear
            if self._halted:
                self._enter_cap_cooldown()
                self._clear_halt()

    @property
    def can_trade(self) -> bool:
        return not self._halted and time.monotonic() >= self._cap_cooldown_until

    @property
    def halted(self) -> bool:
        return self._halted

    @property
    def position_limit_breached(self) -> bool:
        return self._position_breached

    @property
    def order_count_breached(self) -> bool:
        return self._order_count_breached

    @property
    def flash_crash_detected(self) -> bool:
        return self._flash_crash

    def should_resume(self) -> bool:
        return not self._halted and time.monotonic() >= self._cap_cooldown_until

    def reset(self) -> None:
        self._halted = False
        self._halt_reason = ""
        self._halt_time = 0.0
        self._position_breached = False
        self._order_count_breached = False
        self._flash_crash = False
        self._peak_mid = 0.0
        self._cap_cooldown_until = 0.0
        self._cap_breached = False

    # ── Properties for test introspection ────────────────────────

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    @property
    def cap_cooldown_remaining_ms(self) -> int:
        if time.monotonic() >= self._cap_cooldown_until:
            return 0
        return int((self._cap_cooldown_until - time.monotonic()) * 1000)

    # ── Internal ─────────────────────────────────────────────────

    def _check_position(
        self,
        open_orders: list[Order],
        balances: list[Balance],
        mid_price: float,
    ) -> None:
        """Compute total notional position from open buy orders and base balance."""
        if mid_price <= 0:
            self._position_breached = False
            return

        # Base currency (e.g., BTC) held
        base_held = sum(b.total for b in balances if b.total > 0) or 0.0

        # Orders not yet filled that would add to position
        pending_buys = sum(o.size - o.filled_size for o in open_orders
                          if o.side == Side.BUY and o.size > o.filled_size)

        total_notional = (base_held + pending_buys) * mid_price
        self._position_breached = total_notional > self._max_position

        if self._position_breached:
            self._cap_breached = True

    def _check_order_count(self, open_orders: list[Order]) -> None:
        self._order_count_breached = len(open_orders) >= self._max_orders

    def _check_flash_crash(self, mid_price: float) -> None:
        if mid_price <= 0:
            self._flash_crash = False
            return

        if mid_price > self._peak_mid:
            self._peak_mid = mid_price

        if self._peak_mid > 0:
            drop = (self._peak_mid - mid_price) / self._peak_mid
            self._flash_crash = drop >= self._flash_threshold

    def _enter_halt(self) -> None:
        self._halted = True
        self._halt_time = time.monotonic()
        parts = []
        if self._position_breached:
            parts.append("position_limit")
        if self._order_count_breached:
            parts.append("order_count")
        if self._flash_crash:
            parts.append("flash_crash")
        self._halt_reason = "|".join(parts)
        logger.warning("risk_halt", reason=self._halt_reason)

    def _clear_halt(self) -> None:
        self._halted = False
        self._halt_reason = ""
        self._halt_time = 0.0
        logger.info("risk_halt_cleared")

    def _enter_cap_cooldown(self) -> None:
        """Start HIT_CAP_COOLDOWN if position cap was previously breached."""
        if self._cap_breached:
            self._cap_cooldown_until = time.monotonic() + self._hit_cap_cooldown_ms / 1000.0
            self._cap_breached = False
            logger.info("risk_cap_cooldown", duration_ms=self._hit_cap_cooldown_ms)
