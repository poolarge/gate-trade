"""Shared types and data structures for the Gate Trade bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Final

# ── Order side & type ────────────────────────────────────────────


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


# ── Price precision ──────────────────────────────────────────────

PRICE_DECIMALS: Final = 6
SIZE_DECIMALS: Final = 8


# ── Order book ───────────────────────────────────────────────────


@dataclass(slots=True)
class OrderBookLevel:
    price: float
    size: float


@dataclass(slots=True)
class OrderBook:
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    timestamp_ms: int = 0

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def spread(self) -> float:
        ba = self.best_ask
        bb = self.best_bid
        if ba <= 0 or bb <= 0:
            return 0.0
        return ba - bb

    @property
    def mid_price(self) -> float:
        ba = self.best_ask
        bb = self.best_bid
        if ba <= 0 or bb <= 0:
            return 0.0
        return (ba + bb) / 2.0


# ── Order representation ─────────────────────────────────────────


@dataclass(slots=True)
class OrderRequest:
    pair: str
    side: Side
    price: float
    size: float
    order_type: OrderType = OrderType.LIMIT
    client_order_id: str = ""


@dataclass(slots=True)
class Order:
    order_id: str
    pair: str
    side: Side
    price: float
    size: float
    filled_size: float = 0.0
    status: OrderStatus = OrderStatus.OPEN
    client_order_id: str = ""
    created_at_ms: int = 0


# ── Balance ──────────────────────────────────────────────────────


@dataclass(slots=True)
class Balance:
    currency: str
    available: float
    locked: float = 0.0

    @property
    def total(self) -> float:
        return self.available + self.locked


# ── Market indicators ────────────────────────────────────────────


@dataclass(slots=True)
class MarketSignal:
    flash_crash: bool = False
    depth_wall_bid: bool = False
    depth_wall_ask: bool = False
    spread_bps: float = 0.0
    imbalance: float = 0.0  # -1..1, negative = sell pressure


# ── State machine ────────────────────────────────────────────────


class BotState(str, Enum):
    INIT = "INIT"
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COOLDOWN_FILL = "COOLDOWN_FILL"
    COOLDOWN_CANCEL = "COOLDOWN_CANCEL"
    COOLDOWN_SELF_TRADE = "COOLDOWN_SELF_TRADE"
    EMERGENCY = "EMERGENCY"
    SHUTDOWN = "SHUTDOWN"
    RECONNECT = "RECONNECT"


class RunSubState(str, Enum):
    PLACING = "PLACING"          # placing new maker orders
    WAITING = "WAITING"          # orders in book, no action
    CANCELLING_STALE = "CANCELLING_STALE"  # removing orders too far from ref
    REFRESHING = "REFRESHING"    # replace orders around new ref price


# ── Configuration schema stub ────────────────────────────────────

# Full config model lives in gate_trade.config.schema;
# this module stays dependency-free for contract consumers.
