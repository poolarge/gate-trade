"""Mock RefPriceEngine — canned reference prices."""

from __future__ import annotations

from gate_trade.price.contract import RefPriceEngine


class MockRefPriceEngine(RefPriceEngine):
    """Returns pre-configured reference prices."""

    def __init__(self, ref: float = 100.0, spread_ticks: int = 5, tick_size: float = 0.01) -> None:
        self._ref = ref
        self._half_spread = spread_ticks * tick_size
        self._spike = False
        self._spike_remaining = 0
        self.update_calls: list[tuple[float, float, list[float], list[float]]] = []

    @property
    def ref_price(self) -> float:
        return self._ref

    @property
    def ref_bid(self) -> float:
        return round(self._ref - self._half_spread, 6)

    @property
    def ref_ask(self) -> float:
        return round(self._ref + self._half_spread, 6)

    def update(self, best_bid: float, best_ask: float, own_bids: list[float], own_asks: list[float]) -> None:
        self.update_calls.append((best_bid, best_ask, own_bids, own_asks))
        # Exclude own orders from best bid/ask when they match the market top
        bid = best_bid if best_bid not in own_bids else 0.0
        ask = best_ask if best_ask not in own_asks else 0.0
        if bid > 0 and ask > 0:
            self._ref = (bid + ask) / 2.0
        elif ask > 0:
            self._ref = ask
        elif bid > 0:
            self._ref = bid

    @property
    def spike_protection_active(self) -> bool:
        return self._spike

    @property
    def spike_cooldown_remaining_ms(self) -> int:
        return self._spike_remaining

    def reset(self) -> None:
        self._spike = False
        self._spike_remaining = 0

    # ── Test helpers ─────────────────────────────────────────

    def set_ref(self, price: float) -> None:
        self._ref = price

    def set_spike(self, active: bool, remaining_ms: int = 0) -> None:
        self._spike = active
        self._spike_remaining = remaining_ms
