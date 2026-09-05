"""Tests for FAILED_ENTRY same-day retry policy, cooldown, throttling, and reconciliation safety."""

import pytest
import asyncio
from datetime import datetime, time
from unittest.mock import AsyncMock, patch, MagicMock

from src.config.constants import IST_TIMEZONE
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.models.instrument import OptionType
from src.core.models.position import Position
from src.core.models.order import Order, OrderState, OrderSide
from src.strategies.short_strangle.strategy import BTCShortStrangleStrategy
from src.strategies.short_strangle.models import ShortStrangleConfig
from src.engine import TradingEngine
from src.config.settings import Settings


def _create_sample_trade(
    state: StrategyState = StrategyState.FAILED_ENTRY,
    ce_status: LegStatus = LegStatus.PENDING_ENTRY,
    pe_status: LegStatus = LegStatus.PENDING_ENTRY,
    ce_fill_px: float = None,
    pe_fill_px: float = None,
    ce_order_id: str = None,
    pe_order_id: str = None,
    trade_date: str = "2026-09-02",
) -> StrategyTrade:
    ce_leg = StrategyLeg(
        leg_id="CE_1",
        option_type=OptionType.CALL,
        instrument_id="150246",
        symbol="C-BTC-78000-020926",
        strike=78000.0,
        expiry_date="020926",
        quantity=10.0,
        intended_premium=117.5,
        entry_fill_price=ce_fill_px,
        entry_order_id=ce_order_id,
        status=ce_status,
    )
    pe_leg = StrategyLeg(
        leg_id="PE_1",
        option_type=OptionType.PUT,
        instrument_id="150234",
        symbol="P-BTC-77200-020926",
        strike=77200.0,
        expiry_date="020926",
        quantity=10.0,
        intended_premium=90.0,
        entry_fill_price=pe_fill_px,
        entry_order_id=pe_order_id,
        status=pe_status,
    )
    return StrategyTrade(
        strategy_trade_id="STRANGLE_20260902_090000",
        strategy_name="btc_short_strangle",
        trade_date=trade_date,
        ce_leg=ce_leg,
        pe_leg=pe_leg,
        state=state,
    )


# -------------------------------------------------------------------------
# Unit Tests for can_enter_today & Trade Retry Rules
# -------------------------------------------------------------------------

def test_zero_fill_clean_failure_retry_allowed(mock_exchange):
    """1. Zero-fill clean failure within entry window allows retry after cooldown."""
    cfg = ShortStrangleConfig(entry_time=time(9, 0, 0), entry_window_minutes=15, entry_retry_cooldown_seconds=15.0)
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange, config=cfg)
    now_ist = datetime(2026, 9, 2, 9, 5, 0, tzinfo=IST_TIMEZONE)

    # Set clean failed trade
    clean_failed_trade = _create_sample_trade(state=StrategyState.FAILED_ENTRY)
    strategy.current_trade = clean_failed_trade
    assert clean_failed_trade.has_any_fill_or_order is False

    # Should allow entry because no real orders/fills or unwinds occurred
    assert strategy.can_enter_today(now_ist=now_ist) is True


def test_partial_fill_blocks_retry(mock_exchange):
    """4. If one leg was accepted/filled, retry is strictly blocked."""
    cfg = ShortStrangleConfig(entry_time=time(9, 0, 0), entry_window_minutes=15)
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange, config=cfg)
    now_ist = datetime(2026, 9, 2, 9, 5, 0, tzinfo=IST_TIMEZONE)

    # CE had an accepted order / fill price
    partial_trade = _create_sample_trade(
        state=StrategyState.FAILED_ENTRY,
        ce_status=LegStatus.OPEN,
        ce_fill_px=115.0,
        ce_order_id="12345",
    )
    assert partial_trade.has_any_fill_or_order is True
    strategy.current_trade = partial_trade

    assert strategy.can_enter_today(now_ist=now_ist) is False


def test_emergency_unwind_blocks_retry(mock_exchange):
    """5. If emergency unwind occurred, retry is permanently blocked for the day."""
    cfg = ShortStrangleConfig(entry_time=time(9, 0, 0), entry_window_minutes=15)
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange, config=cfg)
    now_ist = datetime(2026, 9, 2, 9, 5, 0, tzinfo=IST_TIMEZONE)

    unwound_trade = _create_sample_trade(
        state=StrategyState.FAILED_ENTRY,
        ce_status=LegStatus.UNWOUND_ON_FAILURE,
    )
    assert unwound_trade.has_any_fill_or_order is True
    strategy.current_trade = unwound_trade

    assert strategy.can_enter_today(now_ist=now_ist) is False


def test_active_trade_blocks_retry(mock_exchange):
    """6. Existing ACTIVE trade blocks new entry."""
    cfg = ShortStrangleConfig(entry_time=time(9, 0, 0), entry_window_minutes=15)
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange, config=cfg)
    now_ist = datetime(2026, 9, 2, 9, 5, 0, tzinfo=IST_TIMEZONE)

    active_trade = _create_sample_trade(state=StrategyState.ACTIVE)
    strategy.current_trade = active_trade

    assert strategy.can_enter_today(now_ist=now_ist) is False


def test_completed_trade_blocks_retry(mock_exchange):
    """7. Existing COMPLETED trade blocks new entry."""
    cfg = ShortStrangleConfig(entry_time=time(9, 0, 0), entry_window_minutes=15)
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange, config=cfg)
    now_ist = datetime(2026, 9, 2, 9, 5, 0, tzinfo=IST_TIMEZONE)

    completed_trade = _create_sample_trade(state=StrategyState.COMPLETED)
    strategy.current_trade = completed_trade

    assert strategy.can_enter_today(now_ist=now_ist) is False


def test_retry_outside_entry_window_blocked(mock_exchange):
    """8. Clean failed trade cannot retry outside entry window (e.g. 09:16 IST)."""
    cfg = ShortStrangleConfig(entry_time=time(9, 0, 0), entry_window_minutes=15)
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange, config=cfg)
    outside_ist = datetime(2026, 9, 2, 9, 16, 0, tzinfo=IST_TIMEZONE)

    clean_failed_trade = _create_sample_trade(state=StrategyState.FAILED_ENTRY)
    strategy.current_trade = clean_failed_trade

    assert strategy.can_enter_today(now_ist=outside_ist) is False


def test_retry_before_cooldown_expires_blocked(mock_exchange):
    """9. Retry before the 15-second cooldown expires is blocked."""
    cfg = ShortStrangleConfig(entry_time=time(9, 0, 0), entry_window_minutes=15, entry_retry_cooldown_seconds=15.0)
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange, config=cfg)
    now_ist = datetime(2026, 9, 2, 9, 5, 0, tzinfo=IST_TIMEZONE)

    # Record attempt at timestamp 100.0
    strategy.record_entry_attempt(now_ist=now_ist, timestamp=100.0)

    # 5 seconds later (timestamp 105.0) -> cooldown active -> blocked
    assert strategy.can_enter_today(now_ist=now_ist, current_timestamp=105.0) is False

    # 16 seconds later (timestamp 116.0) -> cooldown elapsed -> allowed
    assert strategy.can_enter_today(now_ist=now_ist, current_timestamp=116.0) is True


def test_maximum_retry_count_reached_blocked(mock_exchange):
    """10. Maximum retry count (3 attempts) blocks further entries for the day."""
    cfg = ShortStrangleConfig(
        entry_time=time(9, 0, 0),
        entry_window_minutes=15,
        max_entry_retries=3,
        entry_retry_cooldown_seconds=15.0,
    )
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange, config=cfg)
    now_ist = datetime(2026, 9, 2, 9, 5, 0, tzinfo=IST_TIMEZONE)

    # Attempt 1
    strategy.record_entry_attempt(now_ist=now_ist, timestamp=100.0)
    assert strategy.can_enter_today(now_ist=now_ist, current_timestamp=120.0) is True

    # Attempt 2
    strategy.record_entry_attempt(now_ist=now_ist, timestamp=120.0)
    assert strategy.can_enter_today(now_ist=now_ist, current_timestamp=140.0) is True

    # Attempt 3
    strategy.record_entry_attempt(now_ist=now_ist, timestamp=140.0)
    # Reached limit (3/3)
    assert strategy.can_enter_today(now_ist=now_ist, current_timestamp=160.0) is False


# -------------------------------------------------------------------------
# Integration Tests with TradingEngine & Exchange Reconciliation
# -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zero_fill_failure_exchange_position_blocks_retry(tmp_path, mocker):
    """2. Zero-fill failure locally, but exchange has an open position -> blocked."""
    state_file = str(tmp_path / "trade_state.json")
    settings = Settings(
        delta_env="testnet",
        dry_run=True,
        kill_switch=False,
        state_file=state_file,
        db_enabled=False,
        entry_window_minutes=15,
    )
    engine = TradingEngine(settings=settings)

    # Mock exchange to return an open position on the CE symbol
    mock_pos = Position(
        instrument_id="150246",
        symbol="C-BTC-78000-020926",
        size=-10.0,
        entry_price=117.5,
    )
    mocker.patch.object(engine.delta_adapter, "get_positions", return_value=[mock_pos])
    mocker.patch.object(engine.delta_adapter, "get_open_orders", return_value=[])

    # Reconcile state
    res = await engine.reconcile_state()
    assert res.is_synchronized is True

    # Attempt entry trigger that fails
    trade = _create_sample_trade(state=StrategyState.PENDING_ENTRY)
    mocker.patch.object(engine.execution_engine, "execute_strangle_entry", return_value=(False, None, None))
    
    ce_inst = MagicMock(instrument_id="150246", symbol="C-BTC-78000-020926")
    pe_inst = MagicMock(instrument_id="150234", symbol="P-BTC-77200-020926")

    engine.strategy._active = True
    await engine._handle_strategy_entry_trigger(trade, ce_inst, pe_inst, 117.5, 90.0)

    # After failure handling, reconciler detects that an open position exists on exchange for the strategy symbol!
    # Because position exists on exchange, status is SAFE_HALT -> retry is blocked and kill switch active
    assert engine.strategy.current_trade is not None
    assert engine.strategy.current_trade.state in (StrategyState.SAFE_HALT, StrategyState.FAILED_ENTRY)
    assert engine.risk_manager.is_kill_switch_active is True
    assert engine.strategy.can_enter_today() is False


@pytest.mark.asyncio
async def test_zero_fill_failure_exchange_open_order_blocks_retry(tmp_path, mocker):
    """3. Zero-fill failure locally, but exchange has an open order -> blocked."""
    state_file = str(tmp_path / "trade_state.json")
    settings = Settings(
        delta_env="testnet",
        dry_run=True,
        kill_switch=False,
        state_file=state_file,
        db_enabled=False,
        entry_window_minutes=15,
    )
    engine = TradingEngine(settings=settings)

    mock_order = Order(
        order_id="999888",
        client_order_id="test_open",
        instrument_id="150246",
        symbol="C-BTC-78000-020926",
        side=OrderSide.SELL,
        order_type=MagicMock(),
        quantity=10.0,
        state=OrderState.OPEN,
    )
    mocker.patch.object(engine.delta_adapter, "get_positions", return_value=[])
    mocker.patch.object(engine.delta_adapter, "get_open_orders", return_value=[mock_order])

    # When entry fails, post-failure reconciliation finds open orders matching the symbol
    trade = _create_sample_trade(state=StrategyState.PENDING_ENTRY)
    mocker.patch.object(engine.execution_engine, "execute_strangle_entry", return_value=(False, None, None))
    ce_inst = MagicMock(instrument_id="150246", symbol="C-BTC-78000-020926")
    pe_inst = MagicMock(instrument_id="150234", symbol="P-BTC-77200-020926")

    engine.strategy._active = True
    await engine._handle_strategy_entry_trigger(trade, ce_inst, pe_inst, 117.5, 90.0)

    # Reconciler returned non-CLEAN_IDLE due to open order -> current_trade is retained as terminal
    assert engine.strategy.current_trade is not None
    assert engine.strategy.current_trade.state in (StrategyState.SAFE_HALT, StrategyState.FAILED_ENTRY)
    assert engine.risk_manager.is_kill_switch_active is True
    assert engine.strategy.can_enter_today() is False


@pytest.mark.asyncio
async def test_restart_with_clean_failed_entry_and_clean_idle_allows_retry(tmp_path, mocker):
    """11. Engine starts with clean zero-fill FAILED_ENTRY in state + exchange is CLEAN_IDLE -> allows retry."""
    state_file = str(tmp_path / "trade_state.json")
    
    # Pre-populate state file with a clean zero-fill FAILED_ENTRY trade
    clean_failed_trade = _create_sample_trade(state=StrategyState.FAILED_ENTRY, trade_date="2026-09-02")
    from src.state.persistence import StatePersistence
    p = StatePersistence(file_path=state_file)
    p.save_state(clean_failed_trade)

    settings = Settings(
        delta_env="testnet",
        dry_run=True,
        kill_switch=False,
        state_file=state_file,
        db_enabled=False,
        entry_window_minutes=15,
    )
    engine = TradingEngine(settings=settings)

    # Mock exchange as clean
    mocker.patch.object(engine.delta_adapter, "get_positions", return_value=[])
    mocker.patch.object(engine.delta_adapter, "get_open_orders", return_value=[])
    mocker.patch.object(engine.delta_adapter, "get_account_balances", return_value=MagicMock(balances={}))
    mocker.patch.object(engine.delta_adapter, "subscribe_market_data", return_value=None)

    # Start engine
    await engine.start()

    # Verify that clean failed trade was moved to history and current_trade is None (CLEAN_IDLE)
    assert engine.strategy.current_trade is None
    assert len(engine.state_store._historical_trades) == 1
    assert engine.state_store._historical_trades[0].strategy_trade_id == "STRANGLE_20260902_090000"

    # Within entry window at 09:05 IST -> can_enter_today should be True
    now_ist = datetime(2026, 9, 2, 9, 5, 0, tzinfo=IST_TIMEZONE)
    assert engine.strategy.can_enter_today(now_ist=now_ist, history=engine.state_store._historical_trades) is True

    await engine.stop()


@pytest.mark.asyncio
async def test_restart_with_failed_entry_and_exchange_ambiguity_blocks_retry(tmp_path, mocker):
    """12. Engine starts with FAILED_ENTRY, but exchange query fails / discrepancy -> SAFE_HALT / blocked."""
    state_file = str(tmp_path / "trade_state.json")
    
    failed_trade = _create_sample_trade(state=StrategyState.FAILED_ENTRY, trade_date="2026-09-02")
    from src.state.persistence import StatePersistence
    p = StatePersistence(file_path=state_file)
    p.save_state(failed_trade)

    settings = Settings(
        delta_env="testnet",
        dry_run=True,
        kill_switch=False,
        state_file=state_file,
        db_enabled=False,
    )
    engine = TradingEngine(settings=settings)

    # Mock exchange failure during reconciliation
    mocker.patch.object(engine.delta_adapter, "get_positions", side_effect=Exception("Exchange network error"))
    mocker.patch.object(engine.delta_adapter, "get_account_balances", return_value=MagicMock(balances={}))

    # Start engine
    await engine.start()

    # Strategy should NOT be active and trading should be paused/blocked
    assert engine.strategy.is_active is False

    await engine.stop()
