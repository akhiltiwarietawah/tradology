"""Delta fill commission helpers for PnL accounting."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence


def commission_from_fill(fill: Dict[str, Any]) -> float:
    commission = fill.get("commission") or fill.get("fees") or 0.0
    try:
        return abs(float(commission))
    except (TypeError, ValueError):
        return 0.0


async def commissions_by_order_id(
    exchange_ops: Any,
    *,
    instrument_id: str,
    order_ids: Sequence[str],
    entry_time: Optional[float] = None,
    page_size: int = 50,
    retries: int = 4,
    retry_delay_sec: float = 0.5,
) -> Dict[str, float]:
    """
    Sum Delta ``commission`` across recent fills matching the given order IDs.

    Retries briefly so the exit fill is visible right after a market order.
    """
    want = {str(o) for o in order_ids if o}
    if not want:
        return {}
    getter = getattr(exchange_ops, "get_recent_fills_for_product", None)
    if not getter:
        return {}

    start_time_us: Optional[int] = None
    if entry_time:
        start_time_us = int((float(entry_time) - 300.0) * 1_000_000)

    last_by_order: Dict[str, float] = {}
    for attempt in range(max(1, retries)):
        fills: List[Dict[str, Any]] = await getter(
            instrument_id=str(instrument_id),
            side=None,
            page_size=page_size,
            start_time_us=start_time_us,
        )
        by_order: Dict[str, float] = {}
        for fill in fills:
            oid = str(fill.get("order_id") or "")
            if oid not in want:
                continue
            by_order[oid] = by_order.get(oid, 0.0) + commission_from_fill(fill)
        last_by_order = {k: round(v, 4) for k, v in by_order.items()}
        if set(by_order.keys()) >= want:
            return last_by_order
        if attempt + 1 < retries:
            await asyncio.sleep(retry_delay_sec)
    return last_by_order


async def sum_commission_for_order_ids(
    exchange_ops: Any,
    *,
    instrument_id: str,
    order_ids: Sequence[str],
    entry_time: Optional[float] = None,
    page_size: int = 50,
    retries: int = 4,
    retry_delay_sec: float = 0.5,
) -> float:
    by_order = await commissions_by_order_id(
        exchange_ops,
        instrument_id=instrument_id,
        order_ids=order_ids,
        entry_time=entry_time,
        page_size=page_size,
        retries=retries,
        retry_delay_sec=retry_delay_sec,
    )
    return round(sum(by_order.values()), 4)
