"""Mock RiskManager — pre-configured halt/resume flags."""

from __future__ import annotations

from gate_trade.risk.contract import RiskManager
from gate_trade.types import Balance, Order


class MockRiskManager(RiskManager):
    """Returns pre-configured risk decisions."""

    def __init__(self) -> None:
        self._can_trade = True
        self._halted = False
        self._position_breached = False
        self._order_count_breached = False
        self._flash_crash = False
        self._should_resume = True
        self.eval_calls: list[tuple[list[Order], list[Balance], float]] = []

    def evaluate(self, open_orders: list[Order], balances: list[Balance], mid_price: float) -> None:
        self.eval_calls.append((open_orders, balances, mid_price))

    @property
    def can_trade(self) -> bool:
        return self._can_trade

    @property
    def halted(self) -> bool:
        return self._halted

    @property
    def position_limit_breached(self) -> bool:
        return self._position_breached

    @property
    def order_count_breached(self) -> bool:
        return self._order_count_breached

    @property
    def flash_crash_detected(self) -> bool:
        return self._flash_crash

    def should_resume(self) -> bool:
        return self._should_resume

    def reset(self) -> None:
        self._halted = False
        self._can_trade = True

    # ── Test helpers ─────────────────────────────────────────

    def set_can_trade(self, ok: bool) -> None:
        self._can_trade = ok

    def set_halted(self, halted: bool) -> None:
        self._halted = halted

    def set_flash_crash(self, active: bool) -> None:
        self._flash_crash = active
