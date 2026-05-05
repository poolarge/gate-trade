"""Mock Persistence — in-memory store for testing."""

from __future__ import annotations

from gate_trade.persistence.contract import Persistence
from gate_trade.types import BotState, Order


class MockPersistence(Persistence):
    """In-memory persistence that satisfies the contract for tests."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._fills: list[dict[str, object]] = []
        self._state: tuple[BotState, str | None] = (BotState.INIT, None)
        self._markouts: list[dict[str, object]] = []
        self._open = False
        self._closed = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._closed = True

    def save_order(self, order: Order) -> None:
        self._orders[order.order_id] = order

    def save_orders(self, orders: list[Order]) -> None:
        for o in orders:
            self._orders[o.order_id] = o

    def load_orders(self, pair: str) -> list[Order]:
        return [o for o in self._orders.values() if o.pair == pair]

    def load_open_orders(self, pair: str) -> list[Order]:
        return [o for o in self._orders.values() if o.pair == pair and o.status.value == "open"]

    def save_fill(self, order: Order, filled_size: float, price: float) -> None:
        self._fills.append({"order_id": order.order_id, "filled_size": filled_size, "price": price})

    def load_fills(self, pair: str, limit: int = 500) -> list[dict[str, object]]:
        return self._fills[:limit]

    def save_state(self, state: BotState, sub_state: str | None) -> None:
        self._state = (state, sub_state)

    def load_state(self) -> tuple[BotState, str | None]:
        return self._state

    def save_markout(self, fill_id: str, pair: str, fill_price: float, ref_5s: float, ref_30s: float, ref_5min: float) -> None:
        self._markouts.append({
            "fill_id": fill_id, "pair": pair, "fill_price": fill_price,
            "ref_5s": ref_5s, "ref_30s": ref_30s, "ref_5min": ref_5min,
        })

    def vacuum(self) -> None:
        pass
