"""Risk Manager enforcing Max Daily Loss, Kill Switch, and safety boundaries."""

import logging
from typing import Optional, Tuple
from pathlib import Path
from src.core.models.trade import StrategyTrade


class RiskManager:
    """Oversees strategy risk parameters, max loss monitoring, and emergency halts."""

    def __init__(
        self,
        max_daily_loss_pct: Optional[float] = None,
        max_daily_loss_usd: float = 500.0,
        kill_switch: bool = False,
        kill_switch_file: Optional[str] = "data/KILL_SWITCH",
        logger: Optional[logging.Logger] = None,
    ):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_daily_loss_usd = max_daily_loss_usd
        self._kill_switch_flag = kill_switch
        self.kill_switch_file = kill_switch_file
        self.logger = logger or logging.getLogger("risk_manager")

    def get_effective_max_loss_usd(self, trade: Optional[StrategyTrade] = None) -> float:
        """Calculate effective max daily loss in USD dynamically.
        If trade has initial entry premium collected across legs and max_daily_loss_pct is set,
        limit is calculated dynamically as: total_entry_premium * max_daily_loss_pct.
        Otherwise, fall back to max_daily_loss_usd.
        """
        if trade is not None and self.max_daily_loss_pct is not None:
            entry_prem = getattr(trade, "total_entry_premium", 0.0)
            if entry_prem > 0:
                return round(entry_prem * self.max_daily_loss_pct, 4)
        return self.max_daily_loss_usd or 500.0

    @property
    def is_kill_switch_active(self) -> bool:
        if self._kill_switch_flag:
            return True
        if self.kill_switch_file and Path(self.kill_switch_file).exists():
            return True
        return False

    def activate_kill_switch(self):
        self._kill_switch_flag = True
        self.logger.critical("🚨 EMERGENCY KILL SWITCH ENGAGED! All new trading halted.")

    def check_pre_trade_safety(self, trade: Optional[StrategyTrade] = None) -> Tuple[bool, str]:
        """Perform safety checks before placing new orders."""
        if self.is_kill_switch_active:
            return False, "Kill switch is active"

        if trade is not None:
            total_loss = trade.total_realized_pnl + trade.total_unrealized_pnl
            limit = self.get_effective_max_loss_usd(trade)
            if total_loss <= -limit:
                return False, f"Max daily loss breached: current loss ${abs(total_loss):.2f} >= limit ${limit:.2f}"

        return True, "Safety checks passed"

    def check_daily_loss_limit(self, trade: StrategyTrade) -> Tuple[bool, float]:
        """Check if unrealized + realized loss breaches max limit."""
        total_pnl = trade.total_realized_pnl + trade.total_unrealized_pnl
        limit = self.get_effective_max_loss_usd(trade)
        if total_pnl <= -limit:
            self.logger.critical(
                f"🚨 MAX DAILY LOSS BREACHED! Total P&L: ${total_pnl:.2f} (Limit: -${limit:.2f})"
            )
            return True, total_pnl
        return False, total_pnl
