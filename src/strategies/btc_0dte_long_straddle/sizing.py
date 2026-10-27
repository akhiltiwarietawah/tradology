"""Sizing and equity calculations for BTC 0DTE Long Straddle."""

from __future__ import annotations
import math
from typing import Literal

PositionSizingMode = Literal["fixed", "dynamic"]


def effective_equity_for_entry(account_balance_usd: float, virtual_equity: float | None) -> float:
    """
    Entry sizing base: live wallet available balance, capped by virtual equity when set.
    """
    acct = max(0.0, float(account_balance_usd))
    virtual = (
        float(virtual_equity)
        if virtual_equity is not None and float(virtual_equity) > 0
        else None
    )
    if acct > 0 and virtual is not None:
        return min(acct, virtual)
    if acct > 0:
        return acct
    return virtual or 0.0


def calculate_straddle_contracts(
    mode: PositionSizingMode,
    fixed_lots: int,
    effective_equity: float,
    call_premium: float,
    put_premium: float,
    *,
    contract_value: float = 0.001,
    margin_pct: float = 0.25,
    min_lots: int = 1,
    max_lots: int = 1000,
) -> int:
    """
    Compute number of straddle contracts based on sizing mode:
    - 'fixed': Return fixed_lots directly (clamped between min_lots and max_lots).
    - 'dynamic': Allocate margin_pct of effective equity to buy straddle:
        budget = effective_equity * margin_pct
        cost_per_contract = (call_premium + put_premium) * contract_value
        contracts = floor(budget / cost_per_contract)
    """
    if mode == "fixed":
        return max(min_lots, min(int(fixed_lots), max_lots))

    # Dynamic mode
    budget = float(effective_equity) * float(margin_pct)
    combined_premium_points = float(call_premium) + float(put_premium)
    cost_per_contract = combined_premium_points * float(contract_value)

    if budget <= 0 or cost_per_contract <= 0:
        return max(min_lots, 0)

    contracts = int(math.floor(budget / cost_per_contract))
    return max(min_lots, min(contracts, max_lots))


def apply_exit_to_virtual_equity(
    virtual_equity: float,
    realized_net_pnl: float,
    profit_retain_pct: float = 0.5,
) -> float:
    """
    Update virtual equity after a closed straddle trade:
    - On profit: Only profit_retain_pct of net profit is added (simulates 50% profit withdrawal).
    - On loss: 100% of loss is deducted.
    """
    retain = max(0.0, min(1.0, float(profit_retain_pct)))
    if realized_net_pnl > 0:
        return float(virtual_equity) + (realized_net_pnl * retain)
    return float(virtual_equity) + realized_net_pnl
