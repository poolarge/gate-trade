"""Tests for Bot orchestrator."""

from __future__ import annotations

import asyncio

import pytest

from gate_trade.bot import Bot
from gate_trade.types import BotState, OrderRequest, Side
from mocks.mock_market_data import MockMarketData
from mocks.mock_order_engine import MockOrderEngine
from mocks.mock_ref_price import MockRefPriceEngine
from mocks.mock_risk_manager import MockRiskManager
from mocks.mock_state_machine import MockStateMachine
from mocks.mock_strategy import MockStrategy


def _make_bot(dry_run=True):
    sm = MockStateMachine()
    md = MockMarketData()
    ref = MockRefPriceEngine(ref=50000.0)
    strat = MockStrategy(name="test")
    oe = MockOrderEngine()
    risk = MockRiskManager()
    return Bot(sm, md, ref, [strat], oe, risk, dry_run=dry_run, tick_interval=0.01)


class TestInit:
    def test_starts_in_dry_run_mode(self):
        bot = _make_bot(dry_run=True)
        assert bot._dry_run is True

    def test_live_mode(self):
        bot = _make_bot(dry_run=False)
        assert bot._dry_run is False


class TestDryRun:
    @pytest.mark.asyncio
    async def test_does_not_place_orders(self):
        bot = _make_bot(dry_run=True)
        bot._strategies[0].set_orders([
            OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        ])
        bot._sm.set_state(BotState.RUNNING)
        await bot._tick()
        assert len(bot._oe.place_calls) == 0


class TestTick:
    @pytest.mark.asyncio
    async def test_increments_tick_count(self):
        bot = _make_bot()
        bot._sm.set_state(BotState.RUNNING)
        await bot._tick()
        assert bot.tick_count == 1

    @pytest.mark.asyncio
    async def test_skips_order_logic_when_emergency(self):
        bot = _make_bot(dry_run=False)
        bot._sm.set_state(BotState.EMERGENCY)
        bot._strategies[0].set_orders([
            OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        ])
        await bot._tick()
        # Tick count increments, but no orders placed
        assert bot.tick_count == 1
        assert len(bot._oe.place_calls) == 0

    @pytest.mark.asyncio
    async def test_skips_when_no_mid(self):
        bot = _make_bot()
        bot._sm.set_state(BotState.RUNNING)
        bot._md.set_book([], [])  # empty book → mid = 0.0
        await bot._tick()
        # Should return early, but tick count still increments
        assert bot.tick_count == 1

    @pytest.mark.asyncio
    async def test_updates_strategy_with_ref_price(self):
        bot = _make_bot()
        bot._sm.set_state(BotState.RUNNING)
        bot._md.set_book([(50000.0, 1.0)], [(50100.0, 0.5)])
        await bot._tick()
        strat = bot._strategies[0]
        assert len(strat.market_updates) > 0

    @pytest.mark.asyncio
    async def test_risk_halt_triggers_emergency(self):
        bot = _make_bot()
        bot._sm.set_state(BotState.RUNNING)
        bot._md.set_book([(50000.0, 1.0)], [(50100.0, 0.5)])
        bot._risk._halted = True
        await bot._tick()
        assert bot._sm.state == BotState.EMERGENCY

    @pytest.mark.asyncio
    async def test_places_orders_in_live_mode(self):
        bot = _make_bot(dry_run=False)
        bot._sm.set_state(BotState.RUNNING)
        bot._md.set_book([(50000.0, 1.0)], [(50100.0, 0.5)])
        bot._strategies[0].set_orders([
            OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        ])
        await bot._tick()
        assert len(bot._oe.place_calls) == 1

    @pytest.mark.asyncio
    async def test_skips_inactive_strategies(self):
        bot = _make_bot(dry_run=False)
        bot._sm.set_state(BotState.RUNNING)
        bot._md.set_book([(50000.0, 1.0)], [(50100.0, 0.5)])
        bot._strategies[0].set_active(False)
        bot._strategies[0].set_orders([
            OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        ])
        await bot._tick()
        assert len(bot._oe.place_calls) == 0

    @pytest.mark.asyncio
    async def test_cooldown_blocks_orders(self):
        bot = _make_bot(dry_run=False)
        bot._sm.set_state(BotState.RUNNING)
        bot._md.set_book([(50000.0, 1.0)], [(50100.0, 0.5)])
        bot._strategies[0].set_orders([
            OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        ])
        bot._cooldown.start_price_cooldown(5000)
        await bot._tick()
        assert len(bot._oe.place_calls) == 0


class TestRun:
    @pytest.mark.asyncio
    async def test_runs_and_shuts_down(self):
        bot = _make_bot()
        bot._sm.set_state(BotState.RUNNING)

        # Start bot in background, let it run a few ticks, then stop
        async def _run():
            await bot.run()

        task = asyncio.create_task(_run())
        await asyncio.sleep(0.05)
        await bot.shutdown()
        await asyncio.wait_for(task, timeout=2.0)

        assert bot.tick_count > 0
        assert bot._sm.state == BotState.SHUTDOWN

    @pytest.mark.asyncio
    async def test_empty_strategies_no_error(self):
        sm = MockStateMachine()
        md = MockMarketData()
        ref = MockRefPriceEngine(ref=50000.0)
        oe = MockOrderEngine()
        risk = MockRiskManager()
        bot = Bot(sm, md, ref, [], oe, risk, dry_run=True, tick_interval=0.01)
        sm.set_state(BotState.RUNNING)

        task = asyncio.create_task(bot.run())
        await asyncio.sleep(0.05)
        await bot.shutdown()
        await asyncio.wait_for(task, timeout=2.0)

        assert bot.tick_count > 0
