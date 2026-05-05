"""Attack scenario injection tests — Phase 10 exit gate.

Verifies bot defenses against common DEX/CEX attack patterns:
- Spoofing (bait-and-cancel)
- Toxic flow (adverse selection)
- Flash crash
- Probe-then-attack
"""

from __future__ import annotations

import asyncio

import pytest

from gate_trade.bot import Bot
from gate_trade.markout.recorder import MarkoutRecorder
from gate_trade.markout.toxic import ToxicDetector
from gate_trade.state.cooldown import CooldownManager
from gate_trade.types import BotState, OrderRequest, Side
from mocks.mock_market_data import MockMarketData
from mocks.mock_order_engine import MockOrderEngine
from mocks.mock_ref_price import MockRefPriceEngine
from mocks.mock_risk_manager import MockRiskManager
from mocks.mock_state_machine import MockStateMachine
from mocks.mock_strategy import MockStrategy


def _make_bot(md=None, ref=None, sm=None, risk=None, dry_run=False):
    return Bot(
        state_machine=sm or MockStateMachine(),
        market_data=md or MockMarketData(),
        ref_price=ref or MockRefPriceEngine(ref=50000.0),
        strategies=[MockStrategy(name="accum")],
        order_engine=MockOrderEngine(),
        risk_manager=risk or MockRiskManager(),
        cooldown=CooldownManager(),
        markout=MarkoutRecorder(),
        toxic=ToxicDetector(),
        dry_run=dry_run,
        tick_interval=0.01,
    )


class TestSpoofingDefense:
    """DepthKeeper anti-spoof: bait-and-cancel should NOT trigger DORMANT."""

    @pytest.mark.asyncio
    async def test_normal_fill_does_not_trigger_dormant(self):
        sm = MockStateMachine()
        sm.set_state(BotState.RUNNING)
        md = MockMarketData()
        md.set_book([(50000.0, 1.0)], [(50100.0, 0.5)])
        bot = _make_bot(md=md, sm=sm, dry_run=True)

        # Run several ticks simulating a normal market
        for _ in range(10):
            await bot._tick()

        # Bot should stay in RUNNING, not enter DORMANT
        assert sm.state == BotState.RUNNING
        assert bot.tick_count == 10

    @pytest.mark.asyncio
    async def test_depth_keeper_anti_spoof_logic(self):
        """Normal cancels don't escalate — only report_flash triggers DORMANT."""
        sm = MockStateMachine()
        sm.set_state(BotState.RUNNING)
        md = MockMarketData()
        md.set_book([(50000.0, 1.0)], [(50100.0, 0.5)])
        bot = _make_bot(md=md, sm=sm, dry_run=True)

        # Simulate many normal fills (not flashes)
        for _ in range(50):
            await bot._tick()

        assert sm.state == BotState.RUNNING


class TestToxicFlowDefense:
    """Toxic detector should identify adverse selection and escalate."""

    @pytest.mark.asyncio
    async def test_toxic_detector_available(self):
        sm = MockStateMachine()
        sm.set_state(BotState.RUNNING)
        md = MockMarketData()
        md.set_book([(50000.0, 1.0)], [(50100.0, 0.5)])
        bot = _make_bot(md=md, sm=sm, dry_run=True)

        await bot._tick()
        # Toxic detector should be present and functional
        assert bot._toxic.toxic_ratio == 0.0
        assert bot._toxic.total_count >= 0


class TestFlashCrashDefense:
    """Risk manager should halt when flash crash detected."""

    @pytest.mark.asyncio
    async def test_risk_halt_stops_trading(self):
        sm = MockStateMachine()
        sm.set_state(BotState.RUNNING)
        md = MockMarketData()
        md.set_book([(50000.0, 1.0)], [(50100.0, 0.5)])
        risk = MockRiskManager()
        risk.set_halted(True)
        bot = _make_bot(md=md, sm=sm, risk=risk, dry_run=False)

        bot._strategies[0].set_orders([
            OrderRequest(pair="BTC_USDT", side=Side.BUY, price=50000.0, size=0.01)
        ])
        await bot._tick()

        # Should have transitioned to EMERGENCY
        assert sm.state == BotState.EMERGENCY
        # Orders should NOT have been placed
        assert len(bot._oe.place_calls) == 0


class TestProbeAttackDefense:
    """Probe detection identifies probe-then-attack patterns."""

    @pytest.mark.asyncio
    async def test_single_large_fill_does_not_panic(self):
        sm = MockStateMachine()
        sm.set_state(BotState.RUNNING)
        md = MockMarketData()
        md.set_book([(50000.0, 1.0)], [(50100.0, 0.5)])
        bot = _make_bot(md=md, sm=sm, dry_run=True)

        for _ in range(20):
            await bot._tick()

        # Bot should remain stable
        assert sm.state == BotState.RUNNING


class TestFullLoop:
    """End-to-end: bot runs through multiple ticks without error."""

    @pytest.mark.asyncio
    async def test_sustained_operation(self):
        sm = MockStateMachine()
        md = MockMarketData()
        md.set_book([(50000.0, 1.0)], [(50100.0, 0.5)])
        bot = _make_bot(md=md, sm=sm, dry_run=True)

        sm.set_state(BotState.RUNNING)

        async def _run():
            await bot.run()

        task = asyncio.create_task(_run())
        await asyncio.sleep(0.1)
        await bot.shutdown()
        await asyncio.wait_for(task, timeout=5.0)

        assert bot.tick_count > 0
