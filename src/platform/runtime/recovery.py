"""Runtime recovery after application restart."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from src.config.settings import Settings
from src.platform.execution.lifecycle_repository import OrderLifecycleRepository
from src.platform.execution.pipeline import OrderExecutionPipeline
from src.platform.execution.reconciliation import OrderReconciliationService, PositionReconciliationService
from src.platform.runtime.models import ExecutionMode, RuntimeContext, RuntimeStatus
from src.platform.runtime.repository import RuntimeRepository
from src.platform.runtime.safety import ExecutionSafetyChecker
from src.platform.security.credentials import CredentialVault


class RuntimeRecoveryService:
    def __init__(self, repository: RuntimeRepository, logger: Optional[logging.Logger] = None):
        self.repository = repository
        self.logger = logger or logging.getLogger("runtime_recovery")

    async def recover_on_startup(self, *, platform_runtime_execution_enabled: bool) -> int:
        """Mark interrupted runtimes as RECOVERY_REQUIRED instead of blindly restarting."""
        runtimes = await self.repository.list_recoverable_runtimes()
        recovered = 0
        for runtime in runtimes:
            await self.repository.upsert_runtime(
                runtime.strategy_account_id,
                status=RuntimeStatus.RECOVERY_REQUIRED.value,
                last_error="Runtime interrupted by server restart — manual review required",
            )
            await self.repository.update_strategy_account_controls(
                runtime.strategy_account_id,
                runtime_status=RuntimeStatus.RECOVERY_REQUIRED.value,
            )
            recovered += 1
            self.logger.warning(
                "Runtime %s marked RECOVERY_REQUIRED after restart (execution_enabled=%s)",
                runtime.strategy_account_id,
                platform_runtime_execution_enabled,
            )
        return recovered

    async def perform_recovery(
        self,
        ctx: RuntimeContext,
        *,
        repository: RuntimeRepository,
        safety_checker: ExecutionSafetyChecker,
        vault: CredentialVault,
        settings: Settings,
        audit_callback: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """Run the 10-step startup recovery flow before allowing LIVE resume."""
        steps: List[str] = []

        steps.append("load_runtime_state")
        state = {}
        if ctx.runtime_id:
            state = await repository.get_runtime_state(ctx.runtime_id)

        steps.append("verify_subscription")
        sub_check = safety_checker.check_runtime_start(ctx)
        if not sub_check.approved:
            return {"success": False, "message": sub_check.reason, "steps": steps}

        steps.append("verify_exchange_connection")
        conn_check = safety_checker._exchange_connected(ctx)
        if not conn_check.approved:
            return {"success": False, "message": conn_check.reason, "steps": steps}

        steps.append("verify_trading_gates")
        if ctx.execution_mode == ExecutionMode.LIVE:
            live_check = safety_checker.check_live_enable(ctx)
            if not live_check.approved:
                return {"success": False, "message": live_check.reason, "steps": steps}

        steps.append("load_credentials")
        from src.persistence.platform_models import ExchangeAccountModel

        async with repository.db.get_session() as session:
            account = await session.get(ExchangeAccountModel, ctx.exchange_account_id)
            if not account:
                return {"success": False, "message": "Exchange account not found", "steps": steps}
            creds = vault.decrypt_credentials(account.credentials_encrypted)

        lifecycle_repo = OrderLifecycleRepository(repository.db)
        pipeline = OrderExecutionPipeline(
            context=ctx,
            settings=settings,
            safety_checker=safety_checker,
            runtime_repository=repository,
            lifecycle_repository=lifecycle_repo,
            credentials=creds,
            audit_callback=audit_callback,
            logger=self.logger,
        )
        await pipeline.initialize()

        steps.append("reconcile_orders")
        order_rec = OrderReconciliationService(lifecycle_repo, self.logger)
        order_report = await order_rec.reconcile(
            strategy_account_id=ctx.strategy_account_id,
            execution_adapter=pipeline._adapter,
            halt_callback=pipeline.halt_new_entries,
            audit_callback=audit_callback,
        )
        if not order_report.matched:
            if audit_callback:
                await self._call_audit(audit_callback, "recovery.required", {"reason": order_report.message})
            await pipeline.close()
            return {"success": False, "message": order_report.message, "steps": steps}

        steps.append("reconcile_positions")
        pos_rec = PositionReconciliationService(self.logger)
        pos_report = await pos_rec.reconcile(
            expected_positions=state.get("expected_positions", []),
            execution_adapter=pipeline._adapter,
        )
        if not pos_report.matched:
            pipeline.halt_new_entries(pos_report.message)
            if audit_callback:
                await self._call_audit(audit_callback, "reconciliation.position_mismatch", pos_report.details)
            await pipeline.close()
            return {"success": False, "message": pos_report.message, "steps": steps}

        steps.append("verify_risk_settings")
        steps.append("restore_adapter_state")
        await pipeline.close()

        if audit_callback:
            await self._call_audit(audit_callback, "strategy.runtime.recovery_complete", {"steps": steps})

        return {"success": True, "message": "Recovery complete", "steps": steps, "restored_state": bool(state)}

    @staticmethod
    async def _call_audit(callback: Callable, event_type: str, payload: Dict[str, Any]) -> None:
        result = callback(event_type, payload)
        if hasattr(result, "__await__"):
            await result
