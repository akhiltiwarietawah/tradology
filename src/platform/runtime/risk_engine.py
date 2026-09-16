"""Central risk engine for platform strategy execution."""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.platform.runtime.models import RiskCheckResult, RuntimeContext


class PlatformRiskEngine:
    """Evaluates configurable risk limits before order submission."""

    DEFAULT_LIMITS = {
        "max_position_size": None,
        "max_order_size": None,
        "max_leverage": None,
        "max_daily_loss": None,
        "max_drawdown_pct": None,
        "max_open_positions": None,
    }

    def __init__(self, limits: Optional[Dict[str, Any]] = None):
        merged = dict(self.DEFAULT_LIMITS)
        if limits:
            merged.update(limits)
        self.limits = merged

    @classmethod
    def for_context(cls, ctx: RuntimeContext) -> "PlatformRiskEngine":
        limits = dict(cls.DEFAULT_LIMITS)
        limits.update(ctx.risk_settings or {})
        limits.update(ctx.risk_overrides or {})
        return cls(limits)

    def evaluate_order(
        self,
        *,
        order_size: float,
        leverage: Optional[float] = None,
        open_positions: int = 0,
        daily_pnl: float = 0.0,
        drawdown_pct: Optional[float] = None,
    ) -> RiskCheckResult:
        max_order = self._float_limit("max_order_size")
        if max_order is not None and order_size > max_order:
            return RiskCheckResult(approved=False, code="max_order_size", reason="Order size exceeds limit")

        max_position = self._float_limit("max_position_size")
        if max_position is not None and order_size > max_position:
            return RiskCheckResult(approved=False, code="max_position_size", reason="Position size exceeds limit")

        max_leverage = self._float_limit("max_leverage")
        if max_leverage is not None and leverage is not None and leverage > max_leverage:
            return RiskCheckResult(approved=False, code="max_leverage", reason="Leverage exceeds limit")

        max_daily_loss = self._float_limit("max_daily_loss")
        if max_daily_loss is not None and daily_pnl <= -abs(max_daily_loss):
            return RiskCheckResult(approved=False, code="max_daily_loss", reason="Daily loss limit reached")

        max_drawdown = self._float_limit("max_drawdown_pct")
        if max_drawdown is not None and drawdown_pct is not None and drawdown_pct >= max_drawdown:
            return RiskCheckResult(approved=False, code="max_drawdown", reason="Drawdown limit reached")

        max_open = self._float_limit("max_open_positions")
        if max_open is not None and open_positions >= int(max_open):
            return RiskCheckResult(approved=False, code="max_open_positions", reason="Maximum open positions reached")

        return RiskCheckResult(approved=True)

    def _float_limit(self, key: str) -> Optional[float]:
        value = self.limits.get(key)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
