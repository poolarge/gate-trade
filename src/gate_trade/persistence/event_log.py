"""BotEventLogger — in-memory ring buffer + SQLite persistence for bot actions.

Provides a structured audit trail of every significant bot action: ticks,
order placements, fills, state transitions, strategy decisions, risk
evaluations, and toxicity detections.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_MAX_BUFFER = 2000  # in-memory events for the web dashboard


class BotEventType(str, Enum):
    TICK = "tick"
    STATE_CHANGE = "state_change"
    ORDER_PLACE = "order_place"
    ORDER_CANCEL = "order_cancel"
    FILL = "fill"
    STRATEGY = "strategy"
    RISK = "risk"
    TOXIC = "toxic"
    SPIKE = "spike"
    MARKOUT = "markout"
    ERROR = "error"
    SHUTDOWN = "shutdown"


@dataclass(slots=True)
class BotEvent:
    """A single bot action or observation."""

    type: BotEventType
    timestamp: float = field(default_factory=time.monotonic)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "ts": self.timestamp, **self.data}


class BotEventLogger:
    """Ring-buffer event store with optional SQLite persistence.

    Usage::

        events = BotEventLogger(persistence=db, pair="BTC_USDT")
        events.record(BotEventType.TICK, mid=50000, state="RUNNING")
        # ... later ...
        recent = events.recent(limit=50)  # for dashboard
    """

    def __init__(self, pair: str = "") -> None:
        self._buffer: deque[BotEvent] = deque(maxlen=_MAX_BUFFER)
        self._pair = pair
        self._persistence: Any = None  # SqlitePersistence, set via .bind()
        self._on_record: Any = None   # Callable[[BotEvent], None], set by web panel
        self._tick_count: int = 0

    def bind(self, persistence: Any) -> None:
        """Attach a SqlitePersistence instance for durable storage."""
        self._persistence = persistence

    @property
    def tick_count(self) -> int:
        return self._tick_count

    def record(self, event_type: BotEventType, **data: Any) -> None:
        """Record an event to the in-memory buffer and optional persistence."""
        evt = BotEvent(type=event_type, data=data)
        self._buffer.append(evt)

        if event_type == BotEventType.TICK:
            self._tick_count += 1

        if self._persistence is not None:
            try:
                self._persistence.save_event(evt)
            except Exception:
                logger.warning("event_persist_failed", exc_info=True)

        if self._on_record is not None:
            try:
                self._on_record(evt)
            except Exception:
                logger.warning("on_record_callback_failed", exc_info=True)

    def recent(self, limit: int = 100, since: float | None = None) -> list[dict[str, Any]]:
        """Return recent events, optionally filtered by timestamp."""
        events: list[dict[str, Any]] = []
        for evt in reversed(self._buffer):
            if since is not None and evt.timestamp <= since:
                continue
            events.append(evt.to_dict())
            if len(events) >= limit:
                break
        events.reverse()
        return events

    def last_tick(self) -> dict[str, Any] | None:
        """Return the most recent tick event, or None."""
        for evt in reversed(self._buffer):
            if evt.type == BotEventType.TICK:
                return evt.to_dict()
        return None

    def clear(self) -> None:
        self._buffer.clear()
        self._tick_count = 0
