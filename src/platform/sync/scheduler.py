"""Background scheduler for periodic account synchronization."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from src.platform.sync.account_sync_service import AccountSyncService


class AccountSyncScheduler:
    def __init__(
        self,
        sync_service: AccountSyncService,
        interval_seconds: float = 60.0,
        logger: Optional[logging.Logger] = None,
    ):
        self.sync_service = sync_service
        self.interval_seconds = interval_seconds
        self.logger = logger or logging.getLogger("account_sync_scheduler")
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._cycle_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        self.logger.info("Account sync scheduler started (interval=%ss)", self.interval_seconds)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Account sync scheduler stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                if self._cycle_lock.locked():
                    await asyncio.sleep(self.interval_seconds)
                    continue
                async with self._cycle_lock:
                    count = await self.sync_service.sync_all_accounts()
                    if count:
                        self.logger.info("Background sync completed for %s account(s)", count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.warning("Background sync cycle failed: %s", type(exc).__name__)
            await asyncio.sleep(self.interval_seconds)
