"""Runtime validation report for LIVE_DRY_RUN inspection."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from src.config.settings import Settings
from src.platform.execution.validation_stats import ValidationStatsRepository
from src.platform.runtime.models import RuntimeContext
from src.platform.runtime.repository import RuntimeRepository


class RuntimeValidationService:
    def __init__(
        self,
        repository: RuntimeRepository,
        settings: Settings,
        validation_stats: ValidationStatsRepository,
    ):
        self.repository = repository
        self.settings = settings
        self.validation_stats = validation_stats

    async def get_report(
        self,
        ctx: RuntimeContext,
        *,
        runtime_status: Optional[str] = None,
        entries_halted: bool = False,
    ) -> Dict[str, Any]:
        stats = await self.validation_stats.get_stats(ctx.strategy_account_id)
        activity = await self.validation_stats.list_activity(ctx.strategy_account_id, limit=50)

        runtime_row = await self.repository.get_runtime_by_strategy_account(ctx.strategy_account_id)
        last_signal = next((a for a in activity if "signal" in a.get("event_type", "")), None)
        last_order = next((a for a in activity if "order" in a.get("event_type", "")), None)
        last_fill = next((a for a in activity if a.get("event_type") == "order.filled"), None)

        status = runtime_status or (runtime_row.status if runtime_row else "STOPPED")

        return {
            "strategy": ctx.strategy_code,
            "strategy_name": ctx.strategy_name,
            "account": ctx.exchange_account_label,
            "exchange": ctx.exchange,
            "mode": ctx.execution_mode.value,
            "runtime_status": status,
            "trading_enabled": ctx.trading_enabled,
            "reconciliation": stats.get("last_reconciliation") or "UNKNOWN",
            "heartbeat_healthy": bool(runtime_row and runtime_row.last_heartbeat_at),
            "last_signal_at": last_signal.get("created_at") if last_signal else None,
            "last_order_at": last_order.get("created_at") if last_order else None,
            "last_fill_at": last_fill.get("created_at") if last_fill else None,
            "entries_halted": entries_halted,
            "stats": {
                "signals_generated": stats.get("signals_generated", 0),
                "would_execute": stats.get("would_execute", 0),
                "risk_rejected": stats.get("risk_rejected", 0),
                "duplicate_prevented": stats.get("duplicate_prevented", 0),
                "market_data_rejected": stats.get("market_data_rejected", 0),
                "runtime_errors": stats.get("runtime_errors", 0),
            },
            "recent_activity": activity[:20],
            "live_flags": {
                "platform_runtime_execution_enabled": self.settings.platform_runtime_execution_enabled,
                "platform_delta_live_enabled": self.settings.platform_delta_live_enabled,
                "platform_live_trading_enabled": self.settings.platform_live_trading_enabled,
            },
            "controlled_test_limits": {
                "max_live_test_quantity": self.settings.platform_max_live_test_quantity,
                "max_live_test_notional": self.settings.platform_max_live_test_notional,
            },
        }
