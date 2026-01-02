"""Core strategy loop for the Delta Exchange bot."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Optional

from . import config
from .exchange import ExchangeClient
from .models import MarketSnapshot, PnLState, PositionState, Side
from .order_manager import OrderLadderManager
from .quote_engine import (
    QuoteContext,
    build_ladders,
    compute_inventory_skew,
)
from . import risk


class Strategy:
    """Coordinates market data, quoting, and risk controls."""

    def __init__(self, client: ExchangeClient) -> None:
        self.client = client
        self.symbol_configs = config.DEFAULT_SYMBOL_CONFIG
        self.positions: Dict[str, PositionState] = {
            symbol: PositionState(symbol=symbol) for symbol in config.ALL_SYMBOLS
        }
        self.pnl = PnLState()
        self.market: Dict[str, MarketSnapshot] = {}
        self._volatility_bps: Dict[str, float] = {
            symbol: float(self.symbol_configs[symbol].base_spread_bps)
            for symbol in config.ALL_SYMBOLS
        }
        self._last_mid: Dict[str, Optional[float]] = {symbol: None for symbol in config.ALL_SYMBOLS}
        self._order_manager = OrderLadderManager(client, self.symbol_configs)
        self._logger = logging.getLogger(__name__)
        self._last_metrics_log = 0.0
        self.client.register_fill_handler(self.register_fill)

    async def run(self) -> None:
        while True:
            loop_start = time.perf_counter()
            await self._refresh_order_books()
            mid_map = self._mid_map()
            if not mid_map:
                await self._sleep(loop_start)
                continue

            risk.update_unrealized_pnl(self.pnl, self.positions, mid_map)
            drawdown_pct = risk.compute_drawdown_pct(self.pnl)
            spread_scale, size_scale, throttled = risk.drawdown_adjustments(drawdown_pct)
            exposure = risk.compute_dollar_exposure(self.positions, mid_map)
            size_scale *= self._exposure_size_scale(exposure)
            size_scale *= self._resting_notional_scale(mid_map)

            if throttled or size_scale == 0.0:
                await self._order_manager.cancel_all()
                await self._sleep(loop_start)
                continue

            synthetic_fair = self._compute_synthetic_fair(mid_map)
            etf_mispricing_bps = self._compute_mispricing_bps(mid_map, synthetic_fair)
            await self._quote_all(
                mid_map,
                synthetic_fair,
                spread_scale,
                size_scale,
                etf_mispricing_bps,
            )
            self._maybe_log_metrics(etf_mispricing_bps, exposure, drawdown_pct, size_scale)
            await self._sleep(loop_start)

    def register_fill(self, symbol: str, side: Side, size: int, price: float) -> None:
        """Ingest a fill event to update inventory and realized PnL."""

        state = self.positions[symbol]
        signed_qty = size if side is Side.BID else -size
        pre_position = state.position

        if pre_position > 0 and signed_qty < 0:
            closing = min(pre_position, abs(signed_qty))
            self.pnl.realized += closing * (price - state.vwap)
        elif pre_position < 0 and signed_qty > 0:
            closing = min(abs(pre_position), signed_qty)
            self.pnl.realized += closing * (state.vwap - price)

        new_position = pre_position + signed_qty

        if pre_position == 0 or (pre_position > 0 and signed_qty > 0) or (pre_position < 0 and signed_qty < 0):
            total_size = abs(pre_position) + abs(signed_qty)
            if total_size > 0:
                state.vwap = (
                    (state.vwap * abs(pre_position)) + (price * abs(signed_qty))
                ) / total_size
        else:
            residual = new_position
            if residual == 0:
                state.vwap = price
            elif (residual > 0 and signed_qty > 0) or (residual < 0 and signed_qty < 0):
                state.vwap = price

        state.position = new_position

    async def _refresh_order_books(self) -> None:
        tasks = [self.client.get_order_book(symbol) for symbol in config.ALL_SYMBOLS]
        snapshots = await asyncio.gather(*tasks, return_exceptions=True)
        for symbol, snapshot in zip(config.ALL_SYMBOLS, snapshots):
            if isinstance(snapshot, Exception):
                self._logger.debug("orderbook refresh failed", exc_info=snapshot)
                continue
            self.market[symbol] = snapshot
            self._update_volatility(symbol, snapshot.order_book.mid)

    def _mid_map(self) -> dict[str, float]:
        return {
            symbol: snapshot.order_book.mid
            for symbol, snapshot in self.market.items()
            if snapshot.order_book.mid is not None
        }

    def _compute_synthetic_fair(self, mid_map: dict[str, float]) -> Optional[float]:
        weights = config.SYNTHETIC_WEIGHTS
        total = 0.0
        weight_sum = 0.0
        for symbol, weight in weights.items():
            mid = mid_map.get(symbol)
            if mid is None:
                continue
            total += weight * mid
            weight_sum += weight
        if weight_sum == 0:
            return mid_map.get(config.ETF_SYMBOL)
        return total

    def _compute_mispricing_bps(
        self, mid_map: dict[str, float], synthetic_fair: Optional[float]
    ) -> float:
        if synthetic_fair is None or synthetic_fair <= 0:
            return 0.0
        etf_mid = mid_map.get(config.ETF_SYMBOL)
        if etf_mid is None or etf_mid <= 0:
            return 0.0
        return (etf_mid - synthetic_fair) / synthetic_fair * 10_000

    async def _quote_all(
        self,
        mid_map: dict[str, float],
        synthetic_fair: Optional[float],
        spread_scale: float,
        size_scale: float,
        etf_mispricing_bps: float,
    ) -> None:
        coroutines = []
        symbol_order = sorted(
            config.ALL_SYMBOLS,
            key=lambda sym: self._symbol_priority(sym, etf_mispricing_bps),
            reverse=True,
        )
        for symbol in symbol_order:
            snapshot = self.market.get(symbol)
            if snapshot is None:
                continue
            fair_value = synthetic_fair if symbol == config.ETF_SYMBOL else mid_map.get(symbol)
            if fair_value is None:
                continue
            inventory_skew = compute_inventory_skew(
                self.positions[symbol].position, config.RISK_LIMITS.max_position
            )
            spread_multiplier = self._spread_scale_adjust(symbol, etf_mispricing_bps)
            bid_scale, ask_scale = self._side_size_scales(symbol, etf_mispricing_bps)
            ctx = QuoteContext(
                fair_value=fair_value,
                volatility_bps=max(1.0, self._volatility_bps.get(symbol, 5.0)),
                inventory_skew_bps=inventory_skew,
                spread_scale=spread_scale * spread_multiplier,
                size_scale=size_scale,
                bid_size_scale=bid_scale,
                ask_size_scale=ask_scale,
            )
            bids, asks = build_ladders(snapshot, ctx, self.symbol_configs[symbol])
            coroutines.append(self._order_manager.sync_symbol(symbol, bids, asks))
        if coroutines:
            await asyncio.gather(*coroutines)

    def _symbol_priority(self, symbol: str, etf_mispricing_bps: float) -> float:
        mispricing_component = abs(etf_mispricing_bps)
        if symbol != config.ETF_SYMBOL:
            mispricing_component *= config.SYNTHETIC_WEIGHTS.get(symbol, 0.0)
        inventory_ratio = abs(self.positions[symbol].position) / max(
            1, config.RISK_LIMITS.max_position
        )
        priority = mispricing_component + inventory_ratio * config.INVENTORY_PRIORITY_WEIGHT
        if symbol == config.ETF_SYMBOL:
            priority += 10.0
        return priority

    def _mispricing_intensity(self, etf_mispricing_bps: float, weight: float = 1.0) -> float:
        if weight <= 0:
            return 0.0
        base = min(abs(etf_mispricing_bps) / max(1.0, config.MISPRICING_INTENSITY_BPS), 1.0)
        return max(0.0, min(1.0, base * weight))

    def _spread_scale_adjust(self, symbol: str, etf_mispricing_bps: float) -> float:
        weight = 1.0 if symbol == config.ETF_SYMBOL else config.SYNTHETIC_WEIGHTS.get(symbol, 0.0)
        intensity = self._mispricing_intensity(etf_mispricing_bps, weight)
        return 1.0 + intensity * config.MISPRICING_SPREAD_WIDEN

    def _side_size_scales(self, symbol: str, etf_mispricing_bps: float) -> tuple[float, float]:
        weight = 1.0 if symbol == config.ETF_SYMBOL else config.SYNTHETIC_WEIGHTS.get(symbol, 0.0)
        if etf_mispricing_bps == 0.0 or weight <= 0:
            return 1.0, 1.0
        intensity = self._mispricing_intensity(etf_mispricing_bps, weight)
        bonus = 1.0 + intensity * config.MISPRICING_SIZE_BONUS
        penalty = max(0.5, 1.0 - intensity * config.MISPRICING_SIZE_PENALTY)
        if symbol == config.ETF_SYMBOL:
            if etf_mispricing_bps > 0:
                return penalty, bonus
            return bonus, penalty
        if etf_mispricing_bps > 0:
            return bonus, penalty
        return penalty, bonus

    def _update_volatility(self, symbol: str, mid: Optional[float]) -> None:
        if mid is None or mid <= 0:
            return
        previous = self._last_mid.get(symbol)
        self._last_mid[symbol] = mid
        if previous is None or previous <= 0:
            self._volatility_bps[symbol] = max(5.0, self._volatility_bps.get(symbol, 5.0))
            return
        move_bps = abs(mid - previous) / previous * 10_000
        alpha = config.VOL_SMOOTHING_ALPHA
        prior = self._volatility_bps.get(symbol, move_bps)
        self._volatility_bps[symbol] = (1 - alpha) * prior + alpha * move_bps

    def _resting_notional_scale(self, mid_map: dict[str, float]) -> float:
        base = 0.0
        for symbol, cfg in self.symbol_configs.items():
            mid = mid_map.get(symbol)
            if mid is None:
                continue
            size_sum = 0.0
            size = cfg.base_size
            for _ in range(cfg.max_levels):
                size_sum += size
                size = max(1, int(size * cfg.size_multiplier))
            base += 2 * mid * size_sum
        if base <= 0:
            return 1.0
        ratio = config.TARGET_RESTING_NOTIONAL / base
        return max(0.5, min(3.0, ratio))

    def _exposure_size_scale(self, exposure: float) -> float:
        limit = config.RISK_LIMITS.max_dollar_exposure
        if exposure <= 0 or exposure <= limit:
            return 1.0
        scale = limit / exposure
        return max(0.25, min(1.0, scale))

    def _maybe_log_metrics(
        self,
        etf_mispricing_bps: float,
        exposure: float,
        drawdown_pct: float,
        size_scale: float,
    ) -> None:
        now = time.monotonic()
        if now - self._last_metrics_log < config.TELEMETRY_INTERVAL_SECONDS:
            return
        self._last_metrics_log = now
        self._logger.info(
            "telemetry mispricing=%.1fbps exposure=$%.0f drawdown=%.2f%% size_scale=%.2f realized=$%.0f unrealized=$%.0f",
            etf_mispricing_bps,
            exposure,
            drawdown_pct * 100,
            size_scale,
            self.pnl.realized,
            self.pnl.unrealized,
        )

    async def _sleep(self, loop_start: float) -> None:
        elapsed = time.perf_counter() - loop_start
        delay = max(0.0, config.LOOP_DELAY_SECONDS - elapsed)
        if delay > 0:
            await asyncio.sleep(delay)
