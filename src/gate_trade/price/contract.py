"""RefPriceEngine contract — reference price with self-trade protection."""

from __future__ import annotations

from typing import Protocol


class RefPriceEngine(Protocol):
    """Computes a reference price from the orderbook, excluding own orders.

    Also provides spike detection: if the market moves too far too fast,
    the engine can enter a short cooldown to avoid trading into a wick.
    """

    # ── Reference price ──────────────────────────────────────

    @property
    def ref_price(self) -> float:
        """Current reference price (mid or weighted-mid, own orders excluded)."""
        ...

    @property
    def ref_bid(self) -> float:
        """Bid at which the bot is willing to buy (ref minus half-spread offset)."""
        ...

    @property
    def ref_ask(self) -> float:
        """Ask at which the bot is willing to sell (ref plus half-spread offset)."""
        ...

    # ── Update ───────────────────────────────────────────────

    def update(
        self,
        best_bid: float,
        best_ask: float,
        own_bids: list[float],
        own_asks: list[float],
    ) -> None:
        """Feed current market top-of-book and own resting orders to
        recompute the reference price (excluding self-trade influence)."""
        ...

    # ── Spike protection ─────────────────────────────────────

    @property
    def spike_protection_active(self) -> bool:
        """True when a price spike has been detected and the engine
        is in cooldown."""
        ...

    @property
    def spike_cooldown_remaining_ms(self) -> int:
        """Milliseconds remaining in spike-protection cooldown."""
        ...

    def reset(self) -> None:
        """Clear internal state (used on reconnect)."""
        ...
