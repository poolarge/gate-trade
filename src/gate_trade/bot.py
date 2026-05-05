"""Bot — main asyncio orchestrator for the Gate Trade bot.

Wires together StateMachine, MarketData, RefPriceEngine, Strategy,
OrderEngine, RiskManager, CooldownManager, MarkoutRecorder,
ToxicDetector, ToxicResponse, and AlertManager into a single
asyncio event loop with structured logging at every tick.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import time
from typing import Any

import structlog

from gate_trade.markout.recorder import MarkoutRecorder
from gate_trade.markout.response import ToxicResponse
from gate_trade.markout.toxic import ToxicDetector
from gate_trade.persistence.event_log import BotEventLogger, BotEventType
from gate_trade.state.cooldown import CooldownManager
from gate_trade.types import BotState, RunSubState

logger = structlog.get_logger(__name__)


class Bot:
    """Main orchestrator for the Gate Trade bot.

    All external dependencies are injected via the constructor so
    every component can be swapped for a mock in tests.

    Usage::

        bot = Bot(
            state_machine=sm,
            market_data=md,
            ref_price=rp,
            strategies=[accum, depth],
            order_engine=oe,
            risk_manager=rm,
            dry_run=True,
        )
        await bot.run()
    """

    def __init__(
        self,
        state_machine: Any,       # StateMachine protocol
        market_data: Any,         # MarketData protocol
        ref_price: Any,           # RefPriceEngine protocol
        strategies: list[Any],    # list[Strategy protocol]
        order_engine: Any,        # OrderEngine protocol
        risk_manager: Any,        # RiskManager protocol
        cooldown: CooldownManager | None = None,
        markout: MarkoutRecorder | None = None,
        toxic: ToxicDetector | None = None,
        toxic_response: ToxicResponse | None = None,
        alert: Any = None,        # AlertManager protocol
        persistence: Any = None,  # Persistence protocol
        pair: str = "",
        dry_run: bool = True,
        tick_interval: float = 0.5,
    ) -> None:
        self._sm = state_machine
        self._md = market_data
        self._ref = ref_price
        self._strategies = strategies
        self._oe = order_engine
        self._risk = risk_manager
        self._cooldown = cooldown or CooldownManager()
        self._markout = markout or MarkoutRecorder()
        self._toxic = toxic or ToxicDetector()
        self._tox_resp = toxic_response or ToxicResponse()
        self._alert = alert
        self._dry_run = dry_run
        self._tick_interval = tick_interval

        self._events = BotEventLogger(pair=pair)
        if persistence is not None:
            self._events.bind(persistence)

        self._running = False
        self._tick_count = 0
        self._start_time = 0.0

    # ── Public API ──────────────────────────────────────────────

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def uptime_seconds(self) -> float:
        if self._start_time == 0.0:
            return 0.0
        return time.monotonic() - self._start_time

    @property
    def events(self) -> BotEventLogger:
        return self._events

    @property
    def running(self) -> bool:
        return self._running

    async def run(self) -> None:
        """Start the main loop. Blocks until shutdown."""
        self._running = True
        self._start_time = time.monotonic()
        if self._sm.state == BotState.INIT:
            self._sm.transition(BotState.IDLE)
        self._sm.transition(BotState.RUNNING)

        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop_event.set)

        logger.info("bot_started", dry_run=self._dry_run,
                    strategies=[s.name for s in self._strategies])

        try:
            while self._running:
                tick_start = time.monotonic()
                await self._tick()

                # Wait for next tick, but check stop_event frequently
                elapsed = time.monotonic() - tick_start
                wait = max(0.0, self._tick_interval - elapsed)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait)
                    self._running = False
                except TimeoutError:
                    pass
        except Exception:
            logger.exception("bot_fatal_error")
            await self._alert_critical("Bot fatal error — check logs")
        finally:
            await self._shutdown()

    async def shutdown(self) -> None:
        """Initiate a graceful shutdown."""
        self._running = False

    # ── Internal tick ───────────────────────────────────────────

    async def _tick(self) -> None:
        self._tick_count += 1

        # 1. Skip if bot is in emergency or not running
        if self._sm.is_emergency():
            return
        if self._sm.state not in (BotState.RUNNING, BotState.IDLE):
            return

        # 2. Get market data
        mid = self._md.mid_price()
        best_bid = self._md.best_bid()
        best_ask = self._md.best_ask()

        if mid <= 0:
            return  # No valid market data yet

        # 3. Update ref price engine
        self._ref.update(
            best_bid=best_bid,
            best_ask=best_ask,
            own_bids=self._own_prices("buy"),
            own_asks=self._own_prices("sell"),
        )
        ref = self._ref.ref_price

        # 4. Handle spike protection
        if self._ref.spike_protection_active:
            self._sm.start_cooldown_price_spike(
                self._ref.spike_cooldown_remaining_ms
            )
            self._events.record(BotEventType.SPIKE,
                              mid=round(mid, 2),
                              cooldown_ms=self._ref.spike_cooldown_remaining_ms)

        # 5. Risk evaluation
        self._risk.evaluate(
            open_orders=self._oe.open_orders(),
            balances=[],  # Balances come from REST client (not in WS loop scope)
            mid_price=mid,
        )
        if self._risk.halted:
            logger.warning("bot_halted_by_risk")
            self._sm.transition(BotState.EMERGENCY)
            self._events.record(BotEventType.RISK, reason=self._risk.halt_reason,
                              mid=round(mid, 2), state="EMERGENCY")
            await self._alert_warn("Bot halted by risk manager")
            return

        # 6. Update strategies
        strat_states: list[dict[str, Any]] = []
        for strat in self._strategies:
            if strat.active:
                strat.update_market(ref, spike_active=self._ref.spike_protection_active)
            strat_states.append({"name": strat.name, "active": strat.active})

        # 7. Check if we can place
        if not self._sm.can_place():
            self._record_tick(mid, ref, strat_states)
            return
        if not self._cooldown.can_place():
            if self._cooldown.compliance_depth_required():
                await self._place_compliance_orders()
            self._record_tick(mid, ref, strat_states)
            return

        # 8. Place/refresh orders
        await self._refresh_orders()

        # 9. Update markout recorder
        self._markout.update_mid(mid)

        # 10. Process completed markout entries
        for record in self._markout.completed():
            self._toxic.evaluate(record)
            ratio = self._toxic.toxic_ratio
            level = self._tox_resp.evaluate(ratio, self._toxic.total_count)
            if level != self._tox_resp.level:
                self._events.record(BotEventType.TOXIC,
                                  level=level.value, ratio=round(ratio, 4))
                await self._alert_info(
                    f"Toxic level changed: {level.value} (ratio={ratio:.1%})"
                )

        # 11. State machine sub-state management
        self._manage_sub_state()

        # Record tick summary
        self._record_tick(mid, ref, strat_states)

    # ── Order management ────────────────────────────────────────

    async def _refresh_orders(self) -> None:
        """Compute desired orders and reconcile with exchange."""
        self._sm.set_sub_state(RunSubState.PLACING)

        # Collect desired orders from all active strategies
        desired: list[tuple[Any, Any]] = []  # (strategy, OrderRequest)
        for strat in self._strategies:
            if strat.active:
                for req in strat.desired_orders():
                    desired.append((strat, req))

        if not desired:
            self._sm.set_sub_state(RunSubState.WAITING)
            return

        if self._dry_run:
            for strat, req in desired:
                logger.info("dry_run_would_place",
                           strategy=strat.name, side=req.side.value,
                           price=req.price, size=req.size)
                self._events.record(BotEventType.ORDER_PLACE,
                                  strategy=strat.name, side=req.side.value,
                                  price=req.price, size=req.size, dry_run=True)
            self._sm.set_sub_state(RunSubState.WAITING)
            return

        # Place orders
        for _strat, req in desired:
            try:
                await self._oe.place(req)
                self._events.record(BotEventType.ORDER_PLACE,
                                  side=req.side.value, price=req.price,
                                  size=req.size, dry_run=False)
            except Exception:
                logger.warning("place_failed", price=req.price, side=req.side.value)
                self._events.record(BotEventType.ERROR, msg="place_failed",
                                  price=req.price, side=req.side.value)

        self._sm.set_sub_state(RunSubState.WAITING)

    async def _place_compliance_orders(self) -> None:
        """Place minimal compliance depth when cooldowns suppress normal orders."""
        for strat in self._strategies:
            if not strat.active:
                continue
            for req in strat.desired_orders():
                if self._dry_run:
                    logger.info("dry_run_compliance",
                               strategy=strat.name, side=req.side.value)
                else:
                    with contextlib.suppress(Exception):
                        await self._oe.place(req)
                break  # One per strategy is enough for compliance

    # ── Helpers ─────────────────────────────────────────────────

    def _own_prices(self, side: str) -> list[float]:
        """Return prices of own open orders on the given side."""
        orders = self._oe.open_orders()
        return [o.price for o in orders if o.side.value == side]

    def _record_tick(
        self, mid: float, ref: float, strat_states: list[dict[str, Any]],
    ) -> None:
        self._events.record(BotEventType.TICK,
                          state=self._sm.state.value,
                          mid=round(mid, 2),
                          ref_price=round(ref, 2),
                          spread_bps=round(self._md.spread_bps(), 1),
                          toxic_level=self._tox_resp.level.value,
                          strategies=strat_states,
                          open_orders=len(self._oe.open_orders()))

    def _manage_sub_state(self) -> None:
        """Determine RUNNING sub-state based on order book conditions."""
        if not self._oe.open_orders():
            self._sm.set_sub_state(RunSubState.PLACING)
        else:
            self._sm.set_sub_state(RunSubState.WAITING)

    async def _shutdown(self) -> None:
        logger.info("bot_shutting_down", tick_count=self._tick_count,
                    uptime=round(self.uptime_seconds, 1))
        self._events.record(BotEventType.SHUTDOWN, tick_count=self._tick_count,
                          uptime=round(self.uptime_seconds, 1))
        self._sm.transition(BotState.SHUTDOWN)
        if not self._dry_run:
            try:
                await self._oe.cancel_all("")
            except Exception:
                logger.warning("cancel_all_failed_during_shutdown")
        await self._alert_info(
            f"Bot shut down after {self.uptime_seconds:.0f}s, {self._tick_count} ticks"
        )

    async def _alert_critical(self, msg: str) -> None:
        if self._alert:
            try:
                await self._alert.critical("Gate Trade Critical", msg)
            except Exception:
                logger.warning("alert_failed")

    async def _alert_warn(self, msg: str) -> None:
        if self._alert:
            try:
                await self._alert.warn("Gate Trade Warning", msg)
            except Exception:
                logger.warning("alert_failed")

    async def _alert_info(self, msg: str) -> None:
        if self._alert:
            try:
                await self._alert.info("Gate Trade Info", msg)
            except Exception:
                logger.warning("alert_failed")
