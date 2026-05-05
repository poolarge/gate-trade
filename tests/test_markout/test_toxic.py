"""Tests for ToxicDetector — Phase 6.2."""

from __future__ import annotations

from gate_trade.markout.recorder import MarkoutRecord
from gate_trade.markout.toxic import ToxicDetector
from gate_trade.types import Side


def _make_record(order_id="o1", side=Side.BUY, fill_price=50000.0, fill_size=0.1,
                 mid_at_fill=50000.0, mids_after=None):
    if mids_after is None:
        mids_after = {30.0: 50000.0}
    return MarkoutRecord(
        order_id=order_id, side=side, fill_price=fill_price,
        fill_size=fill_size, mid_at_fill=mid_at_fill,
        mids_after=mids_after, fill_timestamp=0.0,
    )


# For BUY: markout = (fill_price - mid_after) / mid_at_fill * 10000
#   mid_after=50200 → (50000-50200)/50000*10000 = -40 bps (adverse, <= -20)
# For fast_reversal: abs(mid_1s - mid_at_fill) / mid_at_fill * 10000
#   mid_1s=50050 → abs(50050-50000)/50000*10000 = 10 bps (>= 10)
ADVERSE_30S = 50200.0
REVERSAL_1S = 50050.0


class TestEvaluate:
    def test_all_signals_true_returns_toxic(self):
        det = ToxicDetector(adverse_markout_bps=-20.0, large_size_multiple=3.0,
                            fast_reversal_bps=10.0, window_fills=20)
        for _ in range(5):
            det.evaluate(_make_record(fill_size=0.01, mid_at_fill=50000.0,
                                       mids_after={30.0: 50001.0}))
        record = _make_record(
            fill_size=1.0,
            mid_at_fill=50000.0,
            mids_after={30.0: ADVERSE_30S, 1.0: REVERSAL_1S},
        )
        assert det.evaluate(record) is True
        assert det.toxic_count == 1

    def test_not_toxic_when_markout_not_adverse(self):
        det = ToxicDetector(adverse_markout_bps=-20.0)
        for _ in range(5):
            det.evaluate(_make_record(fill_size=0.01, mid_at_fill=50000.0,
                                       mids_after={30.0: 50001.0}))
        # markout = (50000-50095)/50000*10000 = -19 bps, > -20, not adverse
        record = _make_record(fill_size=1.0, mid_at_fill=50000.0,
                              mids_after={30.0: 50095.0, 1.0: REVERSAL_1S})
        assert det.evaluate(record) is False

    def test_not_toxic_when_size_not_large(self):
        det = ToxicDetector(large_size_multiple=3.0)
        for _ in range(5):
            det.evaluate(_make_record(fill_size=0.1, mid_at_fill=50000.0,
                                       mids_after={30.0: 50001.0}))
        # avg fill size ≈ 0.1, threshold 0.3, 0.05 < 0.3
        record = _make_record(fill_size=0.05, mid_at_fill=50000.0,
                              mids_after={30.0: ADVERSE_30S, 1.0: REVERSAL_1S})
        assert det.evaluate(record) is False

    def test_not_toxic_when_no_fast_reversal(self):
        det = ToxicDetector(fast_reversal_bps=10.0)
        for _ in range(5):
            det.evaluate(_make_record(fill_size=0.01, mid_at_fill=50000.0,
                                       mids_after={30.0: 50001.0}))
        # 1s mid = 50000 → reversal = 0 bps, < 10
        record = _make_record(fill_size=1.0, mid_at_fill=50000.0,
                              mids_after={30.0: ADVERSE_30S, 1.0: 50000.0})
        assert det.evaluate(record) is False

    def test_returns_false_without_min_samples(self):
        det = ToxicDetector()
        for _ in range(2):
            det.evaluate(_make_record(fill_size=0.01))
        record = _make_record(fill_size=1.0, mid_at_fill=50000.0,
                              mids_after={30.0: ADVERSE_30S, 1.0: REVERSAL_1S})
        assert det.evaluate(record) is False

    def test_no_fast_reversal_when_mid_1s_missing(self):
        det = ToxicDetector(fast_reversal_bps=10.0)
        for _ in range(5):
            det.evaluate(_make_record(fill_size=0.01, mid_at_fill=50000.0,
                                       mids_after={30.0: 50001.0}))
        record = _make_record(fill_size=1.0, mid_at_fill=50000.0,
                              mids_after={30.0: ADVERSE_30S})  # no 1s entry
        assert det.evaluate(record) is False


class TestToxicRatio:
    def test_zero_when_no_fills(self):
        det = ToxicDetector()
        assert det.toxic_ratio == 0.0

    def test_ratio_calculation(self):
        det = ToxicDetector()
        for _ in range(5):
            det.evaluate(_make_record(fill_size=0.01, mid_at_fill=50000.0,
                                       mids_after={30.0: 50001.0}))
        # Toxic fill
        det.evaluate(_make_record(fill_size=1.0, mid_at_fill=50000.0,
                                   mids_after={30.0: ADVERSE_30S, 1.0: REVERSAL_1S}))
        # Non-toxic (small size)
        det.evaluate(_make_record(fill_size=0.01, mid_at_fill=50000.0,
                                   mids_after={30.0: ADVERSE_30S, 1.0: REVERSAL_1S}))
        assert det.toxic_count == 1
        assert det.total_count == 7
        assert det.toxic_ratio == 1 / 7


class TestReset:
    def test_clears_all_state(self):
        det = ToxicDetector()
        for _ in range(5):
            det.evaluate(_make_record(fill_size=0.01, mid_at_fill=50000.0,
                                       mids_after={30.0: 50001.0}))
        det.evaluate(_make_record(fill_size=1.0, mid_at_fill=50000.0,
                                   mids_after={30.0: ADVERSE_30S, 1.0: REVERSAL_1S}))
        det.reset()
        assert det.toxic_count == 0
        assert det.total_count == 0
        assert det.toxic_ratio == 0.0
        assert len(det._fill_sizes) == 0


class TestLargeSizeEdgeCases:
    def test_zero_average_guard_returns_false(self):
        det = ToxicDetector(large_size_multiple=3.0)
        # All fills have zero size → avg=0 → guard returns False for large_size
        for _ in range(4):
            det.evaluate(_make_record(fill_size=0.0, mid_at_fill=50000.0,
                                       mids_after={30.0: 50001.0}))
        record = _make_record(fill_size=0.0, mid_at_fill=50000.0,
                              mids_after={30.0: ADVERSE_30S, 1.0: REVERSAL_1S})
        assert det.evaluate(record) is False
