"""Risk and inventory management utilities."""

from __future__ import annotations

from dataclasses import dataclass

from . import config
from .models import PnLState, Positions


@dataclass
class RiskState:
    drawdown_pct: float = 0.0
    throttled: bool = False


def compute_dollar_exposure(positions: Positions, mid_map: dict[str, float]) -> float:
    exposure = 0.0
    for symbol, state in positions.items():
        mid = mid_map.get(symbol)
        if mid is None:
            continue
        exposure += abs(state.position * mid)
    return exposure


def update_unrealized_pnl(pnl: PnLState, positions: Positions, mid_map: dict[str, float]) -> None:
    unrealized = 0.0
    for symbol, state in positions.items():
        mid = mid_map.get(symbol)
        if mid is None:
            continue
        unrealized += state.position * (mid - state.vwap)
    pnl.unrealized = unrealized
    pnl.update_high_watermark()


def compute_drawdown_pct(pnl: PnLState) -> float:
    equity = pnl.realized + pnl.unrealized
    if pnl.equity_high_watermark <= 0:
        return 0.0
    drop = pnl.equity_high_watermark - equity
    if drop <= 0:
        return 0.0
    return drop / pnl.equity_high_watermark


def drawdown_adjustments(drawdown_pct: float) -> tuple[float, float, bool]:
    limits = config.RISK_LIMITS
    if drawdown_pct >= limits.hard_stop_pct:
        return 2.0, 0.0, True
    if drawdown_pct <= limits.drawdown_stop_pct:
        return 1.0, 1.0, False
    severity = (drawdown_pct - limits.drawdown_stop_pct) / (
        limits.hard_stop_pct - limits.drawdown_stop_pct
    )
    severity = max(0.0, min(1.0, severity))
    curved = severity * severity
    spread_scale = 1.0 + curved * config.DRAWDOWN_SPREAD_MULT
    size_scale = max(0.2, 1.0 - curved * config.DRAWDOWN_SIZE_REDUCTION)
    return spread_scale, size_scale, False


__all__ = [
    "RiskState",
    "compute_dollar_exposure",
    "update_unrealized_pnl",
    "compute_drawdown_pct",
    "drawdown_adjustments",
]
