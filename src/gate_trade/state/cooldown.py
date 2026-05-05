"""CooldownManager — three independent, overlapping cooldown timers.

Phase 2.7: Provides price-move-up cooldown, taker-fill cooldown, and a
compliance-quote existence timer that run in parallel. Unlike the state
machine's single cooldown state, these timers can all be active at once.
"""

from __future__ import annotations

import time

import structlog

logger = structlog.get_logger(__name__)


class CooldownManager:
    """Three independent cooldown timers with simple query API.

    Price-move-up cooldown
        Activated when the ref price spikes upward. Prevents placing new
        orders into a potential bull trap.

    Taker-fill cooldown
        Activated after our own taker fill. Prevents rapid consecutive
        market orders that would incur excessive fees.

    Compliance-quote timer
        Ensures at least one quote is maintained on each side for exchange
        compliance. When active, the bot MUST place compliance depth even
        if other cooldowns would normally suppress ordering.
    """

    def __init__(self) -> None:
        self._price_until: float = 0.0
        self._fill_until: float = 0.0
        self._compliance_until: float = 0.0

    # ── Start timers ────────────────────────────────────────────

    def start_price_cooldown(self, duration_ms: int) -> None:
        self._price_until = time.monotonic() + duration_ms / 1000.0
        logger.info("cooldown_price_start", duration_ms=duration_ms)

    def start_fill_cooldown(self, duration_ms: int) -> None:
        self._fill_until = time.monotonic() + duration_ms / 1000.0
        logger.info("cooldown_fill_start", duration_ms=duration_ms)

    def start_compliance_timer(self, duration_ms: int) -> None:
        self._compliance_until = time.monotonic() + duration_ms / 1000.0
        logger.info("cooldown_compliance_start", duration_ms=duration_ms)

    # ── Query (auto-expiring) ───────────────────────────────────

    @property
    def price_cooldown_active(self) -> bool:
        return time.monotonic() < self._price_until

    @property
    def fill_cooldown_active(self) -> bool:
        return time.monotonic() < self._fill_until

    @property
    def compliance_timer_active(self) -> bool:
        return time.monotonic() < self._compliance_until

    # ── Gating queries ──────────────────────────────────────────

    def can_place(self) -> bool:
        """True if new orders may be placed for non-compliance reasons.

        Price and fill cooldowns block discretionary order placement.
        The compliance timer does NOT block — compliance depth is always
        required regardless of other cooldowns.
        """
        return not self.price_cooldown_active and not self.fill_cooldown_active

    def compliance_depth_required(self) -> bool:
        """True if at least one quote per side must be maintained.

        Active when the compliance timer is running, regardless of other
        cooldowns. This satisfies the acceptance: 'compliance depth
        maintained even during cooldown periods.'
        """
        return self.compliance_timer_active

    def any_active(self) -> bool:
        return self.price_cooldown_active or self.fill_cooldown_active or self.compliance_timer_active

    # ── Remaining time (ms) ─────────────────────────────────────

    def price_cooldown_remaining_ms(self) -> int:
        if not self.price_cooldown_active:
            return 0
        return max(0, int((self._price_until - time.monotonic()) * 1000))

    def fill_cooldown_remaining_ms(self) -> int:
        if not self.fill_cooldown_active:
            return 0
        return max(0, int((self._fill_until - time.monotonic()) * 1000))

    def compliance_remaining_ms(self) -> int:
        if not self.compliance_timer_active:
            return 0
        return max(0, int((self._compliance_until - time.monotonic()) * 1000))

    # ── Reset ───────────────────────────────────────────────────

    def reset(self) -> None:
        self._price_until = 0.0
        self._fill_until = 0.0
        self._compliance_until = 0.0
