"""Tests for TrickleExecutor — Phase 7.3."""

from __future__ import annotations

import pytest

from gate_trade.smasher.trickle import TrickleExecutor


class TestNextChunk:
    def test_returns_size_and_delay(self):
        te = TrickleExecutor(total=1.0, min_chunk=0.1, max_chunk=0.3)
        result = te.next_chunk()
        assert result is not None
        size, delay = result
        assert 0.05 <= size <= 1.0
        assert delay >= 0

    def test_eventually_exhausts_total(self):
        te = TrickleExecutor(total=1.0, min_chunk=0.1, max_chunk=0.3,
                             min_delay_sec=0.01, max_delay_sec=0.02)
        total_allocated = 0.0
        while chunk := te.next_chunk():
            size, delay = chunk
            total_allocated += size
            assert delay >= 0
        assert abs(total_allocated - 1.0) < 1e-8
        assert te.remaining == 0.0
        assert te.next_chunk() is None

    def test_progress_increases(self):
        te = TrickleExecutor(total=1.0, min_chunk=0.1, max_chunk=0.3)
        assert te.progress == 0.0
        te.next_chunk()
        assert te.progress > 0.0

    def test_large_min_chunk_exhausts_in_one_or_two(self):
        te = TrickleExecutor(total=1.0, min_chunk=0.5, max_chunk=0.6)
        chunks = 0
        while te.next_chunk():
            chunks += 1
        assert chunks <= 2

    def test_returns_none_when_done(self):
        te = TrickleExecutor(total=0.5, min_chunk=0.1, max_chunk=0.3)
        while te.next_chunk():
            pass
        assert te.next_chunk() is None
        assert te.progress == 1.0

    def test_delay_scales_with_chunk_size(self):
        te = TrickleExecutor(total=10.0, min_chunk=0.1, max_chunk=2.0,
                             min_delay_sec=1.0, max_delay_sec=10.0)
        # Run a few chunks to get representative delays
        delays = []
        for _ in range(20):
            chunk = te.next_chunk()
            if chunk is None:
                break
            _, delay = chunk
            delays.append(delay)
        assert all(1.0 <= d <= 10.0 for d in delays)


class TestConstructor:
    def test_zero_total_raises(self):
        with pytest.raises(ValueError, match="total must be positive"):
            TrickleExecutor(total=0.0, min_chunk=0.1, max_chunk=0.3)

    def test_negative_total_raises(self):
        with pytest.raises(ValueError, match="total must be positive"):
            TrickleExecutor(total=-1.0, min_chunk=0.1, max_chunk=0.3)

    def test_invalid_chunk_range_raises(self):
        with pytest.raises(ValueError, match="invalid chunk range"):
            TrickleExecutor(total=1.0, min_chunk=10.0, max_chunk=1.0)

    def test_invalid_delay_range_raises(self):
        with pytest.raises(ValueError, match="invalid delay range"):
            TrickleExecutor(total=1.0, min_chunk=0.1, max_chunk=0.3,
                            min_delay_sec=5.0, max_delay_sec=1.0)


class TestReset:
    def test_resets_to_full_total(self):
        te = TrickleExecutor(total=1.0, min_chunk=0.1, max_chunk=0.3)
        while te.next_chunk():
            pass
        assert te.remaining == 0.0
        te.reset()
        assert te.remaining == 1.0
        assert te.progress == 0.0
