"""Asynchronous Typed Event Bus for Engine Decoupling."""

import asyncio
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Awaitable, Any, Optional
from datetime import datetime


class EventType(str, Enum):
    MARKET_TICK = "market_tick"
    ORDER_UPDATE = "order_update"
    POSITION_UPDATE = "position_update"
    TIMER_TICK = "timer_tick"
    STRATEGY_SIGNAL = "strategy_signal"
    RECONCILIATION_EVENT = "reconciliation_event"
    EMERGENCY_HALT = "emergency_halt"


@dataclass
class Event:
    """Base event payload."""
    event_type: EventType
    data: Any
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class EventBus:
    """Async pub/sub event bus with concurrency controls."""

    def __init__(self, max_concurrent_handlers: int = 500, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("event_bus")
        self._handlers: Dict[EventType, List[Callable[[Event], Awaitable[None]]]] = {
            et: [] for et in EventType
        }
        self._semaphore = asyncio.Semaphore(max_concurrent_handlers)

    def subscribe(self, event_type: EventType, handler: Callable[[Event], Awaitable[None]]):
        """Register an async callback for a given EventType."""
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable[[Event], Awaitable[None]]):
        """Unregister an async callback."""
        if handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    async def publish(self, event_type: EventType, data: Any):
        """Publish an event to all registered subscribers concurrently."""
        event = Event(event_type=event_type, data=data)
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            return

        async def _run_handler(h):
            async with self._semaphore:
                try:
                    await h(event)
                except Exception as e:
                    self.logger.error(f"Error in event handler for {event_type}: {e}", exc_info=True)

        await asyncio.gather(*[_run_handler(h) for h in handlers], return_exceptions=True)
