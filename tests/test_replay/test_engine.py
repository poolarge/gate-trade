"""Tests for ReplayEngine — Phase 9.1."""

from __future__ import annotations

from gate_trade.replay.engine import ReplayEngine
from gate_trade.replay.feeder import DataFeeder, MarketSnapshot
from gate_trade.types import Order, OrderRequest, Side


class _FakeStrategy:
    """Minimal fake strategy for replay tests — avoids Accumulator complexity."""

    def __init__(self, pair="BTC_USDT", buy_price=49900.0, sell_price=50100.0, size=0.01):
        self._pair = pair
        self._buy_price = buy_price
        self._sell_price = sell_price
        self._size = size
        self.updated_mids: list[float] = []

    def update_market(self, ref_price: float, spike_active: bool = False) -> None:
        self.updated_mids.append(ref_price)

    def desired_orders(self) -> list[OrderRequest]:
        return [
            OrderRequest(pair=self._pair, side=Side.BUY,
                         price=self._buy_price, size=self._size),
            OrderRequest(pair=self._pair, side=Side.SELL,
                         price=self._sell_price, size=self._size),
        ]

    def on_fill(self, order: Order, filled_size: float) -> None:
        pass


class TestRun:
    def test_processes_all_snapshots(self):
        strategy = _FakeStrategy()
        engine = ReplayEngine(strategy)
        snaps = [MarketSnapshot(float(i), 50000.0, 50010.0, 1.0, 1.0, 50005.0)
                  for i in range(10)]
        feeder = DataFeeder.from_list(snaps)
        result = engine.run(feeder)
        assert result.total_snapshots == 10

    def test_strategy_receives_mid_updates(self):
        strategy = _FakeStrategy()
        engine = ReplayEngine(strategy)
        snaps = [
            MarketSnapshot(0.0, 100.0, 102.0, 1.0, 1.0, 101.0),
            MarketSnapshot(1.0, 101.0, 103.0, 1.0, 1.0, 102.0),
        ]
        engine.run(DataFeeder.from_list(snaps))
        assert strategy.updated_mids == [101.0, 102.0]

    def test_buy_fills_when_price_crosses_ask(self):
        strategy = _FakeStrategy(buy_price=50100.0, sell_price=99999.0)
        engine = ReplayEngine(strategy)
        snaps = [MarketSnapshot(0.0, 50000.0, 50050.0, 1.0, 0.5, 50025.0)]
        result = engine.run(DataFeeder.from_list(snaps))
        # buy at 50100 >= ask 50050 → fills at 50050
        assert result.total_fills == 1
        assert result.buy_count == 1
        assert result.buy_volume > 0

    def test_sell_fills_when_price_crosses_bid(self):
        strategy = _FakeStrategy(buy_price=1.0, sell_price=50000.0)
        engine = ReplayEngine(strategy)
        snaps = [MarketSnapshot(0.0, 50050.0, 50100.0, 0.5, 1.0, 50075.0)]
        result = engine.run(DataFeeder.from_list(snaps))
        # sell at 50000 <= bid 50050 → fills at 50050
        assert result.total_fills == 1
        assert result.sell_count == 1

    def test_no_fill_when_price_does_not_cross(self):
        strategy = _FakeStrategy(buy_price=49900.0, sell_price=50100.0)
        engine = ReplayEngine(strategy)
        snaps = [MarketSnapshot(0.0, 50000.0, 50010.0, 1.0, 1.0, 50005.0)]
        result = engine.run(DataFeeder.from_list(snaps))
        # buy 49900 < ask 50010 → no fill; sell 50100 > bid 50000 → no fill
        assert result.total_fills == 0

    def test_empty_feeder(self):
        strategy = _FakeStrategy()
        engine = ReplayEngine(strategy)
        result = engine.run(DataFeeder.from_list([]))
        assert result.total_snapshots == 0
        assert result.total_fills == 0

    def test_metrics_reset_between_runs(self):
        strategy = _FakeStrategy(buy_price=50100.0)
        engine = ReplayEngine(strategy)
        snaps = [MarketSnapshot(0.0, 50000.0, 50050.0, 1.0, 0.5, 50025.0)]
        engine.run(DataFeeder.from_list(snaps))
        first = engine.metrics.summarize()
        assert first.total_fills > 0
        # Second run should reset
        engine.run(DataFeeder.from_list([]))
        assert engine.metrics.summarize().total_fills == 0
