"""Renko position sizing: fixed contracts or dynamic % equity with virtual profit retention."""

from __future__ import annotations

import math
from typing import Literal

PositionSizingMode = Literal["fixed", "dynamic"]


def compute_realized_pnl_usd(
    entry_price: float,
    exit_price: float,
    quantity: float,
    contract_value: float,
    position_side: int,
) -> float:
    """Perp realized PnL in USD from exact entry/exit fills (matches renko_trade_repository)."""
    if quantity <= 0 or contract_value <= 0:
        return 0.0
    diff = float(exit_price) - float(entry_price)
    if int(position_side) < 0:
        diff = -diff
    return diff * float(quantity) * float(contract_value)


def apply_exit_to_sizing_equity(
    sizing_equity: float,
    realized_pnl: float,
    profit_retain_pct: float,
) -> float:
    """
    Update virtual sizing equity after a closed trade.

    Winning trades: only ``profit_retain_pct`` of profit is kept for sizing
    (simulates withdrawing the rest without moving funds off-exchange).
    Losing trades: full loss is applied to sizing equity.
    """
    retain = max(0.0, min(1.0, float(profit_retain_pct)))
    if realized_pnl > 0:
        return float(sizing_equity) + realized_pnl * retain
    return float(sizing_equity) + realized_pnl


def contracts_from_sizing_equity(
    sizing_equity: float,
    margin_pct: float,
    leverage: float,
    mark_price: float,
    contract_value: float,
) -> int:
    """
    margin = equity × margin_pct; notional = margin × leverage;
    contracts = floor(notional / (price × contract_value)).
    """
    if sizing_equity <= 0 or mark_price <= 0 or contract_value <= 0:
        return 0
    margin = float(sizing_equity) * float(margin_pct)
    notional = margin * float(leverage)
    unit_notional = float(mark_price) * float(contract_value)
    if unit_notional <= 0:
        return 0
    qty = int(math.floor(notional / unit_notional))
    return max(0, qty)


def is_valid_sizing_mode(mode: str) -> bool:
    return mode in ("fixed", "dynamic")
