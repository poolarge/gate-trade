"""Tests for MarkoutRecorder — Phase 6.1."""

from __future__ import annotations

import time

from gate_trade.markout.recorder import MARKOUT_INTERVALS, MarkoutRecord, MarkoutRecorder
from gate_trade.types import Order, OrderStatus, Side


def _make_order(order_id="o1", side=Side.BUY, price=50000.0, size=0.1, filled=0.05):
    return Order(order_id=order_id, pair="BTC_USDT", side=side, price=price,
                 size=size, filled_size=filled, status=OrderStatus.OPEN)


class TestOnFill:
    def test_creates_pending_entry(self):
        rec = MarkoutRecorder()
        order = _make_order()
        rec.on_fill(order, 0.05, 50000.0)
        assert len(rec._pending) == 1

    def test_record_fields(self):
        rec = MarkoutRecorder()
        order = _make_order(order_id="abc", side=Side.SELL, price=60000.0, size=1.0, filled=0.1)
        rec.on_fill(order, 0.1, 59990.0)
        record, deadline = rec._pending[0]
        assert record.order_id == "abc"
        assert record.side == Side.SELL
        assert record.fill_price == 60000.0
        assert record.fill_size == 0.1
        assert record.mid_at_fill == 59990.0
        assert record.mids_after == {}

    def test_deadline_set_to_longest_interval_plus_buffer(self):
        rec = MarkoutRecorder()
        order = _make_order()
        t0 = time.monotonic()
        rec.on_fill(order, 0.05, 50000.0)
        _, deadline = rec._pending[0]
        assert deadline >= t0 + max(MARKOUT_INTERVALS) + 2.0


class TestUpdateMid:
    def _fill_timestamp(self, rec):
        return rec._pending[0][0].fill_timestamp

    def test_fills_1s_markout_after_1_second(self):
        rec = MarkoutRecorder()
        rec.on_fill(_make_order(), 0.05, 50000.0)
        ft = self._fill_timestamp(rec)
        rec.update_mid(50010.0, timestamp=ft + 1.0)
        record = rec._pending[0][0]
        assert 1.0 in record.mids_after
        assert record.mids_after[1.0] == 50010.0

    def test_does_not_fill_1s_before_1_second(self):
        rec = MarkoutRecorder()
        rec.on_fill(_make_order(), 0.05, 50000.0)
        ft = self._fill_timestamp(rec)
        rec.update_mid(50010.0, timestamp=ft + 0.5)
        record = rec._pending[0][0]
        assert 1.0 not in record.mids_after

    def test_fills_all_intervals_at_30_seconds(self):
        rec = MarkoutRecorder()
        rec.on_fill(_make_order(), 0.05, 50000.0)
        ft = self._fill_timestamp(rec)
        rec.update_mid(50100.0, timestamp=ft + 30.0)
        assert len(rec._completed) == 1
        record = rec._completed[0]
        assert 1.0 in record.mids_after
        assert 5.0 in record.mids_after
        assert 30.0 in record.mids_after
        assert record.mids_after[30.0] == 50100.0

    def test_intermediate_update_only_fills_past_intervals(self):
        rec = MarkoutRecorder()
        rec.on_fill(_make_order(), 0.05, 50000.0)
        ft = self._fill_timestamp(rec)
        rec.update_mid(50020.0, timestamp=ft + 3.0)
        record = rec._pending[0][0]
        assert 1.0 in record.mids_after
        assert 5.0 not in record.mids_after  # only 3s elapsed

    def test_multiple_pending_entries(self):
        rec = MarkoutRecorder()
        rec.on_fill(_make_order(order_id="o1"), 0.05, 50000.0)
        rec.on_fill(_make_order(order_id="o2"), 0.1, 50100.0)
        ft2 = rec._pending[1][0].fill_timestamp
        # Advance past 30s for the second fill
        rec.update_mid(50200.0, timestamp=ft2 + 30.0)
        # First fill should also be completed
        assert len(rec._completed) == 2

    def test_pending_cleared_when_completed(self):
        rec = MarkoutRecorder()
        rec.on_fill(_make_order(), 0.05, 50000.0)
        ft = self._fill_timestamp(rec)
        rec.update_mid(50100.0, timestamp=ft + 30.0)
        assert len(rec._pending) == 0


class TestCompleted:
    def test_returns_and_clears(self):
        rec = MarkoutRecorder()
        rec.on_fill(_make_order(), 0.05, 50000.0)
        ft = rec._pending[0][0].fill_timestamp
        rec.update_mid(50100.0, timestamp=ft + 30.0)
        result = rec.completed()
        assert len(result) == 1
        assert result[0].order_id == "o1"
        assert rec.completed() == []  # cleared

    def test_empty_when_nothing_done(self):
        rec = MarkoutRecorder()
        assert rec.completed() == []


class TestComputeMarkoutBps:
    def test_buy_unfavorable(self):
        record = MarkoutRecord(
            order_id="x", side=Side.BUY, fill_price=50000.0, fill_size=0.1,
            mid_at_fill=50000.0, mids_after={30.0: 49900.0}, fill_timestamp=0.0,
        )
        bps = MarkoutRecorder._compute_markout_bps(record)
        # BUY: fill_price - mid_after = 50000 - 49900 = 100
        # 100 / 50000 * 10000 = 20 bps
        assert bps == 20.0

    def test_buy_favorable(self):
        record = MarkoutRecord(
            order_id="x", side=Side.BUY, fill_price=50000.0, fill_size=0.1,
            mid_at_fill=50000.0, mids_after={30.0: 50100.0}, fill_timestamp=0.0,
        )
        bps = MarkoutRecorder._compute_markout_bps(record)
        # BUY: fill_price - mid_after = 50000 - 50100 = -100
        # -100 / 50000 * 10000 = -20 bps
        assert bps == -20.0

    def test_sell_favorable(self):
        record = MarkoutRecord(
            order_id="x", side=Side.SELL, fill_price=50000.0, fill_size=0.1,
            mid_at_fill=50000.0, mids_after={30.0: 49900.0}, fill_timestamp=0.0,
        )
        bps = MarkoutRecorder._compute_markout_bps(record)
        # SELL: mid_after - fill_price = 49900 - 50000 = -100
        # -100 / 50000 * 10000 = -20 bps
        assert bps == -20.0

    def test_sell_unfavorable(self):
        record = MarkoutRecord(
            order_id="x", side=Side.SELL, fill_price=50000.0, fill_size=0.1,
            mid_at_fill=50000.0, mids_after={30.0: 50100.0}, fill_timestamp=0.0,
        )
        bps = MarkoutRecorder._compute_markout_bps(record)
        # SELL: mid_after - fill_price = 50100 - 50000 = 100
        # 100 / 50000 * 10000 = 20 bps
        assert bps == 20.0

    def test_zero_mid_at_fill(self):
        record = MarkoutRecord(
            order_id="x", side=Side.BUY, fill_price=50000.0, fill_size=0.1,
            mid_at_fill=0.0, mids_after={30.0: 49900.0}, fill_timestamp=0.0,
        )
        assert MarkoutRecorder._compute_markout_bps(record) == 0.0

    def test_falls_back_to_mid_at_fill_when_30s_missing(self):
        record = MarkoutRecord(
            order_id="x", side=Side.BUY, fill_price=50000.0, fill_size=0.1,
            mid_at_fill=50000.0, mids_after={1.0: 50010.0, 5.0: 50020.0}, fill_timestamp=0.0,
        )
        # 30s not available → falls back to mid_at_fill=50000, markout = 0
        assert MarkoutRecorder._compute_markout_bps(record) == 0.0


class TestReset:
    def test_clears_pending(self):
        rec = MarkoutRecorder()
        rec.on_fill(_make_order(), 0.05, 50000.0)
        rec.reset()
        assert len(rec._pending) == 0

    def test_clears_completed(self):
        rec = MarkoutRecorder()
        rec.on_fill(_make_order(), 0.05, 50000.0)
        ft = rec._pending[0][0].fill_timestamp
        rec.update_mid(50100.0, timestamp=ft + 30.0)
        rec.reset()
        assert rec.completed() == []

    def test_clears_last_mid(self):
        rec = MarkoutRecorder()
        rec.update_mid(50000.0)
        rec.reset()
        assert rec._last_mid == 0.0
