"""StateMachine — bot lifecycle manager with cooldown gating."""

from __future__ import annotations

import time
from typing import ClassVar

import structlog

from gate_trade.guardrails.exceptions import IllegalTransition
from gate_trade.state.contract import StateMachine
from gate_trade.types import BotState, RunSubState

logger = structlog.get_logger(__name__)

# Minimal valid transitions (Phase 2.1) — expanded in Phase 2.5
_VALID_TRANSITIONS: dict[BotState, frozenset[BotState]] = {
    BotState.INIT:                  frozenset({BotState.IDLE}),
    BotState.IDLE:                  frozenset({BotState.RUNNING, BotState.EMERGENCY, BotState.SHUTDOWN}),
    BotState.RUNNING:               frozenset({BotState.IDLE, BotState.COOLDOWN_FILL, BotState.COOLDOWN_CANCEL, BotState.COOLDOWN_SELF_TRADE, BotState.COOLDOWN_PRICE_SPIKE, BotState.EMERGENCY, BotState.RECONNECT}),
    BotState.COOLDOWN_FILL:         frozenset({BotState.IDLE, BotState.RUNNING, BotState.EMERGENCY}),
    BotState.COOLDOWN_CANCEL:       frozenset({BotState.IDLE, BotState.RUNNING, BotState.EMERGENCY}),
    BotState.COOLDOWN_SELF_TRADE:   frozenset({BotState.IDLE, BotState.RUNNING, BotState.EMERGENCY}),
    BotState.COOLDOWN_PRICE_SPIKE:  frozenset({BotState.IDLE, BotState.RUNNING, BotState.EMERGENCY}),
    BotState.EMERGENCY:             frozenset({BotState.IDLE, BotState.SHUTDOWN}),
    BotState.SHUTDOWN:              frozenset(),
    BotState.RECONNECT:             frozenset({BotState.IDLE, BotState.RUNNING, BotState.EMERGENCY}),
}

_COOLDOWN_STATES: frozenset[BotState] = frozenset({
    BotState.COOLDOWN_FILL,
    BotState.COOLDOWN_CANCEL,
    BotState.COOLDOWN_SELF_TRADE,
    BotState.COOLDOWN_PRICE_SPIKE,
})


class LiveStateMachine(StateMachine):
    """Concrete state machine with transition validation and cooldowns.

    Phase 2.1: Minimal state flow with basic transition guards.
    Phase 2.5 will add full 9-state exhaustive validation.
    """

    VALID_TRANSITIONS: ClassVar = _VALID_TRANSITIONS

    def __init__(self) -> None:
        self._state = BotState.INIT
        self._sub_state: RunSubState | None = None
        self._cooldown_until: float = 0.0
        self._cooldown_type: BotState | None = None

    # ── Current state ────────────────────────────────────────────

    @property
    def state(self) -> BotState:
        return self._state

    @property
    def sub_state(self) -> RunSubState | None:
        if self._state != BotState.RUNNING:
            return None
        return self._sub_state

    # ── Transitions ──────────────────────────────────────────────

    def transition(self, target: BotState) -> bool:
        """Request a state change. Returns True if legal and applied."""
        if self._state == target:
            return True

        valid = self.VALID_TRANSITIONS.get(self._state, frozenset())
        if target not in valid:
            raise IllegalTransition(
                f"Cannot transition from {self._state.value} to {target.value}"
            )

        old = self._state
        self._state = target

        # Clear sub-state and cooldowns on transition
        if target != BotState.RUNNING:
            self._sub_state = None
        if target not in _COOLDOWN_STATES:
            self._cooldown_until = 0.0
            self._cooldown_type = None

        logger.info("state_transition", old=old.value, new=target.value)
        return True

    def set_sub_state(self, target: RunSubState) -> None:
        if self._state != BotState.RUNNING:
            logger.debug("set_sub_state_ignored", state=self._state.value, target=target.value)
            return
        old = self._sub_state
        self._sub_state = target
        logger.info("sub_state_change", old=old.value if old else None, new=target.value)

    # ── Cooldowns ────────────────────────────────────────────────

    def start_cooldown_fill(self, duration_ms: int) -> None:
        self._enter_cooldown(BotState.COOLDOWN_FILL, duration_ms)

    def start_cooldown_cancel(self, duration_ms: int) -> None:
        self._enter_cooldown(BotState.COOLDOWN_CANCEL, duration_ms)

    def start_cooldown_self_trade(self, duration_ms: int) -> None:
        self._enter_cooldown(BotState.COOLDOWN_SELF_TRADE, duration_ms)

    def start_cooldown_price_spike(self, duration_ms: int) -> None:
        self._enter_cooldown(BotState.COOLDOWN_PRICE_SPIKE, duration_ms)

    def cooldown_remaining_ms(self) -> int:
        if self._cooldown_until <= 0:
            return 0
        remaining = int((self._cooldown_until - time.monotonic()) * 1000)
        return max(remaining, 0)

    # ── Queries ──────────────────────────────────────────────────

    def can_place(self) -> bool:
        """True if the bot may submit new orders right now."""
        if self._state == BotState.EMERGENCY:
            return False
        if self._state == BotState.SHUTDOWN:
            return False
        if self._state in _COOLDOWN_STATES:
            return self.cooldown_remaining_ms() <= 0
        return self._state in (BotState.IDLE, BotState.RUNNING)

    def can_cancel(self) -> bool:
        """True if the bot may cancel orders right now."""
        return self._state not in (BotState.EMERGENCY, BotState.SHUTDOWN)

    def is_emergency(self) -> bool:
        return self._state == BotState.EMERGENCY

    # ── Internal ─────────────────────────────────────────────────

    def _enter_cooldown(self, kind: BotState, duration_ms: int) -> None:
        """Transition to a cooldown state for *duration_ms* ms."""
        if self._state in (BotState.EMERGENCY, BotState.SHUTDOWN):
            logger.debug("cooldown_blocked", state=self._state.value)
            return
        old = self._state
        self._state = kind
        self._cooldown_until = time.monotonic() + duration_ms / 1000.0
        self._cooldown_type = kind
        logger.info("cooldown_start", kind=kind.value, duration_ms=duration_ms, from_state=old.value)
