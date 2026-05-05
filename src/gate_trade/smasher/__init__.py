"""Smasher — attack detection and counter-measure orchestration.

Phase 7 integration: Provides SmasherGuard, a lightweight orchestrator that
wraps IcebergDetector, ProbeDetector, TrickleExecutor, and SmasherVerifier
for optional use from Bot._tick().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from gate_trade.smasher.iceberg import IcebergDetector, IcebergSignal
from gate_trade.smasher.probe import ProbeDetector
from gate_trade.smasher.trickle import TrickleExecutor
from gate_trade.smasher.verify import SmasherVerifier

if TYPE_CHECKING:
    from gate_trade.types import OrderBook

__all__ = [
    "IcebergDetector",
    "IcebergSignal",
    "ProbeDetector",
    "TrickleExecutor",
    "SmasherVerifier",
    "SmasherGuard",
    "SmasherEvent",
]


@dataclass
class SmasherEvent:
    """Result of a smasher detection pass."""
    detected: bool = False
    iceberg_signals: list[IcebergSignal] = field(default_factory=list)
    probe_attack: bool = False
    probe_side: str = ""


class SmasherGuard:
    """Lightweight orchestrator for smasher detection in the main loop.

    Usage from Bot._tick()::

        guard = SmasherGuard(iceberg_detector, probe_detector)
        event = guard.inspect(
            order_book=md.book,
            recent_fills=markout.recent_completed(),
        )
        if event.detected:
            await guard.respond(event, oe)
    """

    def __init__(
        self,
        iceberg: IcebergDetector | None = None,
        probe: ProbeDetector | None = None,
    ) -> None:
        self._iceberg = iceberg or IcebergDetector()
        self._probe = probe or ProbeDetector()

    def inspect(
        self,
        order_book: OrderBook | None = None,
        recent_fills: list[object] | None = None,
    ) -> SmasherEvent:
        event = SmasherEvent()
        # Iceberg detection requires order book delta tracking
        # Probe detection requires fill history analysis
        # Both are wired in as data plumbing matures.
        return event

    async def respond(self, event: SmasherEvent, order_engine: object) -> None:
        """Execute counter-measures based on detected attacks."""
        if event.probe_attack and event.probe_side:
            try:
                if hasattr(order_engine, 'cancel_all'):
                    await order_engine.cancel_all("")
            except Exception:
                pass
