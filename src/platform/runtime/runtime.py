"""Strategy runtime abstraction — isolated execution unit per strategy_account."""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from src.exchanges.registry import get_exchange_definition
from src.platform.runtime.models import ExecutionMode, RuntimeContext, RuntimeStatus
from src.platform.runtime.repository import RuntimeRepository
from src.platform.runtime.risk_engine import PlatformRiskEngine
from src.platform.runtime.safety import ExecutionSafetyChecker


class StrategyRuntime(ABC):
    """One runtime instance per strategy_account — must not share mutable trading state."""

    def __init__(
        self,
        *,
        context: RuntimeContext,
        repository: RuntimeRepository,
        safety_checker: ExecutionSafetyChecker,
        event_publisher: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        heartbeat_seconds: int = 15,
        logger: Optional[logging.Logger] = None,
    ):
        self.context = context
        self.repository = repository
        self.safety_checker = safety_checker
        self.event_publisher = event_publisher
        self.heartbeat_seconds = heartbeat_seconds
        self.logger = logger or logging.getLogger("strategy_runtime")
        self.status = RuntimeStatus.STOPPED
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    @property
    def strategy_account_id(self) -> uuid.UUID:
        return self.context.strategy_account_id

    async def start(self) -> None:
        result = self.safety_checker.check_runtime_start(self.context)
        if not result.approved:
            raise RuntimeError(result.reason)

        self.status = RuntimeStatus.STARTING
        runtime = await self.repository.upsert_runtime(
            self.context.strategy_account_id,
            status=RuntimeStatus.STARTING.value,
            clear_error=True,
        )
        self.context.runtime_id = runtime.id
        await self.repository.update_strategy_account_controls(
            self.context.strategy_account_id,
            runtime_status=RuntimeStatus.STARTING.value,
            status="running",
        )
        await self._publish("strategy.runtime.started", {"strategy_account_id": str(self.context.strategy_account_id)})

        await self.on_start()
        self._stop_event.clear()
        self._task = asyncio.create_task(self._heartbeat_loop())
        self.status = RuntimeStatus.RUNNING
        await self.repository.upsert_runtime(self.context.strategy_account_id, status=RuntimeStatus.RUNNING.value)
        await self.repository.update_strategy_account_controls(
            self.context.strategy_account_id,
            runtime_status=RuntimeStatus.RUNNING.value,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.on_stop()
        self.status = RuntimeStatus.STOPPED
        await self.repository.upsert_runtime(self.context.strategy_account_id, status=RuntimeStatus.STOPPED.value)
        await self.repository.update_strategy_account_controls(
            self.context.strategy_account_id,
            runtime_status=RuntimeStatus.STOPPED.value,
            status="paused",
        )
        await self._publish("strategy.runtime.stopped", {"strategy_account_id": str(self.context.strategy_account_id)})

    async def pause(self) -> None:
        self.status = RuntimeStatus.PAUSED
        await self.repository.upsert_runtime(self.context.strategy_account_id, status=RuntimeStatus.PAUSED.value)
        await self.repository.update_strategy_account_controls(
            self.context.strategy_account_id,
            runtime_status=RuntimeStatus.PAUSED.value,
            status="paused",
        )
        await self._publish("strategy.runtime.paused", {"strategy_account_id": str(self.context.strategy_account_id)})

    async def resume(self) -> None:
        if self.status != RuntimeStatus.PAUSED:
            return
        self.status = RuntimeStatus.RUNNING
        await self.repository.upsert_runtime(self.context.strategy_account_id, status=RuntimeStatus.RUNNING.value)
        await self.repository.update_strategy_account_controls(
            self.context.strategy_account_id,
            runtime_status=RuntimeStatus.RUNNING.value,
            status="running",
        )

    async def mark_error(self, message: str) -> None:
        self.status = RuntimeStatus.ERROR
        await self.repository.upsert_runtime(
            self.context.strategy_account_id,
            status=RuntimeStatus.ERROR.value,
            last_error=message,
        )
        await self.repository.update_strategy_account_controls(
            self.context.strategy_account_id,
            runtime_status=RuntimeStatus.ERROR.value,
        )
        await self._publish("strategy.runtime.error", {"strategy_account_id": str(self.context.strategy_account_id), "message": message})

    async def submit_signal(
        self,
        *,
        signal_key: str,
        client_order_id: str,
        order_size: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        duplicate = not await self.repository.reserve_idempotency_key(
            self.context.strategy_account_id,
            client_order_id,
            signal_key=signal_key,
        )
        definition = get_exchange_definition(self.context.exchange)
        adapter_supports = bool(definition and definition.supports_execution)
        safety = self.safety_checker.check_order_submission(
            self.context,
            runtime_status=self.status.value,
            adapter_supports_execution=adapter_supports,
            duplicate_signal=duplicate,
        )
        if not safety.approved:
            await self._publish(
                "strategy.risk.rejected" if safety.code.startswith("max_") else "strategy.order.rejected",
                {"strategy_account_id": str(self.context.strategy_account_id), "reason": safety.reason, "code": safety.code},
            )
            return {"accepted": False, "reason": safety.reason, "code": safety.code}

        risk = PlatformRiskEngine.for_context(self.context).evaluate_order(order_size=order_size)
        if not risk.approved:
            await self._publish(
                "strategy.risk.rejected",
                {"strategy_account_id": str(self.context.strategy_account_id), "reason": risk.reason, "code": risk.code},
            )
            return {"accepted": False, "reason": risk.reason, "code": risk.code}

        await self._publish(
            "strategy.signal.generated",
            {"strategy_account_id": str(self.context.strategy_account_id), "signal_key": signal_key, **(metadata or {})},
        )
        result = await self.execute_signal(
            signal_key=signal_key,
            client_order_id=client_order_id,
            order_size=order_size,
            metadata=metadata or {},
        )
        return result

    @abstractmethod
    async def on_start(self) -> None:
        ...

    @abstractmethod
    async def on_stop(self) -> None:
        ...

    @abstractmethod
    async def execute_signal(
        self,
        *,
        signal_key: str,
        client_order_id: str,
        order_size: float,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        ...

    async def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self.context.runtime_id:
                    await self.repository.touch_heartbeat(self.context.runtime_id)
                    await self.repository.save_runtime_state(
                        self.context.runtime_id,
                        {
                            "status": self.status.value,
                            "execution_mode": self.context.execution_mode.value,
                            "strategy_code": self.context.strategy_code,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
            except Exception as exc:
                self.logger.warning("Heartbeat failed for %s: %s", self.context.strategy_account_id, type(exc).__name__)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.heartbeat_seconds)
            except asyncio.TimeoutError:
                continue

    async def _publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.event_publisher:
            return
        try:
            result = self.event_publisher(event_type, payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass


class PaperStrategyRuntime(StrategyRuntime):
    """Simulated runtime — records signals without placing exchange orders."""

    async def on_start(self) -> None:
        self.logger.info(
            "Paper runtime started for %s on %s",
            self.context.strategy_code,
            self.context.exchange,
        )

    async def on_stop(self) -> None:
        self.logger.info("Paper runtime stopped for %s", self.context.strategy_account_id)

    async def execute_signal(
        self,
        *,
        signal_key: str,
        client_order_id: str,
        order_size: float,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        await self.repository.update_idempotency_status(
            self.context.strategy_account_id,
            client_order_id,
            status="paper_filled",
        )
        await self._publish(
            "strategy.order.submitted",
            {
                "strategy_account_id": str(self.context.strategy_account_id),
                "client_order_id": client_order_id,
                "mode": "PAPER",
            },
        )
        await self._publish(
            "strategy.order.filled",
            {
                "strategy_account_id": str(self.context.strategy_account_id),
                "client_order_id": client_order_id,
                "mode": "PAPER",
                "size": order_size,
            },
        )
        return {
            "accepted": True,
            "mode": "PAPER",
            "client_order_id": client_order_id,
            "signal_key": signal_key,
        }


class LiveStrategyRuntime(StrategyRuntime):
    """Live execution runtime — only Delta India is wired; other exchanges reject orders."""

    async def on_start(self) -> None:
        definition = get_exchange_definition(self.context.exchange)
        if not definition or not definition.supports_execution:
            raise RuntimeError(f"Live execution not supported for {self.context.exchange}")
        if not self.safety_checker.platform_runtime_execution_enabled:
            raise RuntimeError("Platform runtime execution is disabled")
        self.logger.info(
            "Live runtime starting for %s on %s (testnet=%s)",
            self.context.strategy_code,
            self.context.exchange,
            self.context.is_testnet,
        )

    async def on_stop(self) -> None:
        self.logger.info("Live runtime stopped for %s", self.context.strategy_account_id)

    async def execute_signal(
        self,
        *,
        signal_key: str,
        client_order_id: str,
        order_size: float,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Live bridge is intentionally conservative: architecture validates safety,
        # but actual exchange placement remains behind explicit future integration.
        await self.repository.update_idempotency_status(
            self.context.strategy_account_id,
            client_order_id,
            status="rejected",
        )
        await self._publish(
            "strategy.order.rejected",
            {
                "strategy_account_id": str(self.context.strategy_account_id),
                "client_order_id": client_order_id,
                "reason": "Live execution bridge pending verification",
            },
        )
        return {
            "accepted": False,
            "mode": "LIVE",
            "reason": "Live execution bridge pending verification",
            "client_order_id": client_order_id,
        }
