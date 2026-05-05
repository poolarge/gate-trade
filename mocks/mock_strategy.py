"""Mock Strategy — records calls, returns canned orders."""

from __future__ import annotations

from gate_trade.strategy.contract import Strategy
from gate_trade.types import Order, OrderRequest


class MockStrategy(Strategy):
    """Returns pre-configured desired orders and records all events."""

    def __init__(self, name: str = "mock") -> None:
        self._name = name
        self._active = True
        self._desired: list[OrderRequest] = []
        self.fill_events: list[tuple[Order, float]] = []
        self.state_change_events: list[tuple[str, str]] = []
        self.cancel_events: list[Order] = []

    @property
    def name(self) -> str:
        return self._name

    def desired_orders(self) -> list[OrderRequest]:
        return list(self._desired)

    def on_fill(self, order: Order, filled_size: float) -> None:
        self.fill_events.append((order, filled_size))

    def on_state_change(self, old_state: str, new_state: str) -> None:
        self.state_change_events.append((old_state, new_state))

    def on_cancel(self, order: Order) -> None:
        self.cancel_events.append(order)

    @property
    def active(self) -> bool:
        return self._active

    # ── Test helpers ─────────────────────────────────────────

    def set_orders(self, orders: list[OrderRequest]) -> None:
        self._desired = orders

    def set_active(self, active: bool) -> None:
        self._active = active
