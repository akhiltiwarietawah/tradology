"""Scheduler triggering IST time-based trading events."""

import asyncio
import logging
from typing import Optional, Callable, Awaitable, List
from datetime import datetime
import pytz

from src.config.constants import IST_TIMEZONE
from src.core.events.event_bus import EventBus, EventType


class StrategyScheduler:
    """Manages periodic timer ticks and scheduling of IST trading windows."""

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        tick_interval_seconds: float = 1.0,
        logger: Optional[logging.Logger] = None,
    ):
        self.event_bus = event_bus
        self.tick_interval_seconds = tick_interval_seconds
        self.logger = logger or logging.getLogger("strategy_scheduler")
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._timer_callbacks: List[Callable[[datetime], Awaitable[None]]] = []

    def add_timer_callback(self, cb: Callable[[datetime], Awaitable[None]]):
        self._timer_callbacks.append(cb)

    async def start(self):
        """Start the background scheduler loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        self.logger.info("StrategyScheduler started.")

    async def stop(self):
        """Stop the background scheduler loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("StrategyScheduler stopped.")

    async def _run_loop(self):
        while self._running:
            try:
                now_ist = datetime.now(IST_TIMEZONE)

                # Publish to EventBus
                if self.event_bus:
                    await self.event_bus.publish(EventType.TIMER_TICK, now_ist)

                # Call direct callbacks
                for cb in self._timer_callbacks:
                    try:
                        await cb(now_ist)
                    except Exception as e:
                        self.logger.error(f"Error in timer callback: {e}", exc_info=True)

                await asyncio.sleep(self.tick_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in scheduler loop: {e}", exc_info=True)
                await asyncio.sleep(1.0)
