"""Short Strangle strategy specific configuration and models."""

from dataclasses import dataclass
from typing import Optional
from datetime import time

from src.core.models.trade import StrategyTrade, StrategyLeg, LegStatus, StrategyState


@dataclass
class ShortStrangleConfig:
    """Configuration parameters for 0DTE Short Strangle strategy."""
    underlying: str = "BTC"
    target_premium: float = 100.0
    premium_tolerance_usd: float = 30.0
    quantity: float = 1.0  # 1 contract (0.001 BTC on Delta Exchange India)
    sl_percentage: float = 1.0  # 100% stop loss
    entry_time: time = time(9, 0, 0)
    entry_window_minutes: int = 15
    exit_time: time = time(17, 15, 0)
    max_daily_loss_usd: float = 500.0
    max_entry_retries: int = 3
    entry_retry_cooldown_seconds: float = 15.0
