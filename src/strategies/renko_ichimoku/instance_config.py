"""Per-symbol Renko Ichimoku instance configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenkoInstanceConfig:
    """One live Renko+Ichimoku stream (symbol, box, size, state file)."""

    instance_id: str
    strategy_code: str
    symbol: str
    box_size: float
    position_size: float
    state_file: str
    candle_resolution: str = "15m"
    flatten: bool = False
    position_sizing_mode: str = "fixed"
    sizing_base_usd: float = 100.0
    margin_pct: float = 0.25
    leverage: float = 10.0
    profit_retain_pct: float = 0.5


RENKO_ETH_STRATEGY_CODE = "renko_ichimoku_eth"
RENKO_SOL_STRATEGY_CODE = "renko_ichimoku_sol"
RENKO_XRP_STRATEGY_CODE = "renko_ichimoku_xrp"
RENKO_LEGACY_STRATEGY_CODE = "renko_ichimoku"
