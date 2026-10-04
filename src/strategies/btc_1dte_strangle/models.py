"""BTC 1-DTE short strangle configuration."""

from dataclasses import dataclass
from datetime import time


@dataclass
class Btc1DteStrangleConfig:
    """1-DTE short strangle: 10:45–11:00 PM IST entry, parso 17:25 IST exit, 100% per-leg SL."""

    underlying: str = "BTC"
    sl_percentage: float = 1.0  # 100% stop loss per leg (2× entry fill)
    straddle_distance_mult: float = 1.8
    min_otm_premium_usd: float = 20.0
    enable_combined_take_profit: bool = False
    take_profit_base_usd: float = 3.0
    take_profit_calibration_contracts: int = 100
    margin_pct: float = 0.25
    entry_time: time = time(22, 45, 0)
    entry_window_minutes: int = 15
    exit_time: time = time(17, 25, 0)
    expiry_calendar_days: int = 2
    max_entry_retries: int = 3
    entry_retry_cooldown_seconds: float = 15.0
    max_daily_loss_usd: float = 500.0
