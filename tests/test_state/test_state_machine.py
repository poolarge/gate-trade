"""Unit tests for LiveStateMachine — Phase 2.1 + 2.5."""

from __future__ import annotations

import time

import pytest

from gate_trade.guardrails.exceptions import IllegalTransition
from gate_trade.state.state_machine import LiveStateMachine
from gate_trade.types import BotState, RunSubState


@pytest.fixture
def sm():
    return LiveStateMachine()


class TestInitialState:
    def test_starts_in_init(self, sm):
        assert sm.state == BotState.INIT

    def test_sub_state_is_none_initially(self, sm):
        assert sm.sub_state is None


class TestBasicTransitions:
    def test_init_to_idle(self, sm):
        assert sm.transition(BotState.IDLE) is True
        assert sm.state == BotState.IDLE

    def test_idle_to_running(self, sm):
        sm.transition(BotState.IDLE)
        assert sm.transition(BotState.RUNNING) is True
        assert sm.state == BotState.RUNNING

    def test_running_to_idle(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        assert sm.transition(BotState.IDLE) is True
        assert sm.state == BotState.IDLE

    def test_running_to_emergency(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        assert sm.transition(BotState.EMERGENCY) is True
        assert sm.state == BotState.EMERGENCY

    def test_idempotent_same_state(self, sm):
        assert sm.transition(BotState.INIT) is True
        assert sm.state == BotState.INIT

    def test_idempotent_when_idle(self, sm):
        sm.transition(BotState.IDLE)
        assert sm.transition(BotState.IDLE) is True


class TestIllegalTransitions:
    def test_init_to_running_raises(self, sm):
        with pytest.raises(IllegalTransition):
            sm.transition(BotState.RUNNING)

    def test_init_to_emergency_raises(self, sm):
        with pytest.raises(IllegalTransition):
            sm.transition(BotState.EMERGENCY)

    def test_shutdown_stuck(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.SHUTDOWN)
        with pytest.raises(IllegalTransition):
            sm.transition(BotState.RUNNING)


class TestSubStates:
    def test_set_sub_state_only_in_running(self, sm):
        sm.set_sub_state(RunSubState.PLACING)
        assert sm.sub_state is None

    def test_set_sub_state_in_running(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.set_sub_state(RunSubState.PLACING)
        assert sm.sub_state == RunSubState.PLACING

    def test_sub_state_cleared_on_exit_running(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.set_sub_state(RunSubState.PLACING)
        sm.transition(BotState.IDLE)
        assert sm.sub_state is None


class TestCooldowns:
    def test_start_fill_cooldown(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.start_cooldown_fill(2000)
        assert sm.state == BotState.COOLDOWN_FILL
        assert sm.cooldown_remaining_ms() > 0

    def test_cooldown_remaining_decreases(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.start_cooldown_fill(5000)
        remaining = sm.cooldown_remaining_ms()
        assert 0 < remaining <= 5000

    def test_cooldown_expired_returns_zero(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.start_cooldown_fill(1)  # 1ms
        time.sleep(0.01)
        assert sm.cooldown_remaining_ms() == 0

    def test_emergency_blocks_cooldown(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.EMERGENCY)
        sm.start_cooldown_fill(5000)
        assert sm.state == BotState.EMERGENCY  # cooldown blocked

    def test_cooldown_can_transition_to_running_after_expiry(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        sm.start_cooldown_fill(1)
        time.sleep(0.01)
        assert sm.transition(BotState.RUNNING) is True
        assert sm.state == BotState.RUNNING


class TestQueries:
    def test_can_place_in_idle(self, sm):
        sm.transition(BotState.IDLE)
        assert sm.can_place() is True

    def test_can_place_in_running(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.RUNNING)
        assert sm.can_place() is True

    def test_can_place_false_in_emergency(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.EMERGENCY)
        assert sm.can_place() is False

    def test_can_cancel_in_most_states(self, sm):
        sm.transition(BotState.IDLE)
        assert sm.can_cancel() is True
        sm.transition(BotState.RUNNING)
        assert sm.can_cancel() is True

    def test_can_cancel_false_in_emergency(self, sm):
        sm.transition(BotState.IDLE)
        sm.transition(BotState.EMERGENCY)
        assert sm.can_cancel() is False

    def test_is_emergency(self, sm):
        assert sm.is_emergency() is False
        sm.transition(BotState.IDLE)
        sm.transition(BotState.EMERGENCY)
        assert sm.is_emergency() is True


class TestTransitionMatrix:
    """Exhaustive transition validation for all 9 states."""
    _ALL = set(BotState)

    def _valid(self, sm, _from, _to):
        try:
            sm.transition(_from)
        except (IllegalTransition):
            pass
        try:
            sm.transition(_to)
            return True
        except IllegalTransition:
            return False

    def test_valid_from_init(self, sm):
        # INIT → INIT is idempotent (always true), INIT → IDLE is valid
        valid = {BotState.INIT, BotState.IDLE}
        for target in BotState:
            sm2 = LiveStateMachine()
            try:
                result = sm2.transition(target)
                assert result == (target in valid), f"INIT → {target.value}: {result}"
            except IllegalTransition:
                assert target not in valid, f"INIT → {target.value}: unexpected IllegalTransition"

    def test_valid_from_idle(self):
        valid = {BotState.IDLE, BotState.RUNNING, BotState.EMERGENCY, BotState.SHUTDOWN}
        for target in BotState:
            sm = LiveStateMachine()
            sm.transition(BotState.IDLE)
            try:
                result = sm.transition(target)
                assert result == (target in valid), f"IDLE → {target.value}: got {result}, expected {target in valid}"
            except IllegalTransition:
                assert target not in valid, f"IDLE → {target.value}: unexpected IllegalTransition"

    def test_valid_from_running(self):
        valid = {BotState.RUNNING, BotState.IDLE, BotState.COOLDOWN_FILL, BotState.COOLDOWN_CANCEL,
                 BotState.COOLDOWN_SELF_TRADE, BotState.EMERGENCY, BotState.RECONNECT}
        for target in BotState:
            sm = LiveStateMachine()
            sm.transition(BotState.IDLE)
            sm.transition(BotState.RUNNING)
            try:
                result = sm.transition(target)
                assert result == (target in valid), f"RUNNING → {target.value}: got {result}, expected {target in valid}"
            except IllegalTransition:
                assert target not in valid, f"RUNNING → {target.value}: unexpected IllegalTransition"
