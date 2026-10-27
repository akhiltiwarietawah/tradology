"""Models and configuration for BTC 0DTE Long Straddle Strategy."""

import os
from dataclasses import dataclass, field
from datetime import time
from typing import List, Literal

PositionSizingMode = Literal["fixed", "dynamic"]


@dataclass
class LongStraddleConfig:
    """Configuration for 1:00 PM IST BTC 0DTE Long Straddle on Delta Exchange."""

    # Strategy identity
    underlying_symbol: str = "BTC"
    contract_value: float = 0.001  # Delta Exchange BTC option multiplier (0.001 BTC per contract)

    # Schedule parameters
    entry_time: time = field(default_factory=lambda: time(13, 0))  # 1:00 PM IST
    entry_window_minutes: int = 15  # Entry window: 13:00 to 13:15 IST
    exit_time: time = field(default_factory=lambda: time(17, 30))   # 5:30 PM IST (Auto Expiry)

    # Allowed trading days: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4 (Sat=5, Sun=6 excluded)
    allowed_weekdays: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])

    # Position sizing: Fixed vs Dynamic
    position_sizing_mode: PositionSizingMode = "fixed"  # "fixed" or "dynamic"
    fixed_lots: int = 10                                # Default fixed lots
    dynamic_margin_pct: float = 0.25                    # Allocate 25% of equity for dynamic straddle buy
    sizing_base_usd: float = 50.0                       # Base starting equity for dynamic mode
    profit_retain_pct: float = 0.5                      # 50% profit retention (simulated 50% withdrawal)
    min_lots: int = 1
    max_lots: int = 500

    # Execution & settlement parameters
    use_auto_settlement: bool = True  # Hold till 5:30 PM cash settlement (saves exit fees on OTM legs)
    entry_order_type: str = "limit"   # Limit order to save maker fee

    @classmethod
    def from_env(cls) -> "LongStraddleConfig":
        """Load configuration from environment variables with defaults."""
        mode = os.getenv("BTC_0DTE_STRADDLE_POSITION_SIZING_MODE", "fixed").lower()
        if mode not in ("fixed", "dynamic"):
            mode = "fixed"

        allowed_days_raw = os.getenv("BTC_0DTE_STRADDLE_ALLOWED_WEEKDAYS", "0,1,2,3,4")
        try:
            allowed_days = [int(x.strip()) for x in allowed_days_raw.split(",") if x.strip()]
        except Exception:
            allowed_days = [0, 1, 2, 3, 4]

        return cls(
            underlying_symbol=os.getenv("BTC_0DTE_STRADDLE_UNDERLYING", "BTC"),
            contract_value=float(os.getenv("BTC_0DTE_STRADDLE_CONTRACT_VALUE", "0.001")),
            position_sizing_mode=mode,
            fixed_lots=int(os.getenv("BTC_0DTE_STRADDLE_FIXED_LOTS", "10")),
            dynamic_margin_pct=float(os.getenv("BTC_0DTE_STRADDLE_MARGIN_PCT", "0.25")),
            sizing_base_usd=float(os.getenv("BTC_0DTE_STRADDLE_SIZING_BASE_USD", "50.0")),
            profit_retain_pct=float(os.getenv("BTC_0DTE_STRADDLE_PROFIT_RETAIN_PCT", "0.5")),
            min_lots=int(os.getenv("BTC_0DTE_STRADDLE_MIN_LOTS", "1")),
            max_lots=int(os.getenv("BTC_0DTE_STRADDLE_MAX_LOTS", "500")),
            allowed_weekdays=allowed_days,
            use_auto_settlement=os.getenv("BTC_0DTE_STRADDLE_AUTO_SETTLEMENT", "true").lower() == "true",
        )
