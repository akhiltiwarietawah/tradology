"""Strategy runtime manager — orchestrates isolated runtimes per strategy_account."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, Optional

from src.config.settings import Settings
from src.persistence.db import DatabaseManager
from src.platform.repositories.platform_repository import PlatformRepository
from src.platform.runtime.integrated_runtime import IntegratedStrategyRuntime
from src.platform.runtime.models import ExecutionMode, RuntimeContext, RuntimeSnapshot, RuntimeStatus
from src.platform.runtime.ownership_guard import ExecutionOwnershipGuard
from src.platform.runtime.recovery import RuntimeRecoveryService
from src.platform.runtime.validation_service import RuntimeValidationService
from src.platform.execution.validation_stats import ValidationStatsRepository
from src.platform.runtime.repository import RuntimeRepository
from src.platform.runtime.runtime import LiveStrategyRuntime, PaperStrategyRuntime, StrategyRuntime
from src.platform.runtime.safety import ExecutionSafetyChecker
from src.platform.security.credentials import CredentialVault
from src.platform.sync.event_hub import PlatformEventHub


class StrategyRuntimeManager:
    """Manages in-memory runtime instances with DB-backed coordination."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        settings: Settings,
        event_hub: Optional[PlatformEventHub] = None,
        vault: Optional[CredentialVault] = None,
        logger: Optional[logging.Logger] = None,
        legacy_engine: Optional[Any] = None,
    ):
        self.db = db_manager
        self.settings = settings
        self.event_hub = event_hub
        self.vault = vault or CredentialVault()
        self.logger = logger or logging.getLogger("strategy_runtime_manager")
        self.legacy_engine = legacy_engine
        self.ownership_guard = ExecutionOwnershipGuard(self.logger)
        self.repository = RuntimeRepository(db_manager)
        self.platform_repo = PlatformRepository(db_manager, self.vault)
        self.validation_stats = ValidationStatsRepository(db_manager)
        self.validation_service = RuntimeValidationService(self.repository, settings, self.validation_stats)
        self.safety_checker = ExecutionSafetyChecker(
            platform_runtime_execution_enabled=settings.platform_runtime_execution_enabled,
            platform_live_trading_enabled=settings.platform_live_trading_enabled,
            platform_delta_live_enabled=settings.platform_delta_live_enabled,
        )
        self.recovery = RuntimeRecoveryService(self.repository, self.logger)
        self._runtimes: Dict[str, StrategyRuntime] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _lock_for(self, strategy_account_id: uuid.UUID) -> asyncio.Lock:
        key = str(strategy_account_id)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def _publish(self, user_id: uuid.UUID, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.event_hub:
            return
        await self.event_hub.publish(str(user_id), event_type, payload)

    async def build_context(self, user_id: uuid.UUID, strategy_account_id: uuid.UUID) -> RuntimeContext:
        row = await self.repository.get_strategy_account_for_user(user_id, strategy_account_id)
        if not row:
            raise PermissionError("Strategy account not found")
        subscription = row.subscription
        exchange_account = row.exchange_account
        strategy = subscription.strategy
        runtime_row = await self.repository.get_runtime_by_strategy_account(strategy_account_id)
        mode_raw = (row.execution_mode or "PAPER").upper()
        try:
            execution_mode = ExecutionMode(mode_raw)
        except ValueError:
            execution_mode = ExecutionMode.PAPER
        return RuntimeContext(
            user_id=user_id,
            subscription_id=subscription.id,
            strategy_account_id=strategy_account_id,
            strategy_code=strategy.code,
            strategy_name=strategy.name,
            exchange=exchange_account.exchange,
            exchange_account_id=exchange_account.id,
            exchange_account_label=exchange_account.label,
            execution_mode=execution_mode,
            trading_enabled=bool(row.trading_enabled),
            subscription_status=subscription.status,
            exchange_health_status=exchange_account.health_status or "DISCONNECTED",
            exchange_connection_status=exchange_account.connection_status or "disconnected",
            is_testnet=exchange_account.is_testnet,
            exchange_trading_enabled=bool(getattr(exchange_account, "trading_enabled", True)),
            risk_settings=subscription.risk_settings or {},
            risk_overrides=row.risk_overrides or {},
            runtime_id=runtime_row.id if runtime_row else None,
        )

    def _uses_integrated_runtime(self, ctx: RuntimeContext) -> bool:
        return ctx.strategy_code == "short_strangle" and ctx.exchange == "delta_india"

    def _audit_callback(self, ctx: RuntimeContext):
        async def _record(event_type: str, payload: Dict[str, Any]) -> None:
            await self.platform_repo.record_audit(
                user_id=ctx.user_id,
                event_type=event_type,
                resource_type="strategy_account",
                resource_id=str(ctx.strategy_account_id),
                payload=payload,
            )

        return _record

    def _create_runtime(self, ctx: RuntimeContext) -> StrategyRuntime:
        publisher = lambda event_type, payload: self._publish(ctx.user_id, event_type, payload)
        common = dict(
            context=ctx,
            repository=self.repository,
            safety_checker=self.safety_checker,
            event_publisher=publisher,
            heartbeat_seconds=self.settings.platform_runtime_heartbeat_seconds,
            logger=self.logger,
        )
        if self._uses_integrated_runtime(ctx):
            return IntegratedStrategyRuntime(
                **common,
                vault=self.vault,
                settings=self.settings,
                audit_callback=self._audit_callback(ctx),
            )
        if ctx.execution_mode == ExecutionMode.LIVE:
            return LiveStrategyRuntime(**common)
        return PaperStrategyRuntime(**common)

    async def start_runtime(self, user_id: uuid.UUID, strategy_account_id: uuid.UUID) -> RuntimeSnapshot:
        lock = self._lock_for(strategy_account_id)
        async with lock:
            key = str(strategy_account_id)
            if key in self._runtimes and self._runtimes[key].status in {RuntimeStatus.RUNNING, RuntimeStatus.STARTING}:
                raise RuntimeError("Runtime already active for this strategy account")

            acquired = await self.repository.try_acquire_runtime_lock(
                strategy_account_id,
                self.settings.platform_runtime_worker_id,
            )
            if not acquired:
                raise RuntimeError("Another worker is already running this strategy account")

            ctx = await self.build_context(user_id, strategy_account_id)
            if ctx.runtime_id:
                runtime_row = await self.repository.get_runtime_by_strategy_account(strategy_account_id)
                if runtime_row and runtime_row.status == RuntimeStatus.RECOVERY_REQUIRED.value:
                    raise RuntimeError("Runtime requires recovery before start — use recover endpoint")

            safety = self.safety_checker.check_runtime_start(ctx)
            if not safety.approved:
                raise RuntimeError(safety.reason)

            if ctx.execution_mode in {ExecutionMode.LIVE, ExecutionMode.LIVE_DRY_RUN}:
                guard = self.ownership_guard.check_platform_live_start(
                    ctx,
                    self.settings,
                    legacy_engine_running=bool(getattr(self.legacy_engine, "_running", False)),
                )
                if not guard.get("allowed"):
                    raise RuntimeError(guard.get("reason", "Execution ownership conflict"))

            runtime = self._create_runtime(ctx)
            await runtime.start()
            self._runtimes[key] = runtime
            await self.platform_repo.record_audit(
                user_id=user_id,
                event_type="strategy.runtime.started",
                resource_type="strategy_account",
                resource_id=str(strategy_account_id),
                payload={"execution_mode": ctx.execution_mode.value},
            )
            return self.snapshot_from_context(ctx, runtime.status.value)

    async def stop_runtime(self, user_id: uuid.UUID, strategy_account_id: uuid.UUID) -> RuntimeSnapshot:
        lock = self._lock_for(strategy_account_id)
        async with lock:
            key = str(strategy_account_id)
            runtime = self._runtimes.pop(key, None)
            if runtime:
                await runtime.stop()
            else:
                await self.repository.upsert_runtime(strategy_account_id, status=RuntimeStatus.STOPPED.value)
                await self.repository.update_strategy_account_controls(
                    strategy_account_id,
                    runtime_status=RuntimeStatus.STOPPED.value,
                    status="paused",
                )
            ctx = await self.build_context(user_id, strategy_account_id)
            await self.platform_repo.record_audit(
                user_id=user_id,
                event_type="strategy.runtime.stopped",
                resource_type="strategy_account",
                resource_id=str(strategy_account_id),
            )
            return self.snapshot_from_context(ctx, RuntimeStatus.STOPPED.value)

    async def pause_runtime(self, user_id: uuid.UUID, strategy_account_id: uuid.UUID) -> RuntimeSnapshot:
        ctx = await self.build_context(user_id, strategy_account_id)
        runtime = self._runtimes.get(str(strategy_account_id))
        if runtime:
            await runtime.pause()
        else:
            await self.repository.upsert_runtime(strategy_account_id, status=RuntimeStatus.PAUSED.value)
            await self.repository.update_strategy_account_controls(
                strategy_account_id,
                runtime_status=RuntimeStatus.PAUSED.value,
                status="paused",
            )
        return self.snapshot_from_context(ctx, RuntimeStatus.PAUSED.value)

    async def resume_runtime(self, user_id: uuid.UUID, strategy_account_id: uuid.UUID) -> RuntimeSnapshot:
        ctx = await self.build_context(user_id, strategy_account_id)
        runtime_row = await self.repository.get_runtime_by_strategy_account(strategy_account_id)
        if runtime_row and runtime_row.status == RuntimeStatus.RECOVERY_REQUIRED.value:
            raise RuntimeError("Runtime requires recovery before resume")
        runtime = self._runtimes.get(str(strategy_account_id))
        if runtime:
            await runtime.resume()
        else:
            return await self.start_runtime(user_id, strategy_account_id)
        return self.snapshot_from_context(ctx, RuntimeStatus.RUNNING.value)

    async def recover_runtime(self, user_id: uuid.UUID, strategy_account_id: uuid.UUID) -> Dict[str, Any]:
        """Run startup recovery steps before allowing LIVE resume."""
        lock = self._lock_for(strategy_account_id)
        async with lock:
            ctx = await self.build_context(user_id, strategy_account_id)
            report = await self.recovery.perform_recovery(
                ctx,
                repository=self.repository,
                safety_checker=self.safety_checker,
                vault=self.vault,
                settings=self.settings,
                audit_callback=self._audit_callback(ctx),
            )
            if report.get("success"):
                await self.repository.upsert_runtime(strategy_account_id, status=RuntimeStatus.STOPPED.value, clear_error=True)
                await self.repository.update_strategy_account_controls(
                    strategy_account_id,
                    runtime_status=RuntimeStatus.STOPPED.value,
                )
                await self.platform_repo.record_audit(
                    user_id=user_id,
                    event_type="strategy.runtime.recovered",
                    resource_type="strategy_account",
                    resource_id=str(strategy_account_id),
                    payload={"steps": report.get("steps", [])},
                )
            else:
                await self.repository.upsert_runtime(
                    strategy_account_id,
                    status=RuntimeStatus.RECOVERY_REQUIRED.value,
                    last_error=report.get("message", "Recovery failed"),
                )
                await self.repository.update_strategy_account_controls(
                    strategy_account_id,
                    runtime_status=RuntimeStatus.RECOVERY_REQUIRED.value,
                )
            return report

    async def enable_trading(
        self,
        user_id: uuid.UUID,
        strategy_account_id: uuid.UUID,
        *,
        confirm_live: bool = False,
    ) -> Dict[str, Any]:
        ctx = await self.build_context(user_id, strategy_account_id)
        if ctx.execution_mode in {ExecutionMode.LIVE, ExecutionMode.LIVE_DRY_RUN}:
            if not confirm_live:
                return {
                    "success": False,
                    "requires_confirmation": True,
                    "message": "Live trading requires explicit confirmation",
                    "exchange": ctx.exchange,
                    "strategy": ctx.strategy_code,
                    "account": ctx.exchange_account_label,
                    "mode": ctx.execution_mode.value,
                }
            if ctx.execution_mode == ExecutionMode.LIVE:
                check = self.safety_checker.check_live_enable(ctx)
                if not check.approved:
                    raise RuntimeError(check.reason)
        await self.repository.update_strategy_account_controls(
            strategy_account_id,
            trading_enabled=True,
        )
        await self.platform_repo.record_audit(
            user_id=user_id,
            event_type="strategy.trading.enabled",
            resource_type="strategy_account",
            resource_id=str(strategy_account_id),
            payload={"execution_mode": ctx.execution_mode.value},
        )
        return {"success": True, "trading_enabled": True}

    async def disable_trading(self, user_id: uuid.UUID, strategy_account_id: uuid.UUID) -> Dict[str, Any]:
        await self.repository.update_strategy_account_controls(strategy_account_id, trading_enabled=False)
        await self.platform_repo.record_audit(
            user_id=user_id,
            event_type="strategy.trading.disabled",
            resource_type="strategy_account",
            resource_id=str(strategy_account_id),
        )
        return {"success": True, "trading_enabled": False}

    async def set_execution_mode(
        self,
        user_id: uuid.UUID,
        strategy_account_id: uuid.UUID,
        mode: str,
        *,
        confirm_live: bool = False,
    ) -> Dict[str, Any]:
        normalized = mode.upper()
        if normalized not in {"PAPER", "LIVE", "LIVE_DRY_RUN"}:
            raise ValueError("Invalid execution mode")
        if normalized in {"LIVE", "LIVE_DRY_RUN"}:
            if not confirm_live:
                ctx = await self.build_context(user_id, strategy_account_id)
                return {
                    "success": False,
                    "requires_confirmation": True,
                    "message": f"Switching to {normalized} requires explicit confirmation",
                    "exchange": ctx.exchange,
                    "strategy": ctx.strategy_code,
                    "account": ctx.exchange_account_label,
                    "mode": normalized,
                    "warning": "This strategy can place real orders using this account.",
                }
            ctx = await self.build_context(user_id, strategy_account_id)
            ctx.execution_mode = ExecutionMode(normalized)
            if normalized == "LIVE":
                check = self.safety_checker.check_live_enable(ctx)
                if not check.approved:
                    raise RuntimeError(check.reason)
        await self.repository.update_strategy_account_controls(
            strategy_account_id,
            execution_mode=normalized,
            trading_enabled=False,
        )
        await self.platform_repo.record_audit(
            user_id=user_id,
            event_type="strategy.execution_mode.changed",
            resource_type="strategy_account",
            resource_id=str(strategy_account_id),
            payload={"execution_mode": normalized},
        )
        return {"success": True, "execution_mode": normalized, "trading_enabled": False}

    async def list_runtimes(self, user_id: uuid.UUID) -> list[RuntimeSnapshot]:
        rows = await self.repository.list_strategy_accounts_for_user_detailed(user_id)
        snapshots = []
        for row in rows:
            runtime = row.runtime
            snapshots.append(
                RuntimeSnapshot(
                    strategy_account_id=str(row.id),
                    runtime_id=str(runtime.id) if runtime else None,
                    status=row.runtime_status or (runtime.status if runtime else "STOPPED"),
                    execution_mode=row.execution_mode or "PAPER",
                    trading_enabled=bool(row.trading_enabled),
                    strategy_code=row.subscription.strategy.code if row.subscription and row.subscription.strategy else "",
                    exchange=row.exchange_account.exchange if row.exchange_account else "",
                    exchange_account_id=str(row.exchange_account_id),
                    exchange_account_label=row.exchange_account.label if row.exchange_account else "",
                    last_heartbeat_at=runtime.last_heartbeat_at.isoformat() if runtime and runtime.last_heartbeat_at else None,
                    last_error=runtime.last_error if runtime else None,
                    started_at=runtime.started_at.isoformat() if runtime and runtime.started_at else None,
                    stopped_at=runtime.stopped_at.isoformat() if runtime and runtime.stopped_at else None,
                )
            )
        return snapshots

    async def get_validation_report(self, user_id: uuid.UUID, strategy_account_id: uuid.UUID) -> Dict[str, Any]:
        ctx = await self.build_context(user_id, strategy_account_id)
        runtime = self._runtimes.get(str(strategy_account_id))
        entries_halted = False
        runtime_status = None
        if runtime and hasattr(runtime, "_pipeline") and runtime._pipeline:
            entries_halted = runtime._pipeline.entries_halted
            runtime_status = runtime.status.value
        return await self.validation_service.get_report(
            ctx,
            runtime_status=runtime_status,
            entries_halted=entries_halted,
        )

    async def get_execution_history(
        self,
        user_id: uuid.UUID,
        strategy_account_id: uuid.UUID,
        *,
        limit: int = 100,
        status: Optional[str] = None,
    ) -> list:
        row = await self.repository.get_strategy_account_for_user(user_id, strategy_account_id)
        if not row:
            raise PermissionError("Strategy account not found")
        from src.platform.execution.lifecycle_repository import OrderLifecycleRepository

        repo = OrderLifecycleRepository(self.db)
        return await repo.list_execution_history(strategy_account_id, limit=limit, status=status)

    async def recover_on_startup(self) -> int:
        return await self.recovery.recover_on_startup(
            platform_runtime_execution_enabled=self.settings.platform_runtime_execution_enabled
        )

    async def shutdown_all(self) -> None:
        for key, runtime in list(self._runtimes.items()):
            try:
                await runtime.stop()
            except Exception:
                pass
            self._runtimes.pop(key, None)

    @staticmethod
    def snapshot_from_context(ctx: RuntimeContext, status: str) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            strategy_account_id=str(ctx.strategy_account_id),
            runtime_id=str(ctx.runtime_id) if ctx.runtime_id else None,
            status=status,
            execution_mode=ctx.execution_mode.value,
            trading_enabled=ctx.trading_enabled,
            strategy_code=ctx.strategy_code,
            exchange=ctx.exchange,
            exchange_account_id=str(ctx.exchange_account_id),
            exchange_account_label=ctx.exchange_account_label,
        )

    def runtime_to_dict(self, snapshot: RuntimeSnapshot, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "strategy_account_id": snapshot.strategy_account_id,
            "runtime_id": snapshot.runtime_id,
            "status": snapshot.status,
            "execution_mode": snapshot.execution_mode,
            "trading_enabled": snapshot.trading_enabled,
            "strategy_code": snapshot.strategy_code,
            "exchange": snapshot.exchange,
            "exchange_account_id": snapshot.exchange_account_id,
            "exchange_account_label": snapshot.exchange_account_label,
            "last_heartbeat_at": snapshot.last_heartbeat_at,
            "last_error": snapshot.last_error,
            "started_at": snapshot.started_at,
            "stopped_at": snapshot.stopped_at,
        }
        if extra:
            payload.update(extra)
        return payload
