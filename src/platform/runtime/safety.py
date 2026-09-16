"""Pre-execution safety checks for strategy runtimes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.exchanges.registry import get_exchange_definition
from src.platform.runtime.models import ExecutionMode, RuntimeContext, SafetyCheckResult


class ExecutionSafetyChecker:
    """Validates all conditions before runtime start or order submission."""

    def __init__(
        self,
        *,
        platform_runtime_execution_enabled: bool = False,
        platform_live_trading_enabled: bool = False,
        platform_delta_live_enabled: bool = False,
    ):
        self.platform_runtime_execution_enabled = platform_runtime_execution_enabled
        self.platform_live_trading_enabled = platform_live_trading_enabled
        self.platform_delta_live_enabled = platform_delta_live_enabled

    def check_runtime_start(self, ctx: RuntimeContext) -> SafetyCheckResult:
        checks = [
            self._subscription_active(ctx),
            self._exchange_connected(ctx),
        ]
        for result in checks:
            if not result.approved:
                return result
        return SafetyCheckResult(approved=True)

    def check_order_submission(
        self,
        ctx: RuntimeContext,
        *,
        runtime_status: str,
        adapter_supports_execution: bool,
        market_data_fresh: bool = True,
        symbol_supported: bool = True,
        duplicate_signal: bool = False,
    ) -> SafetyCheckResult:
        checks = [
            self._global_live_enabled(ctx),
            self._account_trading_enabled(ctx),
            self._trading_enabled(ctx),
            self._runtime_running(runtime_status),
            self._subscription_allows_entries(ctx),
            self._exchange_connected(ctx),
            self._execution_supported(ctx, adapter_supports_execution),
            self._live_gate(ctx),
            self._market_data_fresh(market_data_fresh),
            self._symbol_supported(symbol_supported),
            self._no_duplicate_signal(duplicate_signal),
        ]
        for result in checks:
            if not result.approved:
                return result
        return SafetyCheckResult(approved=True)

    def check_live_enable(self, ctx: RuntimeContext) -> SafetyCheckResult:
        if ctx.execution_mode == ExecutionMode.LIVE_DRY_RUN:
            return SafetyCheckResult(approved=True)
        if ctx.execution_mode != ExecutionMode.LIVE:
            return SafetyCheckResult(approved=False, code="not_live_mode", reason="Use enable-live endpoint first")
        if not self.platform_runtime_execution_enabled:
            return SafetyCheckResult(
                approved=False,
                code="platform_disabled",
                reason="Platform runtime execution is disabled by server configuration",
            )
        if not self.platform_delta_live_enabled:
            return SafetyCheckResult(
                approved=False,
                code="delta_live_disabled",
                reason="Delta live execution is disabled by server configuration",
            )
        if not self.platform_live_trading_enabled:
            return SafetyCheckResult(
                approved=False,
                code="global_kill_switch",
                reason="Global live trading is disabled",
            )
        definition = get_exchange_definition(ctx.exchange)
        if not definition or not definition.supports_execution:
            return SafetyCheckResult(
                approved=False,
                code="exchange_not_supported",
                reason=f"Live execution is not supported for {ctx.exchange}",
            )
        return SafetyCheckResult(approved=True)

    @staticmethod
    def _trading_enabled(ctx: RuntimeContext) -> SafetyCheckResult:
        if not ctx.trading_enabled:
            return SafetyCheckResult(approved=False, code="trading_disabled", reason="Trading is disabled for this strategy account")
        return SafetyCheckResult(approved=True)

    @staticmethod
    def _runtime_running(runtime_status: str) -> SafetyCheckResult:
        if runtime_status != "RUNNING":
            return SafetyCheckResult(approved=False, code="runtime_not_running", reason=f"Runtime status is {runtime_status}")
        return SafetyCheckResult(approved=True)

    @staticmethod
    def _subscription_active(ctx: RuntimeContext) -> SafetyCheckResult:
        status = (ctx.subscription_status or "").upper()
        if status in {"CANCELLED", "EXPIRED"}:
            return SafetyCheckResult(approved=False, code="subscription_ended", reason=f"Subscription is {status}")
        if status not in {"ACTIVE", "TRIAL", "PAUSED"}:
            return SafetyCheckResult(approved=False, code="subscription_inactive", reason=f"Subscription is {status}")
        return SafetyCheckResult(approved=True)

    @staticmethod
    def _subscription_allows_entries(ctx: RuntimeContext) -> SafetyCheckResult:
        status = (ctx.subscription_status or "").upper()
        if status in {"CANCELLED", "EXPIRED"}:
            return SafetyCheckResult(approved=False, code="subscription_ended", reason=f"Subscription is {status}")
        if status == "PAUSED":
            return SafetyCheckResult(approved=False, code="subscription_paused", reason="Subscription is paused — no new entries")
        if status not in {"ACTIVE", "TRIAL"}:
            return SafetyCheckResult(approved=False, code="subscription_inactive", reason=f"Subscription is {status}")
        return SafetyCheckResult(approved=True)

    @staticmethod
    def _exchange_connected(ctx: RuntimeContext) -> SafetyCheckResult:
        health = (ctx.exchange_health_status or "").upper()
        if health not in {"CONNECTED", "DEGRADED"}:
            return SafetyCheckResult(approved=False, code="exchange_not_connected", reason="Exchange account is not connected")
        return SafetyCheckResult(approved=True)

    @staticmethod
    def _execution_supported(ctx: RuntimeContext, adapter_supports_execution: bool) -> SafetyCheckResult:
        if ctx.execution_mode in {ExecutionMode.PAPER, ExecutionMode.LIVE_DRY_RUN}:
            return SafetyCheckResult(approved=True)
        if not adapter_supports_execution:
            return SafetyCheckResult(approved=False, code="execution_not_supported", reason="Exchange adapter does not support execution")
        return SafetyCheckResult(approved=True)

    def _global_live_enabled(self, ctx: RuntimeContext) -> SafetyCheckResult:
        if ctx.execution_mode != ExecutionMode.LIVE:
            return SafetyCheckResult(approved=True)
        if not self.platform_live_trading_enabled:
            return SafetyCheckResult(approved=False, code="global_kill_switch", reason="Global live trading is disabled")
        return SafetyCheckResult(approved=True)

    @staticmethod
    def _account_trading_enabled(ctx: RuntimeContext) -> SafetyCheckResult:
        if not ctx.exchange_trading_enabled:
            return SafetyCheckResult(approved=False, code="account_trading_disabled", reason="Exchange account trading is disabled")
        return SafetyCheckResult(approved=True)

    def _live_gate(self, ctx: RuntimeContext) -> SafetyCheckResult:
        if ctx.execution_mode in {ExecutionMode.PAPER, ExecutionMode.LIVE_DRY_RUN}:
            return SafetyCheckResult(approved=True)
        if not self.platform_runtime_execution_enabled:
            return SafetyCheckResult(approved=False, code="platform_disabled", reason="Platform live execution disabled")
        if not self.platform_delta_live_enabled:
            return SafetyCheckResult(approved=False, code="delta_live_disabled", reason="Delta live execution disabled")
        return SafetyCheckResult(approved=True)

    @staticmethod
    def _market_data_fresh(market_data_fresh: bool) -> SafetyCheckResult:
        if not market_data_fresh:
            return SafetyCheckResult(approved=False, code="stale_market_data", reason="Market data is stale")
        return SafetyCheckResult(approved=True)

    @staticmethod
    def _symbol_supported(symbol_supported: bool) -> SafetyCheckResult:
        if not symbol_supported:
            return SafetyCheckResult(approved=False, code="unsupported_symbol", reason="Symbol is not supported")
        return SafetyCheckResult(approved=True)

    @staticmethod
    def _no_duplicate_signal(duplicate_signal: bool) -> SafetyCheckResult:
        if duplicate_signal:
            return SafetyCheckResult(approved=False, code="duplicate_signal", reason="Duplicate signal detected")
        return SafetyCheckResult(approved=True)

    @staticmethod
    def subscription_allows_runtime(subscription_status: str, expires_at: Optional[datetime] = None) -> SafetyCheckResult:
        status = (subscription_status or "").upper()
        if status in {"CANCELLED", "EXPIRED"}:
            return SafetyCheckResult(approved=False, code="subscription_ended", reason=f"Subscription is {status}")
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at and expires_at < datetime.now(timezone.utc):
            return SafetyCheckResult(approved=False, code="subscription_expired", reason="Subscription has expired")
        return SafetyCheckResult(approved=True)
