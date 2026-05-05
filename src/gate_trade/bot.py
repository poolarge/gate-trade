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

from gate_trade.client.contract import GateClient
from gate_trade.market.contract import MarketData
from gate_trade.markout.recorder import MarkoutRecorder
from gate_trade.markout.response import ToxicResponse
from gate_trade.markout.toxic import ToxicDetector
from gate_trade.order.contract import OrderEngine
from gate_trade.persistence.contract import Persistence
from gate_trade.persistence.event_log import BotEventLogger, BotEventType
from gate_trade.price.contract import RefPriceEngine
from gate_trade.risk.contract import RiskManager
from gate_trade.state.contract import StateMachine
from gate_trade.state.cooldown import CooldownManager
from gate_trade.strategy.contract import Strategy
from gate_trade.types import Balance, BotState, RunSubState

logger = structlog.get_logger(__name__)

_BALANCE_REFRESH_INTERVAL = 10  # ticks between balance fetches


class Bot:
    """Main orchestrator for the Gate Trade bot.

    All external dependencies are injected via the constructor so
    every component can be swapped for a mock in tests.
    """

    def __init__(
        self,
        state_machine: StateMachine,
        market_data: MarketData,
        ref_price: RefPriceEngine,
        strategies: list[Strategy],
        order_engine: OrderEngine,
        risk_manager: RiskManager,
        cooldown: CooldownManager | None = None,
        markout: MarkoutRecorder | None = None,
        toxic: ToxicDetector | None = None,
        toxic_response: ToxicResponse | None = None,
        alert: Any = None,        # AlertManager protocol
        persistence: Persistence | None = None,
        client: GateClient | None = None,
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
        self._client = client
        self._pair = pair
        self._dry_run = dry_run
        self._tick_interval = tick_interval

        self._balances: list[Balance] = []
        self._persist = persistence

        self._events = BotEventLogger(pair=pair)
        if persistence is not None:
            self._events.bind(persistence)
            self._load_recovery_state(persistence)

        self._running = False
        self._tick_count = 0
        self._start_time = 0.0

    # ── Public properties (for monitoring / panel access) ─────────

    @property
    def sm(self) -> StateMachine:
        return self._sm

    @property
    def md(self) -> MarketData:
        return self._md

    @property
    def oe(self) -> OrderEngine:
        return self._oe

    @property
    def ref(self) -> RefPriceEngine:
        return self._ref

    @property
    def risk(self) -> RiskManager:
        return self._risk

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

    @property
    def balances(self) -> list[Balance]:
        return list(self._balances)

    @property
    def strategies(self) -> list[Strategy]:
        return list(self._strategies)

    @property
    def toxic_response(self) -> ToxicResponse:
        return self._tox_resp

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    async def run(self) -> None:
        """Start the main loop. Blocks until shutdown."""
        self._running = True
        self._start_time = time.monotonic()
        if self._sm.state == BotState.INIT:
            self._sm.transition(BotState.IDLE)

        # If recovering from a crash with a cooldown state, stay in IDLE
        # and let the next tick transition naturally
        if self._sm.state == BotState.IDLE:
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

        # 1. EMERGENCY / SHUTDOWN — hard stop
        if self._sm.is_emergency():
            return
        if self._sm.state == BotState.SHUTDOWN:
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
            self._save_state()

        # 5. Refresh balances periodically
        if self._tick_count % _BALANCE_REFRESH_INTERVAL == 0:
            await self._refresh_balances()

        # 6. Risk evaluation — always run, even during cooldown
        self._risk.evaluate(
            open_orders=self._oe.open_orders(),
            balances=self._balances,
            mid_price=mid,
        )
        if self._risk.halted:
            logger.warning("bot_halted_by_risk")
            self._sm.transition(BotState.EMERGENCY)
            self._events.record(BotEventType.RISK, reason=self._risk.halt_reason,
                              mid=round(mid, 2), state="EMERGENCY")
            self._save_state()
            await self._alert_warn("Bot halted by risk manager")
            return

        # 7. Update strategies
        strat_states: list[dict[str, Any]] = []
        for strat in self._strategies:
            if strat.active:
                strat.update_market(ref, spike_active=self._ref.spike_protection_active)
            strat_states.append({"name": strat.name, "active": strat.active})

        # 8. Cooldown recovery check — cooldown states continue processing
        if self._sm.state in (
            BotState.COOLDOWN_FILL, BotState.COOLDOWN_CANCEL,
            BotState.COOLDOWN_SELF_TRADE, BotState.COOLDOWN_PRICE_SPIKE,
        ):
            if self._sm.can_place():
                self._sm.transition(BotState.RUNNING)
                logger.info("cooldown_expired_resume")
            else:
                # Still in cooldown — place compliance depth if needed
                if self._cooldown.compliance_depth_required():
                    await self._place_compliance_orders()
                self._record_tick(mid, ref, strat_states)
                return

        # 9. Check if we can place
        if not self._sm.can_place():
            self._record_tick(mid, ref, strat_states)
            return
        if not self._cooldown.can_place():
            if self._cooldown.compliance_depth_required():
                await self._place_compliance_orders()
            self._record_tick(mid, ref, strat_states)
            return

        # 10. Place/refresh orders
        await self._refresh_orders()

        # 11. Update markout recorder
        self._markout.update_mid(mid)

        # 12. Smasher attack detection (integrated, lightweight)
        if hasattr(self, '_smasher') and self._smasher is not None:
            smasher_event = self._smasher.inspect(
                order_book=self._md.book,
                recent_fills=self._markout.recent_completed(),
            )
            if smasher_event.detected:
                logger.warning("smasher_attack_detected",
                              iceberg=len(smasher_event.iceberg_signals),
                              probe=smasher_event.probe_attack)
                self._events.record(BotEventType.ERROR, msg="smasher_attack_detected")
                await self._smasher.respond(smasher_event, self._oe)

        # 13. Process completed markout entries
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

        # 13. State machine sub-state management
        self._manage_sub_state()

        # Record tick summary
        self._record_tick(mid, ref, strat_states)

        # Persist state periodically (every 60 ticks ≈ 30s)
        if self._tick_count % 60 == 0:
            self._save_state()

    # ── Order management ────────────────────────────────────────

    async def _refresh_orders(self) -> None:
        """Compute desired orders and reconcile with exchange."""
        self._sm.set_sub_state(RunSubState.PLACING)

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

        for _strat, req in desired:
            try:
                await self._oe.place(req, ref_price=self._ref.ref_price)
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
                        await self._oe.place(req, ref_price=self._ref.ref_price)
                break  # One per strategy is enough for compliance

    # ── Balance refresh ─────────────────────────────────────────

    async def _refresh_balances(self) -> None:
        """Fetch latest balances from the exchange client."""
        if self._dry_run or self._client is None:
            return
        try:
            self._balances = await self._client.fetch_all_balances()
        except Exception:
            logger.warning("balance_fetch_failed", exc_info=True)

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

    def _load_recovery_state(self, persistence: Persistence) -> None:
        """On startup, check if we're recovering from a crash with a risky state."""
        try:
            state, _ts = persistence.load_state()
        except Exception:
            return

        if state in (
            BotState.EMERGENCY, BotState.COOLDOWN_FILL,
            BotState.COOLDOWN_CANCEL, BotState.COOLDOWN_SELF_TRADE,
            BotState.COOLDOWN_PRICE_SPIKE,
        ):
            logger.warning("recovery_from_risky_state", state=state.value)
            if state == BotState.EMERGENCY:
                logger.critical("recovery_emergency_requires_manual_clear")
                self._events.record(BotEventType.RISK,
                                  reason="recovery_emergency",
                                  state=state.value)
                # Stay in INIT — caller should handle this

    async def _shutdown(self) -> None:
        logger.info("bot_shutting_down", tick_count=self._tick_count,
                    uptime=round(self.uptime_seconds, 1))
        self._events.record(BotEventType.SHUTDOWN, tick_count=self._tick_count,
                          uptime=round(self.uptime_seconds, 1))
        self._sm.transition(BotState.SHUTDOWN)

        if self._persist is not None:
            self._persist.save_state(self._sm.state, self._sm.sub_state.value if self._sm.sub_state else None)

        # Flush pending markout records
        self._markout.flush()

        if not self._dry_run and self._pair:
            try:
                # Reconcile first to get accurate exchange state
                await self._oe.reconcile(self._pair)
                count = await self._oe.cancel_all(self._pair)
                logger.info("shutdown_cancelled", count=count, pair=self._pair)
            except Exception:
                logger.warning("cancel_all_failed_during_shutdown")

        await self._alert_info(
            f"Bot shut down after {self.uptime_seconds:.0f}s, {self._tick_count} ticks"
        )

    def _save_state(self) -> None:
        """Persist current state machine status for crash recovery."""
        if self._persist is not None:
            sub = self._sm.sub_state.value if self._sm.sub_state else None
            self._persist.save_state(self._sm.state, sub)

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
