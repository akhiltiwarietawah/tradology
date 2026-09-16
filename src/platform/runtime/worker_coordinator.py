"""Distributed worker coordination for strategy runtimes."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select, text

from src.persistence.platform_models import StrategyRuntimeModel
from src.platform.runtime.repository import RuntimeRepository


class RuntimeWorkerCoordinator:
    """Detects stale workers and enforces one active worker per strategy_account."""

    def __init__(
        self,
        repository: RuntimeRepository,
        *,
        worker_id: str,
        heartbeat_stale_seconds: int = 60,
        logger: Optional[logging.Logger] = None,
    ):
        self.repository = repository
        self.worker_id = worker_id
        self.heartbeat_stale_seconds = heartbeat_stale_seconds
        self.logger = logger or logging.getLogger("runtime_worker_coordinator")

    async def list_stale_runtimes(self) -> List[StrategyRuntimeModel]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.heartbeat_stale_seconds)
        async with self.repository.db.get_session() as session:
            stmt = select(StrategyRuntimeModel).where(
                StrategyRuntimeModel.status.in_(["RUNNING", "STARTING", "PAUSED"]),
                StrategyRuntimeModel.last_heartbeat_at.is_not(None),
                StrategyRuntimeModel.last_heartbeat_at < cutoff,
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def mark_stale_as_recovery_required(self) -> int:
        stale = await self.list_stale_runtimes()
        for runtime in stale:
            await self.repository.upsert_runtime(
                runtime.strategy_account_id,
                status="RECOVERY_REQUIRED",
                last_error=f"Worker {runtime.worker_id} heartbeat stale",
            )
            await self.repository.update_strategy_account_controls(
                runtime.strategy_account_id,
                runtime_status="RECOVERY_REQUIRED",
            )
            self.logger.warning(
                "Marked runtime %s RECOVERY_REQUIRED — stale worker %s",
                runtime.strategy_account_id,
                runtime.worker_id,
            )
        return len(stale)

    async def release_advisory_lock(self, strategy_account_id) -> None:
        key = abs(hash(str(strategy_account_id))) % (2**31 - 1)
        async with self.repository.db.get_session() as session:
            await session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            await session.commit()

    async def graceful_shutdown(self, strategy_account_ids: List) -> None:
        for sa_id in strategy_account_ids:
            await self.release_advisory_lock(sa_id)
        self.logger.info("Released advisory locks for %d runtimes on worker %s", len(strategy_account_ids), self.worker_id)
