"""Realized and unrealized P&L calculations for attributed platform trades."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional


def _d(val: Any, default: str = "0") -> Decimal:
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


def compute_realized_from_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate realized metrics from attributed trade rows."""
    if not trades:
        return {
            "available": False,
            "realized_pnl": 0.0,
            "net_pnl": 0.0,
            "total_fees": 0.0,
            "trade_count": 0,
            "win_count": 0,
            "loss_count": 0,
        }

    realized = Decimal("0")
    net = Decimal("0")
    fees = Decimal("0")
    wins = 0
    losses = 0
    for t in trades:
        realized += _d(t.get("realized_pnl"))
        net += _d(t.get("net_pnl"))
        fees += _d(t.get("total_fees"))
        n = _d(t.get("net_pnl"))
        if n > 0:
            wins += 1
        elif n < 0:
            losses += 1

    completed = [t for t in trades if (t.get("status") or "").upper() == "COMPLETED"]
    return {
        "available": True,
        "realized_pnl": float(realized),
        "net_pnl": float(net),
        "total_fees": float(fees),
        "trade_count": len(trades),
        "completed_trade_count": len(completed),
        "win_count": wins,
        "loss_count": losses,
        "win_rate": (wins / len(completed)) if completed else None,
    }


def compute_leg_realized_pnl(
    *,
    side: str,
    entry_qty: Decimal,
    exit_qty: Decimal,
    entry_price: Decimal,
    exit_price: Decimal,
    contract_value: Decimal = Decimal("1"),
    fees: Decimal = Decimal("0"),
) -> Decimal:
    """Per-leg realized P&L supporting partial fills."""
    qty = min(entry_qty, exit_qty)
    if qty <= 0:
        return Decimal("0") - fees
    side_norm = side.lower()
    if side_norm in {"sell", "short"}:
        gross = (entry_price - exit_price) * qty * contract_value
    else:
        gross = (exit_price - entry_price) * qty * contract_value
    return gross - fees


def compute_strategy_unrealized(
    open_legs: List[Dict[str, Any]],
    mark_prices: Dict[str, Decimal],
    symbol_owners: Dict[str, str],
    strategy_account_id: str,
) -> Dict[str, Any]:
    """
    Compute strategy unrealized P&L only for symbols uniquely attributable to this strategy_account.
    """
    total = Decimal("0")
    attributed = 0
    ambiguous = 0
    for leg in open_legs:
        symbol = leg.get("symbol")
        if not symbol:
            continue
        owner = symbol_owners.get(symbol)
        if owner != strategy_account_id:
            if owner:
                ambiguous += 1
            continue
        mark = mark_prices.get(symbol)
        entry = leg.get("entry_price")
        qty = _d(leg.get("quantity"))
        side = (leg.get("side") or "sell").lower()
        if mark is None or entry is None:
            continue
        entry_d = _d(entry)
        if side in {"sell", "short"}:
            total += (entry_d - mark) * qty
        else:
            total += (mark - entry_d) * qty
        attributed += 1

    if attributed == 0 and ambiguous > 0:
        return {"available": False, "reason": "ambiguous_position_attribution", "unrealized_pnl": None}
    if attributed == 0:
        return {"available": False, "reason": "no_attributable_open_legs", "unrealized_pnl": None}
    return {"available": True, "unrealized_pnl": float(total), "attributed_legs": attributed}


def merge_equity_curves(curves: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Sum account equity curves by timestamp (used once per account)."""
    buckets: Dict[str, float] = defaultdict(float)
    for curve in curves:
        for point in curve:
            ts = point.get("timestamp")
            if ts:
                buckets[ts] += float(point.get("equity") or 0)
    return [{"timestamp": ts, "equity": eq} for ts, eq in sorted(buckets.items())]


def curve_metrics(points: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(points) < 2:
        return {"available": False}
    start = float(points[0].get("equity") or 0)
    end = float(points[-1].get("equity") or 0)
    peak = start
    max_dd = 0.0
    for p in points:
        eq = float(p.get("equity") or 0)
        if eq > peak:
            peak = eq
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)
    ret = ((end - start) / start) if start else None
    return {
        "available": True,
        "start_equity": start,
        "end_equity": end,
        "return_pct": ret,
        "max_drawdown_pct": max_dd,
        "pnl": end - start,
    }
