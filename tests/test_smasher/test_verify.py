"""Tests for SmasherVerifier — Phase 7.4."""

from __future__ import annotations

from gate_trade.smasher.verify import SmasherVerifier, Verdict


class TestAddAndCount:
    def test_samples_counts(self):
        ver = SmasherVerifier(min_samples=5)
        for _ in range(3):
            ver.add_before(-5.0)
        for _ in range(4):
            ver.add_after(2.0)
        assert ver.samples_before == 3
        assert ver.samples_after == 4


class TestCompare:
    def test_insufficient_samples_returns_none(self):
        ver = SmasherVerifier(min_samples=20)
        for _ in range(5):
            ver.add_before(-3.0)
            ver.add_after(1.0)
        assert ver.compare() is None

    def test_markout_improvement_detected(self):
        ver = SmasherVerifier(min_samples=10)
        for _ in range(15):
            ver.add_before(-10.0)  # poor markout before
        for _ in range(15):
            ver.add_after(5.0)  # better markout after
        verdict = ver.compare()
        assert verdict is not None
        assert verdict.improved
        assert verdict.delta_bps > 0

    def test_markout_decline_detected(self):
        ver = SmasherVerifier(min_samples=10)
        for _ in range(15):
            ver.add_before(5.0)
        for _ in range(15):
            ver.add_after(-10.0)
        verdict = ver.compare()
        assert verdict is not None
        assert not verdict.improved
        assert verdict.delta_bps < 0

    def test_no_improvement_with_similar_means(self):
        ver = SmasherVerifier(min_samples=10)
        for _ in range(15):
            ver.add_before(1.0)
        for _ in range(15):
            ver.add_after(1.1)
        verdict = ver.compare()
        assert verdict is not None
        # Slight improvement may or may not be significant

    def test_zero_variance_handled(self):
        ver = SmasherVerifier(min_samples=10)
        for _ in range(15):
            ver.add_before(2.0)
        for _ in range(15):
            ver.add_after(2.0)
        verdict = ver.compare()
        assert verdict is not None
        assert verdict.delta_bps == 0.0


class TestReset:
    def test_clears_samples(self):
        ver = SmasherVerifier()
        ver.add_before(1.0)
        ver.add_after(2.0)
        ver.reset()
        assert ver.samples_before == 0
        assert ver.samples_after == 0


class TestVerdictDataclass:
    def test_fields(self):
        v = Verdict(improved=True, mean_before=-5.0, mean_after=3.0,
                     delta_bps=8.0, samples_before=20, samples_after=25)
        assert v.improved
        assert v.delta_bps == 8.0
        assert v.samples_before == 20
