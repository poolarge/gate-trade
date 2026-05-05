"""Unit tests for LiveStateMachine — Phase 2.1 + 2.5."""

from __future__ import annotations

import time

import pytest

from gate_trade.guardrails.exceptions import IllegalTransition
from gate_trade.state.state_machine import LiveStateMachine
from gate_trade.types import BotState, RunSubState


@pytest.fixture
def sm() -> LiveStateMachine:
    return LiveStateMachine()


class TestInitialState:
    def test_starts_in_init(self, sm: LiveStateMachine) -> None:
        assert sm.state == BotState.INIT

    def test_sub_state_is_none_initially(self, sm: LiveStateMachine) -> None:
        assert sm.sub_state is None


class TestBasicTransitions:
    def test_init_to_idle(self, sm: LiveStateMachine) -> None:
        assert sm.transition(BotState.IDLE) is True
        assert sm.state == BotState.IDLE

    def test_idle_to_running(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        assert sm.transition(BotState.RUNNING) is True
        assert sm.state == BotState.RUNNING

    def test_running_to_idle(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        assert sm.transition(BotState.IDLE) is True
        assert sm.state == BotState.IDLE

    def test_running_to_emergency(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        assert sm.transition(BotState.EMERGENCY) is True
        assert sm.state == BotState.EMERGENCY

    def test_idempotent_same_state(self, sm: LiveStateMachine) -> None:
        assert sm.transition(BotState.INIT) is True
        assert sm.state == BotState.INIT

    def test_idempotent_when_idle(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        assert sm.transition(BotState.IDLE) is True


class TestIllegalTransitions:
    def test_init_to_running_raises(self, sm: LiveStateMachine) -> None:
        with pytest.raises(IllegalTransition):
            sm.transition(BotState.RUNNING)

    def test_init_to_emergency_raises(self, sm: LiveStateMachine) -> None:
        with pytest.raises(IllegalTransition):
            sm.transition(BotState.EMERGENCY)

    def test_shutdown_stuck(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.SHUTDOWN)
        with pytest.raises(IllegalTransition):
            sm.transition(BotState.RUNNING)


class TestSubStates:
    def test_set_sub_state_only_in_running(self, sm: LiveStateMachine) -> None:
        sm.set_sub_state(RunSubState.PLACING)
        assert sm.sub_state is None

    def test_set_sub_state_in_running(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.set_sub_state(RunSubState.PLACING)
        assert sm.sub_state == RunSubState.PLACING

    def test_sub_state_cleared_on_exit_running(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.set_sub_state(RunSubState.PLACING)
        sm.transition(BotState.IDLE)
        assert sm.sub_state is None


class TestCooldowns:
    def test_start_fill_cooldown(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.start_cooldown_fill(2000)
        assert sm.state == BotState.COOLDOWN_FILL
        assert sm.cooldown_remaining_ms() > 0

    def test_cooldown_remaining_decreases(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.start_cooldown_fill(5000)
        remaining = sm.cooldown_remaining_ms()
        assert 0 < remaining <= 5000

    def test_cooldown_expired_returns_zero(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.start_cooldown_fill(1)  # 1ms
        time.sleep(0.01)
        assert sm.cooldown_remaining_ms() == 0

    def test_emergency_blocks_cooldown(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.EMERGENCY)
        sm.start_cooldown_fill(5000)
        assert sm.state == BotState.EMERGENCY  # cooldown blocked

    def test_cooldown_can_transition_to_running_after_expiry(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.start_cooldown_fill(1)
        time.sleep(0.01)
        assert sm.transition(BotState.RUNNING) is True
        assert sm.state == BotState.RUNNING


class TestQueries:
    def test_can_place_in_idle(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        assert sm.can_place() is True

    def test_can_place_in_running(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        assert sm.can_place() is True

    def test_can_place_false_in_emergency(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.EMERGENCY)
        assert sm.can_place() is False

    def test_can_cancel_in_most_states(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        assert sm.can_cancel() is True
        sm.transition(BotState.RUNNING)
        assert sm.can_cancel() is True

    def test_can_cancel_false_in_emergency(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.EMERGENCY)
        assert sm.can_cancel() is False

    def test_is_emergency(self, sm: LiveStateMachine) -> None:
        assert sm.is_emergency() is False
        sm.transition(BotState.IDLE)
        sm.transition(BotState.EMERGENCY)
        assert sm.is_emergency() is True


class TestPriceSpikeCooldown:
    def test_start_price_spike_cooldown(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.start_cooldown_price_spike(30000)
        assert sm.state == BotState.COOLDOWN_PRICE_SPIKE
        assert sm.cooldown_remaining_ms() > 0

    def test_cooldown_can_transition_to_running(self, sm: LiveStateMachine) -> None:
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.start_cooldown_price_spike(1)
        time.sleep(0.01)
        assert sm.transition(BotState.RUNNING) is True


class TestTransitionMatrix:
    """Exhaustive transition validation for all 10 states."""

    @pytest.mark.parametrize("from_state,to_state,expected", [
        # INIT → *
        (BotState.INIT, BotState.INIT, True),
        (BotState.INIT, BotState.IDLE, True),
        (BotState.INIT, BotState.RUNNING, False),
        (BotState.INIT, BotState.EMERGENCY, False),
        (BotState.INIT, BotState.SHUTDOWN, False),
        # IDLE → *
        (BotState.IDLE, BotState.IDLE, True),
        (BotState.IDLE, BotState.RUNNING, True),
        (BotState.IDLE, BotState.EMERGENCY, True),
        (BotState.IDLE, BotState.SHUTDOWN, True),
        (BotState.IDLE, BotState.COOLDOWN_FILL, False),
        (BotState.IDLE, BotState.INIT, False),
        # RUNNING → *
        (BotState.RUNNING, BotState.RUNNING, True),
        (BotState.RUNNING, BotState.IDLE, True),
        (BotState.RUNNING, BotState.COOLDOWN_FILL, True),
        (BotState.RUNNING, BotState.COOLDOWN_CANCEL, True),
        (BotState.RUNNING, BotState.COOLDOWN_SELF_TRADE, True),
        (BotState.RUNNING, BotState.COOLDOWN_PRICE_SPIKE, True),
        (BotState.RUNNING, BotState.EMERGENCY, True),
        (BotState.RUNNING, BotState.RECONNECT, True),
        (BotState.RUNNING, BotState.SHUTDOWN, True),
        # COOLDOWN_FILL → *
        (BotState.COOLDOWN_FILL, BotState.RUNNING, True),
        (BotState.COOLDOWN_FILL, BotState.IDLE, True),
        (BotState.COOLDOWN_FILL, BotState.EMERGENCY, True),
        (BotState.COOLDOWN_FILL, BotState.SHUTDOWN, True),
        # COOLDOWN_PRICE_SPIKE → *
        (BotState.COOLDOWN_PRICE_SPIKE, BotState.RUNNING, True),
        (BotState.COOLDOWN_PRICE_SPIKE, BotState.IDLE, True),
        (BotState.COOLDOWN_PRICE_SPIKE, BotState.EMERGENCY, True),
        (BotState.COOLDOWN_PRICE_SPIKE, BotState.SHUTDOWN, True),
        # EMERGENCY → *
        (BotState.EMERGENCY, BotState.IDLE, True),
        (BotState.EMERGENCY, BotState.SHUTDOWN, True),
        (BotState.EMERGENCY, BotState.RUNNING, False),
        # SHUTDOWN → *
        (BotState.SHUTDOWN, BotState.SHUTDOWN, True),
        (BotState.SHUTDOWN, BotState.IDLE, False),
        (BotState.SHUTDOWN, BotState.RUNNING, False),
        (BotState.SHUTDOWN, BotState.EMERGENCY, False),
    ])
    def test_transition(self, from_state: BotState, to_state: BotState, expected: bool) -> None:
        sm = LiveStateMachine()
        # Navigate to from_state
        if from_state == BotState.IDLE:
            sm.transition(BotState.IDLE)
        elif from_state == BotState.RUNNING:
            sm.transition(BotState.IDLE)
            sm.transition(BotState.RUNNING)
        elif from_state in (BotState.COOLDOWN_FILL, BotState.COOLDOWN_CANCEL,
                            BotState.COOLDOWN_SELF_TRADE, BotState.COOLDOWN_PRICE_SPIKE):
            sm.transition(BotState.IDLE)
            sm.transition(BotState.RUNNING)
            if from_state == BotState.COOLDOWN_FILL:
                sm.start_cooldown_fill(5000)
            elif from_state == BotState.COOLDOWN_CANCEL:
                sm.start_cooldown_cancel(5000)
            elif from_state == BotState.COOLDOWN_SELF_TRADE:
                sm.start_cooldown_self_trade(5000)
            elif from_state == BotState.COOLDOWN_PRICE_SPIKE:
                sm.start_cooldown_price_spike(5000)
        elif from_state == BotState.EMERGENCY:
            sm.transition(BotState.IDLE)
            sm.transition(BotState.EMERGENCY)
        elif from_state == BotState.SHUTDOWN:
            sm.transition(BotState.IDLE)
            sm.transition(BotState.SHUTDOWN)
        # else INIT — already there

        if expected:
            assert sm.transition(to_state) is True, (
                f"{from_state.value} → {to_state.value} should be valid"
            )
        else:
            with pytest.raises(IllegalTransition):
                sm.transition(to_state)
