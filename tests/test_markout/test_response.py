"""Tests for ToxicResponse — Phase 6.3."""

from __future__ import annotations

import time

from gate_trade.markout.response import ToxicLevel, ToxicResponse


class TestEvaluate:
    def test_normal_below_elevated_threshold(self):
        resp = ToxicResponse(elevated_ratio=0.2, dormant_ratio=0.4, halt_ratio=0.6, min_samples=5)
        level = resp.evaluate(toxic_ratio=0.1, total_count=10)
        assert level == ToxicLevel.NORMAL

    def test_elevated_at_threshold(self):
        resp = ToxicResponse(elevated_ratio=0.2, dormant_ratio=0.4, halt_ratio=0.6, min_samples=5)
        level = resp.evaluate(toxic_ratio=0.2, total_count=10)
        assert level == ToxicLevel.ELEVATED

    def test_dormant_at_threshold(self):
        resp = ToxicResponse(elevated_ratio=0.2, dormant_ratio=0.4, halt_ratio=0.6, min_samples=5)
        level = resp.evaluate(toxic_ratio=0.45, total_count=10)
        assert level == ToxicLevel.DORMANT

    def test_halt_at_threshold(self):
        resp = ToxicResponse(elevated_ratio=0.2, dormant_ratio=0.4, halt_ratio=0.6, min_samples=5)
        level = resp.evaluate(toxic_ratio=0.6, total_count=10)
        assert level == ToxicLevel.HALT

    def test_insufficient_samples_keeps_current_level(self):
        resp = ToxicResponse(elevated_ratio=0.2, min_samples=5)
        level = resp.evaluate(toxic_ratio=0.9, total_count=3)
        assert level == ToxicLevel.NORMAL

    def test_escalation_chain(self):
        resp = ToxicResponse(elevated_ratio=0.2, dormant_ratio=0.4, halt_ratio=0.6, min_samples=5)
        assert resp.evaluate(toxic_ratio=0.1, total_count=10) == ToxicLevel.NORMAL
        assert resp.evaluate(toxic_ratio=0.3, total_count=10) == ToxicLevel.ELEVATED
        assert resp.evaluate(toxic_ratio=0.5, total_count=10) == ToxicLevel.DORMANT
        assert resp.evaluate(toxic_ratio=0.7, total_count=10) == ToxicLevel.HALT

    def test_recovery_to_lower_level(self):
        resp = ToxicResponse(elevated_ratio=0.2, dormant_ratio=0.4, halt_ratio=0.6, min_samples=5)
        resp.evaluate(toxic_ratio=0.5, total_count=10)
        assert resp.level == ToxicLevel.DORMANT
        # Ratio drops below elevated threshold
        resp.evaluate(toxic_ratio=0.1, total_count=15)
        assert resp.level == ToxicLevel.NORMAL


class TestSpreadMultiplier:
    def test_normal_is_one(self):
        resp = ToxicResponse()
        resp.evaluate(toxic_ratio=0.1, total_count=10)
        assert resp.spread_multiplier == 1.0

    def test_dormant_is_999(self):
        resp = ToxicResponse(elevated_ratio=0.2, dormant_ratio=0.4, min_samples=5)
        resp.evaluate(toxic_ratio=0.5, total_count=10)
        assert resp.spread_multiplier == 999.0

    def test_halt_is_999(self):
        resp = ToxicResponse(elevated_ratio=0.2, halt_ratio=0.6, min_samples=5)
        resp.evaluate(toxic_ratio=0.7, total_count=10)
        assert resp.spread_multiplier == 999.0

    def test_elevated_starts_at_one(self):
        resp = ToxicResponse(elevated_ratio=0.2, min_samples=5)
        resp.evaluate(toxic_ratio=0.3, total_count=10)
        # Immediately after entering ELEVATED, elapsed ~0
        assert 1.0 <= resp.spread_multiplier < 1.05

    def test_elevated_caps_at_two(self):
        resp = ToxicResponse(elevated_ratio=0.2, min_samples=5)
        resp.evaluate(toxic_ratio=0.3, total_count=10)
        # Simulate that we've been elevated for 120 seconds by reaching in
        resp._elevated_since = time.monotonic() - 120.0
        assert resp.spread_multiplier == 2.0


class TestAutoRecovery:
    def test_elevated_recovers_after_cooldown(self):
        resp = ToxicResponse(elevated_ratio=0.2, cooldown_sec=0.0, min_samples=5)
        resp.evaluate(toxic_ratio=0.3, total_count=10)
        assert resp.level == ToxicLevel.ELEVATED
        # With cooldown=0, next evaluate with low ratio should recover
        resp.evaluate(toxic_ratio=0.1, total_count=15)
        assert resp.level == ToxicLevel.NORMAL

    def test_no_auto_recovery_from_dormant(self):
        resp = ToxicResponse(elevated_ratio=0.2, dormant_ratio=0.4, cooldown_sec=0.0, min_samples=5)
        resp.evaluate(toxic_ratio=0.5, total_count=10)
        assert resp.level == ToxicLevel.DORMANT
        # Even with cooldown=0, DORMANT doesn't auto-recover
        resp.evaluate(toxic_ratio=0.1, total_count=15)
        assert resp.level == ToxicLevel.NORMAL  # Manual evaluate can still lower

    def test_no_auto_recovery_from_halt(self):
        resp = ToxicResponse(elevated_ratio=0.2, halt_ratio=0.6, cooldown_sec=0.0, min_samples=5)
        resp.evaluate(toxic_ratio=0.7, total_count=10)
        assert resp.level == ToxicLevel.HALT
        resp.evaluate(toxic_ratio=0.1, total_count=15)
        assert resp.level == ToxicLevel.NORMAL  # Manual evaluate can still lower


class TestReset:
    def test_returns_to_normal(self):
        resp = ToxicResponse(elevated_ratio=0.2, dormant_ratio=0.4, halt_ratio=0.6, min_samples=5)
        resp.evaluate(toxic_ratio=0.5, total_count=10)
        resp.reset()
        assert resp.level == ToxicLevel.NORMAL


class TestLevelProperty:
    def test_initial_level_is_normal(self):
        resp = ToxicResponse()
        assert resp.level == ToxicLevel.NORMAL
