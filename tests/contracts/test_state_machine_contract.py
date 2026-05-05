"""Contract tests for StateMachine protocol."""

from __future__ import annotations

import pytest

from gate_trade.types import BotState, RunSubState
from mocks.mock_state_machine import MockStateMachine


@pytest.fixture
def sm():
    return MockStateMachine()


class TestStateMachineContract:
    def test_initial_state_is_init(self, sm):
        assert sm.state == BotState.INIT

    def test_initial_sub_state_is_none(self, sm):
        assert sm.sub_state is None

    def test_transition_changes_state(self, sm):
        result = sm.transition(BotState.IDLE)
        assert result is True
        assert sm.state == BotState.IDLE

    def test_transition_is_recorded(self, sm):
        sm.transition(BotState.RUNNING)
        assert len(sm.transitions) == 1
        assert sm.transitions[0] == (BotState.INIT, BotState.RUNNING)

    def test_set_sub_state_only_in_running(self, sm):
        sm.set_sub_state(RunSubState.PLACING)
        assert sm.sub_state is None  # not in RUNNING

    def test_set_sub_state_in_running(self, sm):
        sm.transition(BotState.RUNNING)
        sm.set_sub_state(RunSubState.PLACING)
        assert sm.sub_state == RunSubState.PLACING

    def test_can_place_in_idle_and_running(self, sm):
        sm.transition(BotState.IDLE)
        assert sm.can_place() is True
        sm.transition(BotState.RUNNING)
        assert sm.can_place() is True

    def test_can_place_false_in_emergency(self, sm):
        sm.set_state(BotState.EMERGENCY)
        assert sm.can_place() is False

    def test_can_cancel_true_in_most_states(self, sm):
        sm.set_state(BotState.RUNNING)
        assert sm.can_cancel() is True

    def test_can_cancel_false_in_emergency(self, sm):
        sm.set_state(BotState.EMERGENCY)
        assert sm.can_cancel() is False

    def test_is_emergency(self, sm):
        assert sm.is_emergency() is False
        sm.set_state(BotState.EMERGENCY)
        assert sm.is_emergency() is True

    def test_cooldown_sets_state(self, sm):
        sm.start_cooldown_fill(2000)
        assert sm.state == BotState.COOLDOWN_FILL
        assert sm.cooldown_remaining_ms() == 2000

    def test_start_cooldown_cancel(self, sm):
        sm.start_cooldown_cancel(1000)
        assert sm.state == BotState.COOLDOWN_CANCEL

    def test_start_cooldown_self_trade(self, sm):
        sm.start_cooldown_self_trade(5000)
        assert sm.state == BotState.COOLDOWN_SELF_TRADE
