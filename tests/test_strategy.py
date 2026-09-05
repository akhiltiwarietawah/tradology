"""Tests for BTC 0DTE Short Strangle strategy logic and independent SL triggers."""

import pytest
from datetime import datetime, time
import pytz

from src.config.constants import IST_TIMEZONE
from src.core.models.trade import StrategyState, LegStatus
from src.core.models.market_data import Ticker
from src.strategies.short_strangle.strategy import BTCShortStrangleStrategy
from src.strategies.short_strangle.models import ShortStrangleConfig


@pytest.mark.asyncio
async def test_100_percent_sl_calculation_and_independent_trigger(mock_exchange):
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange)
    now_ist = datetime(2026, 9, 1, 9, 5, 0, tzinfo=IST_TIMEZONE)

    ce_inst = mock_exchange.instruments[1]  # C-BTC-98000
    pe_inst = mock_exchange.instruments[3]  # P-BTC-92000

    trade = strategy.create_trade(
        spot_price=95000.0,
        ce_inst=ce_inst,
        pe_inst=pe_inst,
        ce_est_prem=100.0,
        pe_est_prem=100.0,
        now_ist=now_ist,
    )

    # Simulate fills at $100 entry
    strategy.on_entry_filled(
        trade=trade,
        ce_fill_price=100.0,
        pe_fill_price=100.0,
        ce_order_id="1",
        pe_order_id="2",
        ce_client_order_id="cid_ce",
        pe_client_order_id="cid_pe",
        now_ist=now_ist,
    )

    # 1. Verify 100% SL calculation (entry $100 * (1 + 1.0) = $200)
    assert trade.ce_leg.sl_price == 200.0
    assert trade.pe_leg.sl_price == 200.0
    assert trade.state == StrategyState.ACTIVE

    # 2. Track SL triggers
    sl_triggered_legs = []

    async def _on_sl(leg, px):
        sl_triggered_legs.append((leg.symbol, px))

    strategy.set_execution_callbacks(on_entry=None, on_sl=_on_sl, on_exit=None)

    # Tick 1: CE price spikes to $205 (breaches $200 SL)
    ce_spike_tick = Ticker(symbol=ce_inst.symbol, instrument_id=ce_inst.instrument_id, last_price=205.0)
    await strategy.on_tick(ce_spike_tick)

    # Verify CE SL triggered
    assert len(sl_triggered_legs) == 1
    assert sl_triggered_legs[0] == (ce_inst.symbol, 205.0)
    assert trade.ce_leg.sl_triggered is True

    # Simulate CE closure
    strategy.on_leg_closed(trade.ce_leg, exit_price=205.0, exit_reason="STOP_LOSS")
    assert trade.ce_leg.status == LegStatus.STOPPED_OUT
    assert trade.ce_leg.realized_pnl == round((100.0 - 205.0) * trade.ce_leg.quantity * trade.ce_leg.contract_value, 4)

    # CRITICAL CHECK: PE leg must STILL be OPEN and running!
    assert trade.pe_leg.status == LegStatus.OPEN
    assert trade.has_any_open_leg is True
    assert trade.state == StrategyState.ACTIVE

    # Tick 2: PE price normal at $80 -> no trigger
    pe_normal_tick = Ticker(symbol=pe_inst.symbol, instrument_id=pe_inst.instrument_id, last_price=80.0)
    await strategy.on_tick(pe_normal_tick)
    assert len(sl_triggered_legs) == 1

    # Tick 3: PE price spikes to $210 (breaches $200 SL)
    pe_spike_tick = Ticker(symbol=pe_inst.symbol, instrument_id=pe_inst.instrument_id, last_price=210.0)
    await strategy.on_tick(pe_spike_tick)

    assert len(sl_triggered_legs) == 2
    assert sl_triggered_legs[1] == (pe_inst.symbol, 210.0)

    # Simulate PE closure
    strategy.on_leg_closed(trade.pe_leg, exit_price=210.0, exit_reason="STOP_LOSS")
    assert trade.pe_leg.status == LegStatus.STOPPED_OUT

    # Now both legs are closed -> trade marked COMPLETED
    assert trade.state == StrategyState.COMPLETED


def test_entry_window_and_single_entry_per_day(mock_exchange):
    cfg = ShortStrangleConfig(entry_time=time(9, 0, 0), entry_window_minutes=15)
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange, config=cfg)

    # Time at 08:50 IST -> Outside window
    t1 = datetime(2026, 9, 1, 8, 50, 0, tzinfo=IST_TIMEZONE)
    assert strategy.is_entry_window(t1) is False
    assert strategy.can_enter_today(t1) is False

    # Time at 09:05 IST -> Inside window
    t2 = datetime(2026, 9, 1, 9, 5, 0, tzinfo=IST_TIMEZONE)
    assert strategy.is_entry_window(t2) is True
    assert strategy.can_enter_today(t2) is True

    # After an entry is completed today -> can_enter_today must return False
    strategy.current_trade = strategy.create_trade(
        spot_price=95000.0,
        ce_inst=mock_exchange.instruments[0],
        pe_inst=mock_exchange.instruments[2],
        ce_est_prem=100.0,
        pe_est_prem=100.0,
        now_ist=t2,
    )
    strategy.current_trade.state = StrategyState.ACTIVE

    # Cannot enter second time on same day
    assert strategy.can_enter_today(t2) is False


@pytest.mark.asyncio
async def test_strategy_rest_polling_fallback_when_ws_is_stale(mock_exchange):
    """
    When WebSocket is stale or disconnected, strategy on_timer should poll REST tickers
    to monitor Stop Loss triggers without dropping coverage.
    """
    cfg = ShortStrangleConfig(entry_time=time(9, 0, 0), exit_time=time(17, 15, 0))
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange, config=cfg)
    await strategy.start()

    t_now = datetime(2026, 9, 1, 11, 0, 0, tzinfo=IST_TIMEZONE)
    ce_inst = mock_exchange.instruments[1]
    pe_inst = mock_exchange.instruments[3]

    trade = strategy.create_trade(95000.0, ce_inst, pe_inst, 100.0, 100.0, now_ist=t_now)
    strategy.on_entry_filled(trade, 100.0, 100.0, "1", "2", "c1", "c2", now_ist=t_now)

    # Set exchange adapter as stale
    mock_exchange.is_stale = True

    # Update REST tickers to simulate a breach on CE ($210 > $200 SL)
    mock_exchange.tickers_map[ce_inst.symbol] = Ticker(
        symbol=ce_inst.symbol,
        instrument_id=ce_inst.instrument_id,
        last_price=210.0,
        mark_price=210.0,
    )

    sl_triggered_legs = []
    async def _on_sl(leg, px):
        sl_triggered_legs.append((leg.symbol, px))

    strategy.set_execution_callbacks(on_entry=None, on_sl=_on_sl, on_exit=None)

    # Call on_timer: should trigger REST polling fallback and detect SL breach
    await strategy.on_timer(t_now)

    assert len(sl_triggered_legs) == 1
    assert sl_triggered_legs[0] == (ce_inst.symbol, 210.0)
    assert trade.ce_leg.sl_triggered is True
