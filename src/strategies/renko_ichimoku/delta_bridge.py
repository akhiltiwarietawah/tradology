"""Delta candle + perpetual product helpers used only by Renko Ichimoku."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from src.strategies.renko_ichimoku.runtime import RESOLUTION_SECONDS, ClosedCandle


class CandleFetchCache:
    """Reuse one candle response for every book of the same symbol in this tick."""

    def __init__(self, ttl_seconds: float = 2.0):
        self.ttl_seconds = ttl_seconds
        self._items: Dict[tuple, tuple[float, List[ClosedCandle]]] = {}

    def get(self, key: tuple) -> Optional[List[ClosedCandle]]:
        item = self._items.get(key)
        if item is None:
            return None
        stored_at, candles = item
        if time.monotonic() - stored_at > self.ttl_seconds:
            return None
        return list(candles)

    def store(self, key: tuple, candles: List[ClosedCandle]) -> None:
        self._items[key] = (time.monotonic(), list(candles))


class DeltaCandleProductBridge:
    def __init__(self, adapter, logger, cache: Optional[CandleFetchCache] = None):
        self.adapter = adapter
        self.logger = logger
        self.cache = cache

    async def fetch_closed_candles(self, symbol: str, resolution: str, limit: int) -> List[ClosedCandle]:
        key = (symbol, resolution, int(limit))
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        raw = await self.adapter.get_candles(symbol=symbol, resolution=resolution, limit=limit)
        step = RESOLUTION_SECONDS.get(resolution, 900)
        now = time.time()
        out: List[ClosedCandle] = []
        for row in raw:
            t = float(row.get("time") or row.get("timestamp") or 0)
            close = float(row.get("close") or 0)
            if t <= 0 or close <= 0:
                continue
            if t + step > now:
                # Forming / unconfirmed source candle — never used for Renko.
                continue
            out.append(ClosedCandle(time=t, close=close))
        out.sort(key=lambda c: c.time)
        if self.cache is not None:
            self.cache.store(key, out)
        return out

    async def resolve_perpetual(self, symbol: str) -> Optional[Dict[str, Any]]:
        return await self.adapter.get_perpetual_product(symbol)
