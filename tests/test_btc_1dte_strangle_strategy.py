"""Unit tests for BTC 1-DTE short strangle live strategy logic."""

import pytest
from datetime import datetime, time

from src.config.constants import IST_TIMEZONE
from src.core.models.trade import StrategyState
from src.strategies.btc_1dte_strangle.models import Btc1DteStrangleConfig
from src.strategies.btc_1dte_strangle.sizing import scaled_take_profit
from src.strategies.btc_1dte_strangle.strategy import BTC1DteShortStrangleStrategy


@pytest.mark.asyncio
async def test_parso_expiry_day_exit_not_next_calendar_day(mock_exchange):
    cfg = Btc1DteStrangleConfig(entry_time=time(22, 45), exit_time=time(17, 25), expiry_calendar_days=2)
    strategy = BTC1DteShortStrangleStrategy(exchange_adapter=mock_exchange, config=cfg)
    entry_ist = datetime(2026, 3, 10, 22, 48, 0, tzinfo=IST_TIMEZONE)
    ce_inst = mock_exchange.instruments[1]
    pe_inst = mock_exchange.instruments[3]
    trade = await strategy.create_trade(
        spot_price=95000.0,
        ce_inst=ce_inst,
        pe_inst=pe_inst,
        ce_est_prem=80.0,
        pe_est_prem=70.0,
        now_ist=entry_ist,
    )
    same_day_late = datetime(2026, 3, 10, 23, 0, 0, tzinfo=IST_TIMEZONE)
    assert strategy.should_force_exit(same_day_late, trade) is False
    next_calendar_day = datetime(2026, 3, 11, 17, 30, 0, tzinfo=IST_TIMEZONE)
    assert strategy.should_force_exit(next_calendar_day, trade) is False
    parso_exit = datetime(2026, 3, 12, 17, 30, 0, tzinfo=IST_TIMEZONE)
    assert strategy.should_force_exit(parso_exit, trade) is True


@pytest.mark.asyncio
async def test_combined_take_profit_disabled_by_default(mock_exchange):
    strategy = BTC1DteShortStrangleStrategy(exchange_adapter=mock_exchange)
    entry_ist = datetime(2026, 3, 10, 22, 48, 0, tzinfo=IST_TIMEZONE)
    ce_inst = mock_exchange.instruments[1]
    pe_inst = mock_exchange.instruments[3]
    tp_hits = []

    async def on_tp(t):
        tp_hits.append(t.strategy_trade_id)

    async def qty(_ce, _pe):
        return 100

    strategy.set_execution_callbacks(on_entry=None, on_sl=None, on_exit=None, on_tp=on_tp, resolve_quantity=qty)
    trade = await strategy.create_trade(
        spot_price=95000.0,
        ce_inst=ce_inst,
        pe_inst=pe_inst,
        ce_est_prem=80.0,
        pe_est_prem=70.0,
        now_ist=entry_ist,
    )
    strategy.on_entry_filled(
        trade,
        ce_fill_price=80.0,
        pe_fill_price=70.0,
        ce_order_id="1",
        pe_order_id="2",
        ce_client_order_id="a",
        pe_client_order_id="b",
        now_ist=entry_ist,
    )

    from src.core.models.market_data import Ticker

    ce_tick = Ticker(symbol=ce_inst.symbol, instrument_id=ce_inst.instrument_id, last_price=65.0)
    pe_tick = Ticker(symbol=pe_inst.symbol, instrument_id=pe_inst.instrument_id, last_price=55.0)
    await strategy.on_tick(ce_tick)
    await strategy.on_tick(pe_tick)
    assert len(tp_hits) == 0
    assert trade.state == StrategyState.ACTIVE


def test_scaled_take_profit_matches_backtest():
    assert scaled_take_profit(100, base_usd=3.0, calibration_contracts=100) == 3.0
    assert abs(scaled_take_profit(657, base_usd=3.0, calibration_contracts=100) - 19.71) < 1e-9
