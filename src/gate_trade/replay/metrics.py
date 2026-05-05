"""MetricsCollector — tracks P&L, fills, and performance during replay.

Phase 9.2: Accumulates trade and markout data, then produces a
ReplayResult summary object.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gate_trade.types import Side


@dataclass
class FillRecord:
    timestamp: float
    side: Side
    price: float
    size: float


@dataclass
class ReplayResult:
    total_snapshots: int
    total_fills: int
    buy_volume: float
    sell_volume: float
    buy_count: int
    sell_count: int
    net_inventory: float
    avg_buy_price: float
    avg_sell_price: float
    avg_markout_bps: float
    toxic_fill_count: int
    peak_inventory: float
    fills: list[FillRecord] = field(default_factory=list)
    markout_samples: list[float] = field(default_factory=list)

    @property
    def net_volume(self) -> float:
        return self.sell_volume - self.buy_volume

    @property
    def toxic_ratio(self) -> float:
        if self.total_fills == 0:
            return 0.0
        return self.toxic_fill_count / self.total_fills


class MetricsCollector:
    """Collects fill and markout data during a replay run."""

    def __init__(self) -> None:
        self._fills: list[FillRecord] = []
        self._markout_samples: list[float] = []
        self._toxic_fill_count = 0
        self._peak_inventory = 0.0
        self._inventory = 0.0
        self._snapshot_count = 0

    def record_snapshot(self) -> None:
        self._snapshot_count += 1

    def record_fill(self, side: Side, price: float, size: float, timestamp: float) -> None:
        self._fills.append(FillRecord(timestamp=timestamp, side=side, price=price, size=size))
        if side == Side.BUY:
            self._inventory += size
        else:
            self._inventory -= size
        if abs(self._inventory) > self._peak_inventory:
            self._peak_inventory = abs(self._inventory)

    def record_markout(self, bps: float, is_toxic: bool = False) -> None:
        self._markout_samples.append(bps)
        if is_toxic:
            self._toxic_fill_count += 1

    def summarize(self) -> ReplayResult:
        buy_fills = [f for f in self._fills if f.side == Side.BUY]
        sell_fills = [f for f in self._fills if f.side == Side.SELL]
        buy_volume = sum(f.price * f.size for f in buy_fills)
        sell_volume = sum(f.price * f.size for f in sell_fills)
        avg_buy = buy_volume / sum(f.size for f in buy_fills) if buy_fills else 0.0
        avg_sell = sell_volume / sum(f.size for f in sell_fills) if sell_fills else 0.0
        avg_markout = (sum(self._markout_samples) / len(self._markout_samples)
                       if self._markout_samples else 0.0)

        return ReplayResult(
            total_snapshots=self._snapshot_count,
            total_fills=len(self._fills),
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            buy_count=len(buy_fills),
            sell_count=len(sell_fills),
            net_inventory=self._inventory,
            avg_buy_price=avg_buy,
            avg_sell_price=avg_sell,
            avg_markout_bps=avg_markout,
            toxic_fill_count=self._toxic_fill_count,
            peak_inventory=self._peak_inventory,
            fills=list(self._fills),
            markout_samples=list(self._markout_samples),
        )

    def reset(self) -> None:
        self._fills.clear()
        self._markout_samples.clear()
        self._toxic_fill_count = 0
        self._peak_inventory = 0.0
        self._inventory = 0.0
        self._snapshot_count = 0
