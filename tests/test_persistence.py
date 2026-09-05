"""Tests for atomic state persistence across restarts."""

import pytest
from src.state.persistence import StatePersistence
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.models.instrument import OptionType


def test_atomic_persistence_save_and_load(tmp_path):
    state_file = tmp_path / "trade_state.json"
    persistence = StatePersistence(file_path=str(state_file))

    ce_leg = StrategyLeg(
        leg_id="CE_1",
        option_type=OptionType.CALL,
        instrument_id="101",
        symbol="C-BTC-98000-010926",
        strike=98000.0,
        expiry_date="010926",
        quantity=1.0,
        intended_premium=100.0,
        entry_fill_price=100.0,
        sl_price=200.0,
        status=LegStatus.OPEN,
    )
    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_20260901_090000",
        strategy_name="btc_short_strangle",
        trade_date="2026-09-01",
        underlying_spot_at_entry=95000.0,
        ce_leg=ce_leg,
        state=StrategyState.ACTIVE,
    )

    # Save state
    saved = persistence.save_state(current_trade=trade)
    assert saved is True
    assert state_file.exists()

    # Load state in a new persistence instance
    persistence2 = StatePersistence(file_path=str(state_file))
    loaded_trade, history = persistence2.load_state()

    assert loaded_trade is not None
    assert loaded_trade.strategy_trade_id == "STRANGLE_20260901_090000"
    assert loaded_trade.state == StrategyState.ACTIVE
    assert loaded_trade.ce_leg is not None
    assert loaded_trade.ce_leg.sl_price == 200.0
