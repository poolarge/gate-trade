"""Strategy contract — desired-orders generation and event handlers."""

from __future__ import annotations

from typing import Protocol

from gate_trade.types import Order, OrderRequest


class Strategy(Protocol):
    """Generates desired orders based on market state and own position.

    Each strategy sub-module (Accumulator, DepthKeeper, Smasher, FlashBuyer)
    implements this protocol. Strategies are stateless with respect to order
    tracking — they only express *intent*. The OrderEngine handles execution.
    """

    @property
    def name(self) -> str:
        """Unique strategy name (e.g. 'accum', 'depth', 'smasher')."""
        ...

    # ── Core: desired orders ─────────────────────────────────

    def desired_orders(self) -> list[OrderRequest]:
        """Compute the set of orders this strategy currently wants in the book.

        Called by the main loop each tick. An empty list means the strategy
        has no new intent this cycle — it never means 'cancel everything'.
        """
        ...

    # ── Event handlers ───────────────────────────────────────

    def on_fill(self, order: Order, filled_size: float) -> None:
        """Called when one of this strategy's orders is filled (partial or full).

        The strategy may adjust its internal target or ratchet in response.
        """
        ...

    def on_state_change(self, old_state: str, new_state: str) -> None:
        """Called when the bot's top-level state changes.

        Strategies can use this to reset internal counters or exit
        aggressive modes when the bot halts.
        """
        ...

    def on_cancel(self, order: Order) -> None:
        """Called when one of this strategy's orders is cancelled.

        Lets the strategy distinguish 'filled' from 'cancelled' for
        ratchet / collapse-protection logic.
        """
        ...

    # ── Health ────────────────────────────────────────────────

    @property
    def active(self) -> bool:
        """True if the strategy is currently enabled (feature-flag or
        state-dependent). Inactive strategies return empty desired_orders."""
        ...
