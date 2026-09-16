"""Integrated strategy runtime with adapter + execution pipeline."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from src.config.settings import Settings, get_settings
from src.persistence.trade_repository import TradeRepository
from src.platform.execution.activity_logger import ExecutionActivityLogger
from src.platform.execution.group_repository import StrangleGroupRepository
from src.platform.execution.lifecycle_repository import OrderLifecycleRepository
from src.platform.execution.models import OrderIntent
from src.platform.execution.pipeline import OrderExecutionPipeline
from src.platform.execution.reconciliation import OrderReconciliationService, PositionReconciliationService
from src.platform.execution.validation_stats import ValidationStatsRepository
from src.platform.runtime.adapters.short_strangle_adapter import ShortStrangleRuntimeAdapter
from src.platform.runtime.models import RuntimeContext, RuntimeStatus
from src.platform.runtime.repository import RuntimeRepository
from src.platform.runtime.runtime import StrategyRuntime
from src.platform.runtime.safety import ExecutionSafetyChecker
from src.platform.runtime.strategy_adapter_base import StrategyRuntimeAdapter
from src.platform.security.credentials import CredentialVault


class IntegratedStrategyRuntime(StrategyRuntime):
    """Runtime with strategy adapter — paper/live/dry-run share the same signal path."""

    ADAPTER_FACTORY = {
        "short_strangle": ShortStrangleRuntimeAdapter,
    }

    def __init__(
        self,
        *,
        context: RuntimeContext,
        repository: RuntimeRepository,
        safety_checker: ExecutionSafetyChecker,
        vault: CredentialVault,
        settings: Optional[Settings] = None,
        event_publisher: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        audit_callback: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        heartbeat_seconds: int = 15,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(
            context=context,
            repository=repository,
            safety_checker=safety_checker,
            event_publisher=event_publisher,
            heartbeat_seconds=heartbeat_seconds,
            logger=logger,
        )
        self.settings = settings or get_settings()
        self.vault = vault
        self.audit = audit_callback
        self._adapter: Optional[StrategyRuntimeAdapter] = None
        self._pipeline: Optional[OrderExecutionPipeline] = None
        self._strategy_task: Optional[asyncio.Task] = None
        self._lifecycle_repo = OrderLifecycleRepository(repository.db)
        self._group_repo = StrangleGroupRepository(repository.db)
        self._activity = ExecutionActivityLogger(repository.db, self.logger)
        self._validation_stats = ValidationStatsRepository(repository.db)
        self._trade_repo = TradeRepository(repository.db, self.logger)

    async def on_start(self) -> None:
        creds = await self._load_credentials()
        self._pipeline = OrderExecutionPipeline(
            context=self.context,
            settings=self.settings,
            safety_checker=self.safety_checker,
            runtime_repository=self.repository,
            lifecycle_repository=self._lifecycle_repo,
            credentials=creds,
            audit_callback=self.audit,
            event_callback=self._publish,
            activity_logger=self._activity,
            validation_stats=self._validation_stats,
            logger=self.logger,
        )
        await self._pipeline.initialize()

        factory = self.ADAPTER_FACTORY.get(self.context.strategy_code)
        if not factory:
            raise RuntimeError(f"No runtime adapter for strategy {self.context.strategy_code}")
        self._adapter = factory(
            context=self.context,
            pipeline=self._pipeline,
            credentials=creds,
            safety_checker=self.safety_checker,
            group_repository=self._group_repo,
            activity_logger=self._activity,
            trade_repository=self._trade_repo,
            settings=self.settings,
            logger=self.logger,
        )

        if self.context.runtime_id:
            state = await self.repository.get_runtime_state(self.context.runtime_id)
            await self._adapter.restore_state(state)

        await self._adapter.initialize()
        await self._run_reconciliation()
        await self._adapter.start()
        self._strategy_task = asyncio.create_task(self._strategy_loop())

    async def on_stop(self) -> None:
        if self._strategy_task:
            self._strategy_task.cancel()
            try:
                await self._strategy_task
            except asyncio.CancelledError:
                pass
        if self._adapter:
            await self._adapter.stop()
        if self._pipeline:
            await self._pipeline.close()
        if self.context.runtime_id and self._adapter:
            await self.repository.save_runtime_state(self.context.runtime_id, self._adapter.export_state())

    async def execute_signal(
        self,
        *,
        signal_key: str,
        client_order_id: str,
        order_size: float,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self._pipeline:
            return {"accepted": False, "reason": "Pipeline not initialized"}
        intent = OrderIntent(
            signal_key=signal_key,
            client_order_id=client_order_id,
            symbol=metadata.get("symbol", "UNKNOWN"),
            side=metadata.get("side", "buy"),
            quantity=order_size,
            order_type=metadata.get("order_type", "market"),
            price=metadata.get("price"),
            instrument_id=metadata.get("instrument_id"),
            metadata=metadata,
        )
        result = await self._pipeline.process_intent(
            intent,
            runtime_status=self.status.value,
            market_data_fresh=self._adapter.is_market_data_fresh if self._adapter else True,
        )
        return {
            "accepted": result.success,
            "status": result.status.value,
            "mode": result.mode.value,
            "client_order_id": client_order_id,
            "message": result.message,
        }

    async def _strategy_loop(self) -> None:
        while self.status in {RuntimeStatus.RUNNING, RuntimeStatus.PAUSED}:
            try:
                if self.status == RuntimeStatus.RUNNING and self._adapter:
                    if not self._pipeline.check_kill_switch():
                        self.status = RuntimeStatus.PAUSED
                        await self.repository.upsert_runtime(
                            self.context.strategy_account_id,
                            status=RuntimeStatus.PAUSED.value,
                            last_error="Global kill switch activated",
                        )
                        break
                    await self._adapter.on_timer(datetime.now(timezone.utc))
                    if self.context.runtime_id:
                        await self.repository.save_runtime_state(
                            self.context.runtime_id, self._adapter.export_state()
                        )
            except Exception as exc:
                self.logger.warning("Strategy loop error: %s", type(exc).__name__)
                await self._validation_stats.increment(self.context.strategy_account_id, "runtime_errors")
            await asyncio.sleep(1.0)

    async def _load_credentials(self) -> Dict[str, str]:
        from src.persistence.platform_models import ExchangeAccountModel

        async with self.repository.db.get_session() as session:
            account = await session.get(ExchangeAccountModel, self.context.exchange_account_id)
            if not account:
                raise RuntimeError("Exchange account not found")
            return self.vault.decrypt_credentials(account.credentials_encrypted)

    async def _run_reconciliation(self) -> None:
        if not self._pipeline or not self._adapter:
            return
        adapter = self._pipeline._adapter
        if not adapter:
            return
        order_rec = OrderReconciliationService(self._lifecycle_repo, self.logger)
        pos_rec = PositionReconciliationService(self.logger)

        order_report = await order_rec.reconcile(
            strategy_account_id=self.context.strategy_account_id,
            execution_adapter=adapter,
            halt_callback=self._pipeline.halt_new_entries,
            audit_callback=self.audit,
        )
        rec_status = "PASS" if order_report.matched else "FAIL"
        await self._validation_stats.set_reconciliation(self.context.strategy_account_id, rec_status)
        if not order_report.matched:
            await self.mark_error(f"Order reconciliation: {order_report.message}")
            return

        pos_report = await pos_rec.reconcile(
            expected_positions=self._adapter.get_expected_positions(),
            execution_adapter=adapter,
        )
        if not pos_report.matched:
            self._pipeline.halt_new_entries(f"Position reconciliation: {pos_report.message}")
            await self._validation_stats.set_reconciliation(self.context.strategy_account_id, "FAIL")
            await self._audit("reconciliation.position_mismatch", pos_report.details)

    async def _audit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self.audit:
            result = self.audit(event_type, payload)
            if asyncio.iscoroutine(result):
                await result

    async def get_validation_report(self) -> Dict[str, Any]:
        stats = await self._validation_stats.get_stats(self.context.strategy_account_id)
        activity = await self._validation_stats.list_activity(self.context.strategy_account_id, limit=20)
        orders = await self._lifecycle_repo.list_execution_history(self.context.strategy_account_id, limit=20)
        return {
            "strategy": self.context.strategy_code,
            "account": self.context.exchange_account_label,
            "exchange": self.context.exchange,
            "mode": self.context.execution_mode.value,
            "runtime_status": self.status.value,
            "stats": stats,
            "recent_activity": activity,
            "recent_orders": orders,
            "entries_halted": self._pipeline.entries_halted if self._pipeline else False,
        }
