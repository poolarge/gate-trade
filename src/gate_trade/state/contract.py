"""StateMachine contract — bot lifecycle with cooldown gating."""

from __future__ import annotations

from typing import Protocol

from gate_trade.types import BotState, RunSubState


class StateMachine(Protocol):
    """Determines what the bot is allowed to do right now.

    Nine main states (INIT → IDLE → RUNNING → ... → SHUTDOWN) plus
    RUNNING sub-states (PLACING, WAITING, CANCELLING_STALE, REFRESHING).
    Three independent cooldown timers gate transitions out of the
    COOLDOWN_* states.
    """

    # ── Current state ────────────────────────────────────────

    @property
    def state(self) -> BotState:
        """Current top-level state."""
        ...

    @property
    def sub_state(self) -> RunSubState | None:
        """Sub-state when *state* is RUNNING, else None."""
        ...

    # ── Transitions ──────────────────────────────────────────

    def transition(self, target: BotState) -> bool:
        """Request a state change. Returns True if the transition is
        legal and was applied. Idempotent: same→same returns True."""
        ...

    def set_sub_state(self, target: RunSubState) -> None:
        """Set RUNNING sub-state. No-op if state != RUNNING."""
        ...

    # ── Cooldowns ────────────────────────────────────────────

    def start_cooldown_fill(self, duration_ms: int) -> None:
        """Enter COOLDOWN_FILL for *duration_ms* ms."""
        ...

    def start_cooldown_cancel(self, duration_ms: int) -> None:
        """Enter COOLDOWN_CANCEL for *duration_ms* ms."""
        ...

    def start_cooldown_self_trade(self, duration_ms: int) -> None:
        """Enter COOLDOWN_SELF_TRADE for *duration_ms* ms."""
        ...

    def cooldown_remaining_ms(self) -> int:
        """Remaining ms in current cooldown, or 0 if not in a cooldown state."""
        ...

    # ── Queries ──────────────────────────────────────────────

    def can_place(self) -> bool:
        """True if the bot may submit new orders right now."""
        ...

    def can_cancel(self) -> bool:
        """True if the bot may cancel orders right now."""
        ...

    def is_emergency(self) -> bool:
        """True if state == EMERGENCY (all trading halted)."""
        ...
