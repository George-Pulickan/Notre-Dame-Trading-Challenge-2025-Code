"""Dataclasses and helper types for the Delta Exchange bot."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Side(str, Enum):
    BID = "bid"
    ASK = "ask"

    @property
    def opposite(self) -> "Side":
        return Side.ASK if self is Side.BID else Side.BID


@dataclass
class OrderLevel:
    symbol: str
    side: Side
    level_index: int
    price: float
    size: int


@dataclass
class OrderInfo(OrderLevel):
    order_id: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class PositionState:
    symbol: str
    position: int = 0
    vwap: float = 0.0


@dataclass
class PnLState:
    realized: float = 0.0
    unrealized: float = 0.0
    equity_high_watermark: float = 0.0

    def update_high_watermark(self) -> None:
        self.equity_high_watermark = max(
            self.equity_high_watermark, self.realized + self.unrealized
        )


@dataclass
class MarketLevel:
    price: float
    size: int


@dataclass
class OrderBook:
    bids: List[MarketLevel]
    asks: List[MarketLevel]

    @property
    def mid(self) -> Optional[float]:
        if not self.bids or not self.asks:
            return None
        return (self.bids[0].price + self.asks[0].price) / 2.0


@dataclass
class MarketSnapshot:
    symbol: str
    order_book: OrderBook
    timestamp: float


ActiveOrders = Dict[str, Dict[Side, Dict[int, OrderInfo | None]]]
Positions = Dict[str, PositionState]
