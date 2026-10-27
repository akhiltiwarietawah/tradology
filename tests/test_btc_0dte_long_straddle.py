"""Tests for BTC 0DTE Long Straddle Strategy and Sizing."""

import pytest
from datetime import time, datetime
import pytz

from src.strategies.btc_0dte_long_straddle.models import LongStraddleConfig
from src.strategies.btc_0dte_long_straddle.sizing import (
    calculate_straddle_contracts,
    effective_equity_for_entry,
    apply_exit_to_virtual_equity,
)


def test_fixed_position_sizing():
    """Verify fixed sizing returns fixed lots clamped by limits."""
    lots = calculate_straddle_contracts(
        mode="fixed",
        fixed_lots=10,
        effective_equity=100.0,
        call_premium=175.0,
        put_premium=175.0,
        min_lots=1,
        max_lots=100,
    )
    assert lots == 10

    # Max clamp test
    lots_clamped = calculate_straddle_contracts(
        mode="fixed",
        fixed_lots=150,
        effective_equity=100.0,
        call_premium=175.0,
        put_premium=175.0,
        min_lots=1,
        max_lots=100,
    )
    assert lots_clamped == 100


def test_dynamic_position_sizing():
    """
    Verify dynamic sizing:
    Equity = $100, Margin = 25% -> Budget = $25
    Straddle = 175 CE + 175 PE = 350 pts
    Cost per contract = 350 * 0.001 = $0.35
    Contracts = floor(25 / 0.35) = 71 contracts
    """
    contracts = calculate_straddle_contracts(
        mode="dynamic",
        fixed_lots=10,
        effective_equity=100.0,
        call_premium=175.0,
        put_premium=175.0,
        contract_value=0.001,
        margin_pct=0.25,
        min_lots=1,
        max_lots=500,
    )
    assert contracts == 71


def test_effective_equity_calculation():
    """Test virtual equity capping and wallet fallback."""
    # Wallet > Virtual: capped at virtual
    assert effective_equity_for_entry(account_balance_usd=200.0, virtual_equity=100.0) == 100.0

    # Wallet < Virtual: wallet constrained
    assert effective_equity_for_entry(account_balance_usd=50.0, virtual_equity=100.0) == 50.0

    # Virtual is None: returns full wallet
    assert effective_equity_for_entry(account_balance_usd=150.0, virtual_equity=None) == 150.0


def test_apply_exit_virtual_equity():
    """Test 50% profit retention on wins and 100% loss deduction."""
    # Winning trade of $40: 50% ($20) retained
    eq_after_win = apply_exit_to_virtual_equity(virtual_equity=100.0, realized_net_pnl=40.0, profit_retain_pct=0.5)
    assert eq_after_win == 120.0

    # Losing trade of -$15: full $15 deducted
    eq_after_loss = apply_exit_to_virtual_equity(virtual_equity=120.0, realized_net_pnl=-15.0, profit_retain_pct=0.5)
    assert eq_after_loss == 105.0


def test_config_schedule_and_days():
    """Verify default schedule parameters."""
    config = LongStraddleConfig()
    assert config.entry_time == time(13, 0)
    assert config.exit_time == time(17, 30)
    assert config.allowed_weekdays == [0, 1, 2, 3, 4]  # Mon-Fri
    assert config.position_sizing_mode == "fixed"
    assert config.fixed_lots == 10
