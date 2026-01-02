"""Order management utilities for maintaining quote ladders."""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Iterable

from . import config
from .exchange import ExchangeClient
from .models import ActiveOrders, OrderInfo, OrderLevel, Side


def _bps_distance(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return float("inf")
    mid = (a + b) / 2.0
    return abs(a - b) / mid * 10_000


class OrderLadderManager:
    """Keeps ladder state aligned with desired levels while respecting rate limits."""

    def __init__(self, client: ExchangeClient, symbol_configs: Dict[str, config.SymbolConfig]):
        self.client = client
        self.symbol_configs = symbol_configs
        self.active_orders: ActiveOrders = {
            symbol: {Side.BID: {}, Side.ASK: {}} for symbol in symbol_configs
        }
        self._window_start = time.monotonic()
        self._actions_this_window = 0
        self._lock = asyncio.Lock()

    async def sync_symbol(self, symbol: str, bids: list[OrderLevel], asks: list[OrderLevel]) -> None:
        async with self._lock:
            await self._sync_side(symbol, Side.BID, bids)
            await self._sync_side(symbol, Side.ASK, asks)
            await self._prune_levels(symbol, Side.BID, {lvl.level_index for lvl in bids})
            await self._prune_levels(symbol, Side.ASK, {lvl.level_index for lvl in asks})

    async def cancel_all(self) -> None:
        async with self._lock:
            for symbol in list(self.active_orders):
                for side in (Side.BID, Side.ASK):
                    for info in list(self.active_orders[symbol][side].values()):
                        if info is None:
                            continue
                        await self._throttled_cancel(info)
                    self.active_orders[symbol][side].clear()

    async def _sync_side(self, symbol: str, side: Side, desired: Iterable[OrderLevel]) -> None:
        for level in desired:
            existing = self.active_orders[symbol][side].get(level.level_index)
            if existing is None:
                info = await self._throttled_place(level)
                self.active_orders[symbol][side][level.level_index] = info
            elif self._needs_refresh(existing, level):
                info = await self._throttled_replace(existing, level)
                self.active_orders[symbol][side][level.level_index] = info

    async def _prune_levels(self, symbol: str, side: Side, desired_indexes: set[int]) -> None:
        for level_index, info in list(self.active_orders[symbol][side].items()):
            if level_index in desired_indexes:
                continue
            if info is None:
                continue
            await self._throttled_cancel(info)
            del self.active_orders[symbol][side][level_index]

    def _needs_refresh(self, existing: OrderInfo, desired: OrderLevel) -> bool:
        if existing.size != desired.size:
            return True
        return _bps_distance(existing.price, desired.price) >= config.MIN_MOVE_TO_REFRESH_BPS

    async def _throttled_place(self, level: OrderLevel) -> OrderInfo:
        await self._reserve_action_slot()
        return await self.client.place_order(level)

    async def _throttled_replace(self, existing: OrderInfo, level: OrderLevel) -> OrderInfo:
        await self._reserve_action_slot()
        return await self.client.replace_order(existing.order_id, level)

    async def _throttled_cancel(self, info: OrderInfo) -> None:
        await self._reserve_action_slot()
        await self.client.cancel_order(info.order_id)

    async def _reserve_action_slot(self) -> None:
        while True:
            now = time.monotonic()
            elapsed = now - self._window_start
            if elapsed >= 1.0:
                self._window_start = now
                self._actions_this_window = 0
            if self._actions_this_window < config.MAX_ACTIONS_PER_SECOND:
                self._actions_this_window += 1
                return
            await asyncio.sleep(max(0.0, 1.0 - elapsed))


__all__ = ["OrderLadderManager"]
