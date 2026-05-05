import time

import pytest

from gate_trade.guardrails.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_burst_available_on_init(self):
        rl = RateLimiter(burst=5, rate=10.0)
        assert rl.available >= 4.9  # close to burst

    def test_try_acquire_depletes(self):
        rl = RateLimiter(burst=3, rate=10.0)
        assert rl.try_acquire()
        assert rl.try_acquire()
        assert rl.try_acquire()
        assert not rl.try_acquire()

    @pytest.mark.timeout(3)
    async def test_acquire_blocks_and_succeeds(self):
        rl = RateLimiter(burst=1, rate=100.0, max_wait_sec=1.0)
        assert await rl.acquire()  # consume the burst token
        t0 = time.monotonic()
        assert await rl.acquire()  # waits for refill
        elapsed = time.monotonic() - t0
        assert elapsed < 0.5  # should refill fast at rate=100

    async def test_acquire_times_out(self):
        # burst=1, then consume it; refill at 0.1/s with 50ms wait won't produce another token
        rl = RateLimiter(burst=1, rate=0.1, max_wait_sec=0.05)
        assert await rl.acquire()  # consume the burst token
        assert not await rl.acquire()  # no token within max_wait — degraded

    def test_reset_refills(self):
        rl = RateLimiter(burst=3, rate=10.0)
        for _ in range(3):
            rl.try_acquire()
        assert not rl.try_acquire()
        rl.reset()
        assert rl.available >= 2.9
