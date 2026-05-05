"""Unit tests for CooldownManager — Phase 2.7."""

from __future__ import annotations

import time

import pytest

from gate_trade.state.cooldown import CooldownManager


@pytest.fixture
def cm() -> CooldownManager:
    return CooldownManager()


class TestIndependentTimers:
    def test_all_inactive_initially(self, cm: CooldownManager) -> None:
        assert cm.any_active() is False
        assert cm.can_place() is True

    def test_price_cooldown_blocks_place(self, cm: CooldownManager) -> None:
        cm.start_price_cooldown(5000)
        assert cm.price_cooldown_active is True
        assert cm.can_place() is False

    def test_fill_cooldown_blocks_place(self, cm: CooldownManager) -> None:
        cm.start_fill_cooldown(5000)
        assert cm.fill_cooldown_active is True
        assert cm.can_place() is False

    def test_both_cooldowns_block_place(self, cm: CooldownManager) -> None:
        cm.start_price_cooldown(5000)
        cm.start_fill_cooldown(5000)
        assert cm.can_place() is False
        assert cm.price_cooldown_active is True
        assert cm.fill_cooldown_active is True

    def test_cooldown_expires(self, cm: CooldownManager) -> None:
        cm.start_price_cooldown(1)
        time.sleep(0.01)
        assert cm.price_cooldown_active is False
        assert cm.can_place() is True

    def test_remaining_ms_decreases(self, cm: CooldownManager) -> None:
        cm.start_fill_cooldown(5000)
        remaining = cm.fill_cooldown_remaining_ms()
        assert 0 < remaining <= 5000


class TestCompliance:
    def test_compliance_timer_active(self, cm: CooldownManager) -> None:
        cm.start_compliance_timer(5000)
        assert cm.compliance_timer_active is True
        assert cm.compliance_depth_required() is True

    def test_compliance_does_not_block_place(self, cm: CooldownManager) -> None:
        """Compliance timer must NOT block order placement — depth must be
        maintained even during other cooldowns."""
        cm.start_compliance_timer(5000)
        assert cm.can_place() is True
        assert cm.any_active() is True

    def test_compliance_depth_required_during_cooldowns(self, cm: CooldownManager) -> None:
        """Core acceptance: compliance depth required even when other
        cooldowns are active."""
        cm.start_price_cooldown(5000)
        cm.start_fill_cooldown(5000)
        cm.start_compliance_timer(5000)
        # Price and fill cooldowns block discretionary placement
        assert cm.can_place() is False
        # But compliance depth is still required
        assert cm.compliance_depth_required() is True

    def test_compliance_expires(self, cm: CooldownManager) -> None:
        cm.start_compliance_timer(1)
        time.sleep(0.01)
        assert cm.compliance_timer_active is False
        assert cm.compliance_depth_required() is False


class TestRemaining:
    def test_price_remaining_initially_zero(self, cm: CooldownManager) -> None:
        assert cm.price_cooldown_remaining_ms() == 0

    def test_fill_remaining_initially_zero(self, cm: CooldownManager) -> None:
        assert cm.fill_cooldown_remaining_ms() == 0

    def test_compliance_remaining_initially_zero(self, cm: CooldownManager) -> None:
        assert cm.compliance_remaining_ms() == 0


class TestReset:
    def test_reset_clears_all(self, cm: CooldownManager) -> None:
        cm.start_price_cooldown(5000)
        cm.start_fill_cooldown(5000)
        cm.start_compliance_timer(5000)
        assert cm.any_active() is True
        cm.reset()
        assert cm.any_active() is False
        assert cm.can_place() is True
        assert cm.compliance_depth_required() is False
