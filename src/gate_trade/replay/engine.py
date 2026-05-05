"""ReplayEngine — drives historical data through the bot pipeline.

Phase 9.1: Feeds MarketSnapshot objects through ref price, strategy,
and markout modules, simulating fills when order prices cross the market.
"""

from __future__ import annotations

from typing import Any

import structlog

from gate_trade.markout.recorder import MarkoutRecorder
from gate_trade.markout.response import ToxicResponse
from gate_trade.markout.toxic import ToxicDetector
from gate_trade.replay.feeder import DataFeeder, MarketSnapshot
from gate_trade.replay.metrics import MetricsCollector, ReplayResult
from gate_trade.types import Order, OrderRequest, OrderStatus, Side

logger = structlog.get_logger(__name__)


class ReplayEngine:
    """Replay historical data through strategy and markout pipeline.

    On each snapshot:
      1. Update markout recorder with current mid
      2. Notify strategy of new ref price
      3. Evaluate desired orders against market — if our bid >= best_ask
         (or ask <= best_bid), simulate an immediate fill
      4. Record fill in markout and metrics collectors
      5. Check toxicity and update response level
    """

    def __init__(
        self,
        strategy: Any,  # duck-typed: needs update_market, desired_orders, on_fill
        markout: MarkoutRecorder | None = None,
        toxic: ToxicDetector | None = None,
        response: ToxicResponse | None = None,
    ) -> None:
        self._strategy = strategy
        self._markout = markout or MarkoutRecorder()
        self._toxic = toxic or ToxicDetector()
        self._response = response or ToxicResponse()
        self._metrics = MetricsCollector()

    @property
    def metrics(self) -> MetricsCollector:
        return self._metrics

    def run(self, feeder: DataFeeder) -> ReplayResult:
        """Run replay over all snapshots from the feeder."""
        self._metrics.reset()

        for snap in feeder:
            self._process_snapshot(snap)

        result = self._metrics.summarize()
        logger.info("replay_complete",
                    fills=result.total_fills,
                    avg_markout_bps=round(result.avg_markout_bps, 2),
                    net_volume=round(result.net_volume, 2))
        return result

    def _process_snapshot(self, snap: MarketSnapshot) -> None:
        self._metrics.record_snapshot()

        # Update markout recorder with latest mid
        self._markout.update_mid(snap.mid_price, timestamp=snap.timestamp)

        # Notify strategy of new ref price
        self._strategy.update_market(snap.mid_price)

        # Get desired orders and simulate fills
        for req in self._strategy.desired_orders():
            fill_price = self._crosses_market(req, snap)
            if fill_price is not None:
                self._simulate_fill(req, fill_price, snap.timestamp, snap.mid_price)

        # Process completed markout entries
        for record in self._markout.completed():
            is_toxic = self._toxic.evaluate(record)
            self._metrics.record_markout(
                MarkoutRecorder._compute_markout_bps(record),
                is_toxic=is_toxic,
            )
            self._response.evaluate(self._toxic.toxic_ratio, self._toxic.total_count)

    def _crosses_market(self, req: OrderRequest, snap: MarketSnapshot) -> float | None:
        """Check if an order would fill against the snapshot.

        Returns fill_price if the order crosses the market, else None.
        A buy limit at or above best_ask fills at the ask price.
        A sell limit at or below best_bid fills at the bid price.
        """
        if req.side == Side.BUY and req.price >= snap.best_ask > 0:
            return snap.best_ask
        if req.side == Side.SELL and req.price <= snap.best_bid and snap.best_bid > 0:
            return snap.best_bid
        return None

    def _simulate_fill(
        self, req: OrderRequest, fill_price: float, timestamp: float, mid_price: float
    ) -> None:
        """Record a simulated fill through markout and metrics."""
        order = Order(
            order_id=f"replay_{timestamp}_{req.side.value}",
            pair=req.pair,
            side=req.side,
            price=fill_price,
            size=req.size,
            filled_size=req.size,
            status=OrderStatus.CLOSED,
        )
        self._markout.on_fill(order, req.size, mid_price, timestamp=timestamp)
        self._metrics.record_fill(req.side, fill_price, req.size, timestamp)

    def reset(self) -> None:
        self._markout.reset()
        self._toxic.reset()
        self._response.reset()
        self._metrics.reset()
