"""Static configuration used by the Delta Exchange bot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class SymbolConfig:
    """Per-symbol configuration for level ladders."""

    symbol: str
    base_size: int
    size_multiplier: float
    base_spread_bps: int
    level_spread_step_bps: int
    max_levels: int


@dataclass(frozen=True)
class RiskLimits:
    max_position: int
    max_dollar_exposure: float
    drawdown_stop_pct: float
    hard_stop_pct: float


BASE_CURRENCY: Final[str] = "USD"
ETF_SYMBOL: Final[str] = "ETF"
BASKET_SYMBOLS: Final[tuple[str, ...]] = ("XYZ", "ABC", "DEF")
ALL_SYMBOLS: Final[tuple[str, ...]] = (ETF_SYMBOL,) + BASKET_SYMBOLS
SYNTHETIC_WEIGHTS: Final[dict[str, float]] = {"XYZ": 0.5, "ABC": 0.3, "DEF": 0.2}

LOOP_DELAY_SECONDS: Final[float] = 0.01  # 100 Hz target
MIN_MOVE_TO_REFRESH_BPS: Final[int] = 2
MAX_ACTIONS_PER_SECOND: Final[int] = 95
POSITIONS_REFRESH_SECONDS: Final[float] = 1.0

MAKER_REBATE_BPS: Final[float] = 2.0
TAKER_FEE_BPS: Final[float] = 5.0
EFFECTIVE_MAKER_EDGE_BPS: Final[float] = MAKER_REBATE_BPS + TAKER_FEE_BPS

DEFAULT_SYMBOL_CONFIG: Final[dict[str, SymbolConfig]] = {
    symbol: SymbolConfig(
        symbol=symbol,
        base_size=400,
        size_multiplier=1.5,
        base_spread_bps=15,
        level_spread_step_bps=15,
        max_levels=6,
    )
    for symbol in ALL_SYMBOLS
}

RISK_LIMITS: Final[RiskLimits] = RiskLimits(
    max_position=25_000,
    max_dollar_exposure=5_000_000.0,
    drawdown_stop_pct=0.15,
    hard_stop_pct=0.25,
)

TARGET_NOTIONAL_UTILIZATION: Final[float] = 0.8
NOTIONAL_CAPITAL: Final[float] = 1_000_000.0
TARGET_RESTING_NOTIONAL: Final[float] = NOTIONAL_CAPITAL * TARGET_NOTIONAL_UTILIZATION

VOL_SMOOTHING_ALPHA: Final[float] = 0.2

INVENTORY_SKEW_BPS: Final[int] = 8
INVENTORY_PRIORITY_WEIGHT: Final[float] = 120.0  # bps-equivalent boost per 100% inventory usage

HTTP_TIMEOUT_SECONDS: Final[float] = 0.2
HTTP_MAX_RETRIES: Final[int] = 3

EXCHANGE_HOST: Final[str] = "159.65.173.202"
GATEWAY_PORT: Final[int] = 9001
MARKET_DATA_PORT: Final[int] = 5001
SCOREKEEPER_HTTP_PORT: Final[int] = 8081
SCOREKEEPER_BASE_URL: Final[str] = f"http://{EXCHANGE_HOST}:{SCOREKEEPER_HTTP_PORT}"

TEAM_TOKEN_ENV: Final[str] = "DELTA_TOKEN"
DEFAULT_TEAM_TOKEN: Final[str] = "shortinggpa-129asfasd301"

SYMBOL_IDS: Final[dict[str, int]] = {"XYZ": 1, "ETF": 2, "ABC": 3, "DEF": 4}
ID_TO_SYMBOL: Final[dict[int, str]] = {value: key for key, value in SYMBOL_IDS.items()}
ORDER_PRICE_SCALE: Final[int] = 100  # cents per dollar

MISPRICING_INTENSITY_BPS: Final[float] = 40.0
MISPRICING_SIZE_BONUS: Final[float] = 0.8
MISPRICING_SIZE_PENALTY: Final[float] = 0.5
MISPRICING_SPREAD_WIDEN: Final[float] = 0.25

DRAWDOWN_SPREAD_MULT: Final[float] = 1.5
DRAWDOWN_SIZE_REDUCTION: Final[float] = 0.7

TELEMETRY_INTERVAL_SECONDS: Final[float] = 1.0
