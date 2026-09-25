"""Per-symbol Renko Ichimoku instance configuration."""

from __future__ import annotations

from dataclasses import dataclass

from src.strategies.renko_ichimoku.asset_registry import DEFAULT_RENKO_SIZING_BASE_USD


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
    sizing_base_usd: float = DEFAULT_RENKO_SIZING_BASE_USD
    margin_pct: float = 0.25
    leverage: float = 10.0
    profit_retain_pct: float = 0.5
    account_name: str = "renko"
    api_key: str = ""
    api_secret: str = ""


RENKO_ETH_STRATEGY_CODE = "renko_ichimoku_eth"
RENKO_SOL_STRATEGY_CODE = "renko_ichimoku_sol"
RENKO_XRP_STRATEGY_CODE = "renko_ichimoku_xrp"
RENKO_XRP2_STRATEGY_CODE = "renko_ichimoku_xrp2"
RENKO_LEGACY_STRATEGY_CODE = "renko_ichimoku"
