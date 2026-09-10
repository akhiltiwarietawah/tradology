"""Delta candle + perpetual product helpers used only by Renko Ichimoku."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from src.strategies.renko_ichimoku.runtime import RESOLUTION_SECONDS, ClosedCandle


class DeltaCandleProductBridge:
    def __init__(self, adapter, logger):
        self.adapter = adapter
        self.logger = logger

    async def fetch_closed_candles(self, symbol: str, resolution: str, limit: int) -> List[ClosedCandle]:
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
        return out

    async def resolve_perpetual(self, symbol: str) -> Optional[Dict[str, Any]]:
        return await self.adapter.get_perpetual_product(symbol)
