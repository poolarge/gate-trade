"""DataFeeder — loads and streams historical market snapshots.

Phase 9.2: Reads CSV files with order book snapshots and yields
MarketSnapshot objects for the replay engine.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class MarketSnapshot:
    timestamp: float
    best_bid: float
    best_ask: float
    bid_size: float
    ask_size: float
    last_price: float

    @property
    def mid_price(self) -> float:
        if self.best_bid <= 0 or self.best_ask <= 0:
            return self.last_price
        return (self.best_bid + self.best_ask) / 2.0


class DataFeeder:
    """Load historical market data and yield snapshots.

    CSV format: timestamp,best_bid,best_ask,bid_size,ask_size,last_price
    """

    def __init__(self, snapshots: list[MarketSnapshot]) -> None:
        self._snapshots = snapshots
        self._index = 0

    def __len__(self) -> int:
        return len(self._snapshots)

    def __iter__(self) -> Iterator[MarketSnapshot]:
        self._index = 0
        return self

    def __next__(self) -> MarketSnapshot:
        if self._index >= len(self._snapshots):
            raise StopIteration
        snap = self._snapshots[self._index]
        self._index += 1
        return snap

    @property
    def progress(self) -> float:
        if not self._snapshots:
            return 1.0
        return self._index / len(self._snapshots)

    @staticmethod
    def from_csv(path: str) -> DataFeeder:
        """Load snapshots from a CSV file."""
        filepath = Path(path)
        if not filepath.exists():
            raise FileNotFoundError(f"Data file not found: {path}")

        snapshots: list[MarketSnapshot] = []
        with filepath.open("r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                snapshots.append(MarketSnapshot(
                    timestamp=float(row["timestamp"]),
                    best_bid=float(row["best_bid"]),
                    best_ask=float(row["best_ask"]),
                    bid_size=float(row["bid_size"]),
                    ask_size=float(row["ask_size"]),
                    last_price=float(row["last_price"]),
                ))
        return DataFeeder(snapshots)

    @staticmethod
    def from_list(snapshots: list[MarketSnapshot]) -> DataFeeder:
        """Create feeder from an in-memory list (for testing)."""
        return DataFeeder(list(snapshots))
