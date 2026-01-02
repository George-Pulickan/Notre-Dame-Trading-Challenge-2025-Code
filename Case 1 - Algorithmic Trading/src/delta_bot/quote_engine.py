"""Quote generation logic for layered passive liquidity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from . import config
from .models import MarketSnapshot, OrderLevel, Side


@dataclass
class QuoteContext:
    fair_value: float
    volatility_bps: float
    inventory_skew_bps: int
    spread_scale: float = 1.0
    size_scale: float = 1.0
    bid_size_scale: float = 1.0
    ask_size_scale: float = 1.0


def compute_inventory_skew(position: int, limit: int) -> int:
    if limit == 0:
        return 0
    ratio = max(-1.0, min(1.0, position / limit))
    return int(config.INVENTORY_SKEW_BPS * ratio)


def build_ladders(
    snapshot: MarketSnapshot,
    ctx: QuoteContext,
    symbol_config: config.SymbolConfig,
) -> tuple[list[OrderLevel], list[OrderLevel]]:
    mid = ctx.fair_value or snapshot.order_book.mid
    if mid is None or mid <= 0:
        return [], []

    base_spread = (symbol_config.base_spread_bps * ctx.spread_scale) + ctx.volatility_bps
    level_step = symbol_config.level_spread_step_bps * ctx.spread_scale
    size_seed = max(1, int(symbol_config.base_size))
    maker_edge = config.EFFECTIVE_MAKER_EDGE_BPS / 2.0

    bids: list[OrderLevel] = []
    asks: list[OrderLevel] = []

    current_size = size_seed
    for level_index in range(symbol_config.max_levels):
        offset_bps = base_spread + level_index * level_step
        base_size = max(1, int(current_size * ctx.size_scale))
        bid_size = max(1, int(base_size * ctx.bid_size_scale))
        ask_size = max(1, int(base_size * ctx.ask_size_scale))

        bid_bps = offset_bps + max(ctx.inventory_skew_bps, 0)
        ask_bps = offset_bps + max(-ctx.inventory_skew_bps, 0)

        bid_price = _price_from_bps(mid, bid_bps - maker_edge, Side.BID)
        ask_price = _price_from_bps(mid, ask_bps - maker_edge, Side.ASK)

        bids.append(
            OrderLevel(
                symbol=snapshot.symbol,
                side=Side.BID,
                level_index=level_index,
                price=bid_price,
                size=bid_size,
            )
        )
        asks.append(
            OrderLevel(
                symbol=snapshot.symbol,
                side=Side.ASK,
                level_index=level_index,
                price=ask_price,
                size=ask_size,
            )
        )

        current_size = max(1, int(current_size * symbol_config.size_multiplier))

    return bids, asks


def estimate_notional(levels: Iterable[OrderLevel]) -> float:
    return sum(level.price * level.size for level in levels)


def _price_from_bps(mid: float, bps: float, side: Side) -> float:
    effective_bps = max(1.0, bps)
    delta = mid * (effective_bps / 10_000)
    if side is Side.BID:
        return max(0.01, mid - delta)
    return mid + delta


__all__ = ["QuoteContext", "compute_inventory_skew", "build_ladders", "estimate_notional"]
