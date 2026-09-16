"""Unified order execution pipeline — paper/live/dry-run parity."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Dict, Optional

from src.config.settings import Settings
from src.platform.execution.activity_logger import ExecutionActivityLogger
from src.platform.execution.adapter_base import ExecutionAdapter
from src.platform.execution.delta_execution_adapter import DeltaExecutionAdapter
from src.platform.execution.dry_run_execution_adapter import LiveDryRunExecutionAdapter
from src.platform.execution.lifecycle_repository import OrderLifecycleRepository
from src.platform.execution.models import ExecutionLayerMode, ExecutionResult, OrderIntent, OrderLifecycleStatus
from src.platform.execution.paper_execution_adapter import PaperExecutionAdapter
from src.platform.execution.validation_stats import ValidationStatsRepository
from src.platform.runtime.models import ExecutionMode, RiskCheckResult, RuntimeContext
from src.platform.runtime.repository import RuntimeRepository
from src.platform.runtime.risk_engine import PlatformRiskEngine
from src.platform.runtime.safety import ExecutionSafetyChecker


class OrderExecutionPipeline:
    """Signal → intent → risk → idempotency → execution adapter → lifecycle."""

    def __init__(
        self,
        *,
        context: RuntimeContext,
        settings: Settings,
        safety_checker: ExecutionSafetyChecker,
        runtime_repository: RuntimeRepository,
        lifecycle_repository: OrderLifecycleRepository,
        credentials: Dict[str, str],
        audit_callback: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        activity_logger: Optional[ExecutionActivityLogger] = None,
        validation_stats: Optional[ValidationStatsRepository] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.context = context
        self.settings = settings
        self.safety = safety_checker
        self.runtime_repo = runtime_repository
        self.lifecycle_repo = lifecycle_repository
        self.credentials = credentials
        self.audit = audit_callback
        self.event = event_callback
        self.activity = activity_logger
        self.validation_stats = validation_stats
        self.logger = logger or logging.getLogger("order_execution_pipeline")
        self._adapter: Optional[ExecutionAdapter] = None
        self._entries_halted = False

    @property
    def entries_halted(self) -> bool:
        return self._entries_halted

    def halt_new_entries(self, reason: str) -> None:
        self._entries_halted = True
        self.logger.warning("Entries halted for %s: %s", self.context.strategy_account_id, reason)

    def check_kill_switch(self) -> bool:
        """Re-check global kill switch — used during long-running operations."""
        if self.context.execution_mode == ExecutionMode.LIVE and not self.settings.platform_live_trading_enabled:
            self.halt_new_entries("Global kill switch activated")
            return False
        return True

    async def initialize(self) -> None:
        self._adapter = self._build_adapter()

    async def close(self) -> None:
        if self._adapter:
            await self._adapter.close()
            self._adapter = None

    def _build_adapter(self) -> ExecutionAdapter:
        mode = self._resolve_execution_layer()
        if mode == ExecutionLayerMode.PAPER:
            return PaperExecutionAdapter(self.logger)
        if mode == ExecutionLayerMode.LIVE_DRY_RUN:
            return LiveDryRunExecutionAdapter(self.logger)
        return DeltaExecutionAdapter(
            api_key=self.credentials.get("api_key", ""),
            api_secret=self.credentials.get("api_secret", ""),
            is_testnet=self.context.is_testnet,
            logger=self.logger,
        )

    def _resolve_execution_layer(self) -> ExecutionLayerMode:
        if self.context.execution_mode == ExecutionMode.PAPER:
            return ExecutionLayerMode.PAPER
        if self.context.execution_mode == ExecutionMode.LIVE_DRY_RUN:
            return ExecutionLayerMode.LIVE_DRY_RUN
        if (
            self.settings.platform_runtime_execution_enabled
            and self.settings.platform_delta_live_enabled
            and self.settings.platform_live_trading_enabled
        ):
            return ExecutionLayerMode.LIVE
        if getattr(self.settings, "platform_live_dry_run_enabled", True):
            return ExecutionLayerMode.LIVE_DRY_RUN
        return ExecutionLayerMode.PAPER

    async def process_intent(
        self,
        intent: OrderIntent,
        *,
        runtime_status: str,
        market_data_fresh: bool = True,
        group_id: Optional[uuid.UUID] = None,
        leg_role: Optional[str] = None,
    ) -> ExecutionResult:
        if not self.check_kill_switch():
            return ExecutionResult(False, OrderLifecycleStatus.REJECTED, intent.client_order_id, message="Global kill switch active")

        if self._entries_halted and not intent.metadata.get("allow_when_halted"):
            return ExecutionResult(
                success=False,
                status=OrderLifecycleStatus.REJECTED,
                client_order_id=intent.client_order_id,
                message="New entries halted due to reconciliation",
            )

        layer = self._resolve_execution_layer()
        duplicate = not await self.runtime_repo.reserve_idempotency_key(
            self.context.strategy_account_id,
            intent.client_order_id,
            signal_key=intent.signal_key,
        )
        if duplicate:
            await self._track("duplicate_prevented")
            await self._activity("order.duplicate_prevented", "WARNING", intent, layer, OrderLifecycleStatus.REJECTED)
            return ExecutionResult(False, OrderLifecycleStatus.REJECTED, intent.client_order_id, message="Duplicate client order ID")

        if not market_data_fresh and not intent.metadata.get("allow_when_halted"):
            await self._track("market_data_rejected")
            await self._activity("order.market_data_rejected", "WARNING", intent, layer, OrderLifecycleStatus.REJECTED)
            return ExecutionResult(False, OrderLifecycleStatus.REJECTED, intent.client_order_id, message="Market data stale")

        safety = self.safety.check_order_submission(
            self.context,
            runtime_status=runtime_status,
            adapter_supports_execution=self.context.exchange == "delta_india",
            market_data_fresh=market_data_fresh,
            duplicate_signal=False,
        )
        if not safety.approved:
            await self._track("risk_rejected")
            await self._emit("strategy.risk.rejected" if safety.code.startswith("max_") else "strategy.order.rejected", {
                "code": safety.code,
                "reason": safety.reason,
                "client_order_id": intent.client_order_id,
            })
            await self._activity("order.rejected", "WARNING", intent, layer, OrderLifecycleStatus.REJECTED, metadata={"code": safety.code})
            return ExecutionResult(False, OrderLifecycleStatus.REJECTED, intent.client_order_id, message=safety.reason)

        intent_id = await self.lifecycle_repo.create_intent(
            strategy_account_id=self.context.strategy_account_id,
            runtime_id=self.context.runtime_id,
            intent=intent,
            execution_mode=layer.value,
            status=OrderLifecycleStatus.RISK_CHECK,
            group_id=group_id,
            leg_role=leg_role,
        )

        risk = PlatformRiskEngine.for_context(self.context).evaluate_order(
            order_size=intent.quantity,
            open_positions=len(self.context.risk_overrides.get("open_positions_list", [])) if isinstance(self.context.risk_overrides.get("open_positions_list"), list) else 0,
        )
        if layer == ExecutionLayerMode.LIVE:
            max_qty = getattr(self.settings, "platform_max_live_test_quantity", None)
            if max_qty is not None and intent.quantity > float(max_qty) and not intent.metadata.get("is_unwind"):
                risk = RiskCheckResult(approved=False, reason=f"Exceeds max live test quantity ({max_qty})", code="max_live_test_quantity")
            est_price = intent.price or float(intent.metadata.get("estimated_premium") or 0)
            max_notional = getattr(self.settings, "platform_max_live_test_notional", None)
            if risk.approved and max_notional is not None and est_price > 0:
                notional = intent.quantity * est_price
                if notional > float(max_notional) and not intent.metadata.get("is_unwind"):
                    risk = RiskCheckResult(approved=False, reason=f"Exceeds max live test notional ({max_notional})", code="max_live_test_notional")

        if not risk.approved:
            await self._track("risk_rejected")
            await self.lifecycle_repo.update_status(
                self.context.strategy_account_id, intent.client_order_id, OrderLifecycleStatus.REJECTED, last_error=risk.reason
            )
            await self._emit("strategy.risk.rejected", {"code": risk.code, "reason": risk.reason})
            await self._activity("risk.rejected", "WARNING", intent, layer, OrderLifecycleStatus.REJECTED, metadata={"code": risk.code})
            return ExecutionResult(False, OrderLifecycleStatus.REJECTED, intent.client_order_id, message=risk.reason)

        await self._track("signals_generated")
        await self._emit("strategy.signal.generated", {"signal_key": intent.signal_key, "symbol": intent.symbol})
        await self._activity("signal.generated", "INFO", intent, layer, OrderLifecycleStatus.RISK_CHECK)
        await self._audit("execution.risk_approved", {"client_order_id": intent.client_order_id, "symbol": intent.symbol})

        if not self._adapter:
            await self.initialize()
        assert self._adapter is not None
        await self._adapter.initialize()

        await self.lifecycle_repo.update_status(
            self.context.strategy_account_id, intent.client_order_id, OrderLifecycleStatus.SUBMITTED
        )
        await self._emit("strategy.order.submitted", {"client_order_id": intent.client_order_id, "mode": layer.value})

        if layer == ExecutionLayerMode.LIVE_DRY_RUN:
            await self._track("would_execute")
            await self._activity("order.would_execute", "INFO", intent, layer, OrderLifecycleStatus.WOULD_EXECUTE, metadata={
                "estimated_price": intent.price or intent.metadata.get("estimated_premium"),
                "risk_result": "approved",
            })
            await self._audit("execution.would_execute", {
                "client_order_id": intent.client_order_id,
                "symbol": intent.symbol,
                "side": intent.side,
                "quantity": intent.quantity,
            })

        result = await self._adapter.place_order(intent)
        result.order_intent_id = intent_id
        await self.lifecycle_repo.update_status(
            self.context.strategy_account_id,
            intent.client_order_id,
            result.status,
            exchange_order_id=result.exchange_order_id,
            last_error=result.message if not result.success else None,
            filled_quantity=result.filled_quantity,
            average_fill_price=result.average_price,
        )

        if result.status == OrderLifecycleStatus.UNKNOWN:
            self.halt_new_entries("Order state unknown after submission")
            await self._audit("reconciliation.order_unknown", {"client_order_id": intent.client_order_id})
            await self._activity("order.unknown", "CRITICAL", intent, layer, result.status)

        if result.success and result.status in {OrderLifecycleStatus.FILLED, OrderLifecycleStatus.WOULD_EXECUTE}:
            await self.runtime_repo.update_idempotency_status(
                self.context.strategy_account_id, intent.client_order_id, status=result.status.value
            )
            await self._emit("strategy.order.filled", {"client_order_id": intent.client_order_id, "mode": layer.value})
            await self._activity("order.filled", "INFO", intent, layer, result.status, exchange_order_id=result.exchange_order_id)
        elif not result.success:
            await self._emit("strategy.order.rejected", {"client_order_id": intent.client_order_id, "reason": result.message})
            await self._activity("order.rejected", "ERROR", intent, layer, result.status, metadata={"reason": result.message})

        return result

    async def resolve_intent_result(self, client_order_id: str) -> Optional[ExecutionResult]:
        """Rebuild execution result from persisted intent (idempotent replay)."""
        row = await self.lifecycle_repo.get_by_client_id(self.context.strategy_account_id, client_order_id)
        if not row:
            return None
        status = OrderLifecycleStatus(row["status"])
        success = status in {OrderLifecycleStatus.FILLED, OrderLifecycleStatus.WOULD_EXECUTE, OrderLifecycleStatus.PARTIALLY_FILLED}
        return ExecutionResult(
            success=success,
            status=status,
            client_order_id=client_order_id,
            exchange_order_id=row.get("exchange_order_id"),
            filled_quantity=float(row.get("filled_quantity") or 0),
            average_price=float(row["average_fill_price"]) if row.get("average_fill_price") is not None else None,
            order_intent_id=row.get("id"),
        )

    async def _track(self, counter: str) -> None:
        if self.validation_stats:
            await self.validation_stats.increment(self.context.strategy_account_id, counter)

    async def _activity(
        self,
        event_type: str,
        severity: str,
        intent: OrderIntent,
        layer: ExecutionLayerMode,
        status: OrderLifecycleStatus,
        *,
        exchange_order_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.activity:
            return
        await self.activity.log(
            strategy_account_id=self.context.strategy_account_id,
            runtime_id=self.context.runtime_id,
            event_type=event_type,
            severity=severity,
            signal_key=intent.signal_key,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            execution_mode=layer.value,
            order_status=status.value,
            exchange_order_id=exchange_order_id,
            metadata=metadata,
        )

    async def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.event:
            return
        full = {"strategy_account_id": str(self.context.strategy_account_id), **payload}
        result = self.event(event_type, full)
        if hasattr(result, "__await__"):
            await result

    async def _audit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.audit:
            return
        result = self.audit(event_type, payload)
        if hasattr(result, "__await__"):
            await result
