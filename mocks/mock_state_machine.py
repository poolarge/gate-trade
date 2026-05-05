"""Mock StateMachine — manual state control for testing."""

from __future__ import annotations

from gate_trade.state.contract import StateMachine
from gate_trade.types import BotState, RunSubState


class MockStateMachine(StateMachine):
    """State machine that accepts any transition (no validation)."""

    def __init__(self) -> None:
        self._state = BotState.INIT
        self._sub_state: RunSubState | None = None
        self._cooldown_remaining = 0
        self.transitions: list[tuple[BotState, BotState]] = []

    @property
    def state(self) -> BotState:
        return self._state

    @property
    def sub_state(self) -> RunSubState | None:
        return self._sub_state

    def transition(self, target: BotState) -> bool:
        old = self._state
        self.transitions.append((old, target))
        self._state = target
        return True

    def set_sub_state(self, target: RunSubState) -> None:
        if self._state == BotState.RUNNING:
            self._sub_state = target

    def start_cooldown_fill(self, duration_ms: int) -> None:
        self._state = BotState.COOLDOWN_FILL
        self._cooldown_remaining = duration_ms

    def start_cooldown_cancel(self, duration_ms: int) -> None:
        self._state = BotState.COOLDOWN_CANCEL
        self._cooldown_remaining = duration_ms

    def start_cooldown_self_trade(self, duration_ms: int) -> None:
        self._state = BotState.COOLDOWN_SELF_TRADE
        self._cooldown_remaining = duration_ms

    def start_cooldown_price_spike(self, duration_ms: int) -> None:
        self._state = BotState.COOLDOWN_PRICE_SPIKE
        self._cooldown_remaining = duration_ms

    def cooldown_remaining_ms(self) -> int:
        return self._cooldown_remaining

    def can_place(self) -> bool:
        return self._state in (BotState.IDLE, BotState.RUNNING)

    def can_cancel(self) -> bool:
        return self._state not in (BotState.EMERGENCY, BotState.SHUTDOWN)

    def is_emergency(self) -> bool:
        return self._state == BotState.EMERGENCY

    # ── Test helpers ─────────────────────────────────────────

    def set_state(self, state: BotState) -> None:
        self._state = state
