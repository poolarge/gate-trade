"""Unit tests for LiveRefPriceEngine — Phase 2.2."""

from __future__ import annotations

import time

import pytest

from gate_trade.price.ref_price_engine import LiveRefPriceEngine


@pytest.fixture
def rpe() -> LiveRefPriceEngine:
    return LiveRefPriceEngine()


class TestBasicMid:
    def test_mid_with_valid_bid_ask(self, rpe: LiveRefPriceEngine) -> None:
        rpe.update(50000.0, 50100.0, [], [])
        assert rpe.ref_price == 50050.0
        assert rpe.ref_bid == 50000.0
        assert rpe.ref_ask == 50100.0

    def test_mid_ask_only(self, rpe: LiveRefPriceEngine) -> None:
        rpe.update(0.0, 50100.0, [], [])
        assert rpe.ref_price == 50100.0

    def test_mid_bid_only(self, rpe: LiveRefPriceEngine) -> None:
        rpe.update(50000.0, 0.0, [], [])
        assert rpe.ref_price == 50000.0

    def test_zero_book_does_nothing(self, rpe: LiveRefPriceEngine) -> None:
        rpe.update(0.0, 0.0, [], [])
        assert rpe.ref_price == 0.0


class TestSelfFillExclusion:
    """Acceptance: injecting own-taker-fill does not pull ref price."""

    def test_exclude_own_bid_at_best(self, rpe: LiveRefPriceEngine) -> None:
        # Our own bid at 50000 is the market best; exclude it
        rpe.update(50000.0, 50100.0, [50000.0], [])
        # Ref should use ask only since bid is excluded
        assert rpe.ref_price == 50100.0

    def test_exclude_own_ask_at_best(self, rpe: LiveRefPriceEngine) -> None:
        rpe.update(50000.0, 50100.0, [], [50100.0])
        assert rpe.ref_price == 50000.0

    def test_exclude_both_own_at_best(self, rpe: LiveRefPriceEngine) -> None:
        # First establish a baseline with clean data
        rpe.update(50000.0, 50200.0, [], [])
        assert rpe.ref_price == 50100.0
        # Now exclude both — engine preserves last valid ref
        rpe.update(50000.0, 50100.0, [50000.0], [50100.0])
        assert rpe.ref_price == 50100.0  # last valid ref preserved

    def test_own_bid_not_at_best_no_effect(self, rpe: LiveRefPriceEngine) -> None:
        # Our bid at 49900 is NOT the market best (50000 is)
        rpe.update(50000.0, 50100.0, [49900.0], [])
        assert rpe.ref_price == 50050.0
        assert rpe.ref_bid == 50000.0

    def test_self_fill_does_not_pull_ref(self, rpe: LiveRefPriceEngine) -> None:
        """Core acceptance test: own taker fill that becomes new best
        bid should NOT pull the ref price."""
        rpe.update(50000.0, 50100.0, [], [])
        assert rpe.ref_price == 50050.0
        # A taker buy fills at 50100, making best bid = 50100 but it's our order
        rpe.update(50100.0, 50200.0, [50100.0], [])
        assert rpe.ref_price == 50200.0  # uses ask only, bid excluded


class TestSpikeProtection:
    def test_no_spike_with_normal_movement(self, rpe: LiveRefPriceEngine) -> None:
        rpe.update(50000.0, 50100.0, [], [])
        assert rpe.spike_protection_active is False
        rpe.update(50001.0, 50101.0, [], [])
        assert rpe.spike_protection_active is False

    def test_spike_detected_with_large_move(self, rpe: LiveRefPriceEngine) -> None:
        rpe.update(50000.0, 50100.0, [], [])
        # Move > 50 bps: mid 50050 → 49790, change ≈ 51.9 bps
        rpe.update(49740.0, 49840.0, [], [])
        assert rpe.spike_protection_active is True
        assert rpe.spike_cooldown_remaining_ms > 0

    def test_spike_cooldown_expires(self) -> None:
        rpe2 = LiveRefPriceEngine(spike_threshold_bps=10.0, spike_cooldown_sec=0.01)
        rpe2.update(50000.0, 50100.0, [], [])
        rpe2.update(49900.0, 50000.0, [], [])  # large move triggers spike
        assert rpe2.spike_protection_active is True
        time.sleep(0.02)
        assert rpe2.spike_protection_active is False

    def test_reset_clears_spike(self, rpe: LiveRefPriceEngine) -> None:
        rpe.update(50000.0, 50100.0, [], [])
        rpe.update(49740.0, 49840.0, [], [])
        assert rpe.spike_protection_active is True
        rpe.reset()
        assert rpe.spike_protection_active is False
        assert rpe.ref_price == 0.0


class TestTWAP:
    def test_twap_equals_mid_with_single_update(self, rpe: LiveRefPriceEngine) -> None:
        rpe.update(50000.0, 50100.0, [], [])
        twap = rpe.twap
        assert twap == 50050.0

    def test_twap_averages_multiple_updates(self, rpe: LiveRefPriceEngine) -> None:
        rpe.update(50000.0, 50100.0, [], [])
        rpe.update(50010.0, 50110.0, [], [])
        rpe.update(50020.0, 50120.0, [], [])
        twap = rpe.twap
        assert 50050.0 < twap < 50080.0  # roughly average

    def test_twap_initial_zero(self, rpe: LiveRefPriceEngine) -> None:
        assert rpe.twap == 0.0
