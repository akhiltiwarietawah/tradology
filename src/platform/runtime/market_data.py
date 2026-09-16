"""Normalized market data feed for strategy runtimes."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from src.platform.execution.models import NormalizedMarketEvent


class NormalizedMarketDataFeed:
    """Exchange-agnostic market data with stale detection and deduplication."""

    def __init__(
        self,
        *,
        stale_after_seconds: float = 30.0,
        max_seen_events: int = 500,
        logger: Optional[logging.Logger] = None,
    ):
        self.stale_after_seconds = stale_after_seconds
        self.max_seen_events = max_seen_events
        self.logger = logger or logging.getLogger("market_data_feed")
        self._last_event_at: Optional[datetime] = None
        self._connected = False
        self._seen: OrderedDict[str, datetime] = OrderedDict()

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_stale(self) -> bool:
        if self._last_event_at is None:
            return True
        return datetime.now(timezone.utc) - self._last_event_at > timedelta(seconds=self.stale_after_seconds)

    def mark_connected(self) -> None:
        self._connected = True

    def mark_disconnected(self) -> None:
        self._connected = False

    def normalize_ticker(self, *, symbol: str, mark_price: float, best_bid=None, best_ask=None, source: str) -> NormalizedMarketEvent:
        now = datetime.now(timezone.utc)
        event = NormalizedMarketEvent(
            symbol=symbol,
            mark_price=mark_price,
            best_bid=best_bid,
            best_ask=best_ask,
            timestamp=now,
            source=source,
            stale=False,
        )
        return self.ingest(event)

    def ingest(self, event: NormalizedMarketEvent) -> Optional[NormalizedMarketEvent]:
        key = f"{event.symbol}:{event.mark_price}:{event.timestamp.isoformat()}"
        if key in self._seen:
            return None
        self._seen[key] = event.timestamp
        while len(self._seen) > self.max_seen_events:
            self._seen.popitem(last=False)

        self._last_event_at = event.timestamp
        event.stale = self.is_stale
        return event

    async def dispatch(
        self,
        event: NormalizedMarketEvent,
        handler: Callable[[NormalizedMarketEvent], Awaitable[None]],
    ) -> None:
        if event.stale or self.is_stale:
            self.logger.warning("Stale market data for %s — skipping dispatch", event.symbol)
            return
        await handler(event)
