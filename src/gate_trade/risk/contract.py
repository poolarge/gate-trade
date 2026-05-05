"""RiskManager contract — halt/resume gatekeeper."""

from __future__ import annotations

from typing import Protocol

from gate_trade.types import Balance, Order


class RiskManager(Protocol):
    """Evaluates risk conditions every tick and decides whether the bot
    may continue trading or must halt.

    All checks are non-blocking snapshots. The main loop calls
    :meth:`evaluate` each tick and gates order placement on
    :meth:`can_trade`.
    """

    # ── Core evaluation ──────────────────────────────────────

    def evaluate(
        self,
        open_orders: list[Order],
        balances: list[Balance],
        mid_price: float,
    ) -> None:
        """Run all risk checks against current state.

        Called every main-loop tick. Updates internal halt/resume flags.
        """
        ...

    # ── Gating ────────────────────────────────────────────────

    @property
    def can_trade(self) -> bool:
        """True if no risk condition currently blocks trading."""
        ...

    @property
    def halted(self) -> bool:
        """True when the bot should transition to EMERGENCY / HALTED."""
        ...

    # ── Specific checks (exposed for monitoring) ──────────────

    @property
    def position_limit_breached(self) -> bool:
        """True when notional position exceeds *max_position_notional*."""
        ...

    @property
    def order_count_breached(self) -> bool:
        """True when open-order count exceeds *max_open_orders*."""
        ...

    @property
    def flash_crash_detected(self) -> bool:
        """True when a flash-crash signal is active."""
        ...

    # ── Resume logic ──────────────────────────────────────────

    def should_resume(self) -> bool:
        """True if all conditions that triggered the halt have cleared
        and the minimum cooldown has elapsed."""
        ...

    def reset(self) -> None:
        """Clear all halt flags (called on explicit resume)."""
        ...
