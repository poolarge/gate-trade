"""Accumulator — unilateral accumulation strategy with ratchet and collapse protection.

Phase 2.3: Ladder calculation, tick alignment, collapse protection, SUSPENDED gate, v1.7 ratchet.
"""

from __future__ import annotations

import structlog

from gate_trade.strategy.contract import Strategy
from gate_trade.types import Order, OrderRequest, Side

logger = structlog.get_logger(__name__)


class Accumulator(Strategy):
    """Places a descending ladder of buy orders below the reference price.

    Ratchet (v1.7)
        The ladder's top rung only moves *down* — never up. This prevents
        the strategy from chasing rallies and enforces disciplined accumulation
        on pullbacks only.

    Collapse protection
        If the reference price drops too far below the cheapest ladder rung,
        the strategy enters SUSPENDED state and stops placing orders.
        Recovery requires the ref price to rise back above the suspend trigger
        plus hysteresis.
    """

    def __init__(
        self,
        pair: str,
        tick_size: float = 0.01,
        order_size: float = 1.0,
        ladder_rungs: int = 5,
        rung_spacing_ticks: int = 10,
        start_offset_ticks: int = 5,
        collapse_threshold_pct: float = 2.0,
        collapse_recovery_pct: float = 1.0,
        suspend_on_spike: bool = True,
    ) -> None:
        self._pair = pair
        self._tick_size = tick_size
        self._order_size = order_size
        self._ladder_rungs = ladder_rungs
        self._rung_spacing = rung_spacing_ticks * tick_size
        self._start_offset = start_offset_ticks * tick_size
        self._collapse_threshold = collapse_threshold_pct / 100.0
        self._collapse_recovery = collapse_recovery_pct / 100.0
        self._suspend_on_spike = suspend_on_spike

        # Market context (fed by main loop)
        self._ref_price: float = 0.0
        self._spike_active: bool = False

        # Ratchet state
        self._ratchet: float = 0.0
        self._entry_price: float = 0.0
        self._filled_size: float = 0.0
        self._filled_cost: float = 0.0

        # Collapse protection
        self._suspended: bool = False
        self._suspend_trigger: float = 0.0
        self._just_recovered: bool = False

        # Track placed orders for reconciliation
        self._active_orders: list[OrderRequest] = []

    # ── Strategy Protocol ────────────────────────────────────────

    @property
    def name(self) -> str:
        return "accum"

    @property
    def active(self) -> bool:
        return not self._suspended

    def desired_orders(self) -> list[OrderRequest]:
        if self._ref_price <= 0:
            return []

        if self._suspended:
            self._check_recovery()
            if self._suspended:
                return []
            self._just_recovered = True

        if self._spike_active and self._suspend_on_spike:
            return []

        if self._ratchet <= 0:
            self._ratchet = self._ref_price - self._start_offset

        orders = self._compute_ladder()
        self._active_orders = orders
        if not self._just_recovered:
            self._check_collapse(orders)
        self._just_recovered = False
        if self._suspended:
            return []
        return orders

    def on_fill(self, order: Order, filled_size: float) -> None:
        self._filled_size += filled_size
        self._filled_cost += order.price * filled_size
        self._entry_price = self._filled_cost / self._filled_size
        # Ratchet: only move down
        if self._ratchet <= 0 or order.price < self._ratchet:
            self._ratchet = order.price
            logger.info("accum_ratchet_down", ratchet=self._ratchet,
                        fill_price=order.price, entry=self._entry_price)

    def on_state_change(self, old_state: str, new_state: str) -> None:
        if new_state in ("EMERGENCY", "SHUTDOWN"):
            self._suspended = True

    def on_cancel(self, order: Order) -> None:
        pass  # no action needed for cancelled orders in this strategy

    # ── Public API ───────────────────────────────────────────────

    def update_market(self, ref_price: float, spike_active: bool = False) -> None:
        self._ref_price = ref_price
        self._spike_active = spike_active

    def reset(self) -> None:
        self._ratchet = 0.0
        self._entry_price = 0.0
        self._filled_size = 0.0
        self._filled_cost = 0.0
        self._suspended = False
        self._suspend_trigger = 0.0
        self._active_orders.clear()

    # ── Properties for test introspection ────────────────────────

    @property
    def ratchet(self) -> float:
        return self._ratchet

    @property
    def entry_price(self) -> float:
        return self._entry_price

    @property
    def suspended(self) -> bool:
        return self._suspended

    # ── Internal ─────────────────────────────────────────────────

    def _compute_ladder(self) -> list[OrderRequest]:
        orders: list[OrderRequest] = []
        for i in range(self._ladder_rungs):
            price = self._align(self._ratchet - i * self._rung_spacing)
            if price <= 0:
                continue
            orders.append(OrderRequest(
                pair=self._pair,
                side=Side.BUY,
                price=price,
                size=self._order_size,
            ))
        return orders

    def _align(self, price: float) -> float:
        tick = self._tick_size
        return round(round(price / tick) * tick, 8)

    def _check_collapse(self, orders: list[OrderRequest]) -> None:
        """Suspend if ref price drops too far below the lowest rung."""
        if not orders:
            return
        lowest = min(o.price for o in orders)
        if self._ref_price < lowest * (1.0 - self._collapse_threshold):
            self._suspended = True
            self._suspend_trigger = self._ref_price
            logger.warning("accum_collapse_suspended",
                           ref=self._ref_price, lowest_rung=lowest,
                           threshold_pct=self._collapse_threshold * 100)

    def _check_recovery(self) -> None:
        """Resume if ref price recovers above suspend trigger + hysteresis."""
        if self._ref_price >= self._suspend_trigger * (1.0 + self._collapse_recovery):
            self._suspended = False
            logger.info("accum_collapse_recovered",
                        ref=self._ref_price, trigger=self._suspend_trigger)
