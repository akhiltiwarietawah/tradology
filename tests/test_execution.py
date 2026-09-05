"""Tests for ExecutionEngine and Two-Leg Entry Failure Emergency Unwind."""

import pytest
from src.core.models.order import OrderRequest, OrderSide, OrderType, OrderState
from src.core.models.trade import StrategyState, LegStatus
from src.execution.execution_engine import ExecutionEngine
from src.execution.order_manager import OrderManager
from src.strategies.short_strangle.strategy import BTCShortStrangleStrategy


@pytest.mark.asyncio
async def test_two_leg_entry_success(mock_exchange):
    engine = ExecutionEngine(exchange_adapter=mock_exchange)
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange)
    ce_inst = mock_exchange.instruments[1]
    pe_inst = mock_exchange.instruments[3]

    trade = strategy.create_trade(95000.0, ce_inst, pe_inst, 100.0, 100.0)

    ce_req = OrderRequest(instrument_id=ce_inst.instrument_id, symbol=ce_inst.symbol, side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=1.0)
    pe_req = OrderRequest(instrument_id=pe_inst.instrument_id, symbol=pe_inst.symbol, side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=1.0)

    success, ce_ord, pe_ord = await engine.execute_strangle_entry(trade, ce_req, pe_req)
    assert success is True
    assert ce_ord.is_filled
    assert pe_ord.is_filled


@pytest.mark.asyncio
async def test_two_leg_entry_failure_emergency_unwind(mock_exchange):
    """
    CRITICAL TEST: When CE fills and PE fails, CE must be immediately unwound
    and the position verified zero, never leaving a naked short.
    """
    engine = ExecutionEngine(exchange_adapter=mock_exchange)
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange)

    ce_inst = mock_exchange.instruments[1]
    pe_inst = mock_exchange.instruments[3]

    # Make PE order placement fail
    mock_exchange.fail_specific_symbol = pe_inst.symbol

    trade = strategy.create_trade(95000.0, ce_inst, pe_inst, 100.0, 100.0)

    ce_req = OrderRequest(instrument_id=ce_inst.instrument_id, symbol=ce_inst.symbol, side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=1.0, client_order_id="cid_ce")
    pe_req = OrderRequest(instrument_id=pe_inst.instrument_id, symbol=pe_inst.symbol, side=OrderSide.SELL, order_type=OrderType.MARKET, quantity=1.0, client_order_id="cid_pe")

    success, ce_ord, pe_ord = await engine.execute_strangle_entry(trade, ce_req, pe_req)

    # 1. Entry must be marked as failed
    assert success is False
    assert trade.state == StrategyState.FAILED_ENTRY
    assert trade.ce_leg.status == LegStatus.UNWOUND_ON_FAILURE

    # 2. Emergency unwind BUY order must have been placed for CE
    placed_buys = [o for o in mock_exchange.placed_orders if o.symbol == ce_inst.symbol and o.side == OrderSide.BUY]
    assert len(placed_buys) == 1
    assert placed_buys[0].quantity == 1.0
    assert placed_buys[0].reduce_only is True

    # 3. Position for CE on exchange must be 0 (flat)
    positions = await mock_exchange.get_positions()
    ce_pos = [p for p in positions if p.symbol == ce_inst.symbol][0]
    assert ce_pos.size == 0.0


def test_order_manager_deduplication():
    om = OrderManager()
    cid1 = om.generate_client_order_id("strangle", "20260901_090000", "CE", OrderSide.SELL)
    assert om.register_order_attempt(cid1) is True

    # Duplicate registration must fail
    assert om.register_order_attempt(cid1) is False


@pytest.mark.asyncio
async def test_attach_exchange_bracket_sl_success(mock_exchange):
    """Verify ExecutionEngine correctly attaches native bracket SL and sets leg metadata."""
    engine = ExecutionEngine(exchange_adapter=mock_exchange)
    strategy = BTCShortStrangleStrategy(exchange_adapter=mock_exchange)
    ce_inst = mock_exchange.instruments[1]
    pe_inst = mock_exchange.instruments[3]

    trade = strategy.create_trade(95000.0, ce_inst, pe_inst, 100.0, 100.0)
    strategy.on_entry_filled(
        trade=trade,
        ce_fill_price=100.0,
        pe_fill_price=100.0,
        ce_order_id="1",
        pe_order_id="2",
        ce_client_order_id="c1",
        pe_client_order_id="c2",
    )

    ce_ok = await engine.attach_exchange_bracket_sl(trade.ce_leg, trade.ce_leg.sl_price)
    pe_ok = await engine.attach_exchange_bracket_sl(trade.pe_leg, trade.pe_leg.sl_price)

    assert ce_ok is True
    assert pe_ok is True
    assert trade.ce_leg.exchange_sl_active is True
    assert trade.ce_leg.bracket_order_id == f"BRK_{ce_inst.instrument_id}_200"
    assert trade.ce_leg.sl_price == 200.0
    assert trade.pe_leg.exchange_sl_active is True
    assert trade.pe_leg.bracket_order_id == f"BRK_{pe_inst.instrument_id}_200"
    assert trade.pe_leg.sl_price == 200.0


@pytest.mark.asyncio
async def test_engine_bracket_creation_failure_triggers_emergency_square_off(test_settings, mock_exchange):
    """
    CRITICAL TEST: If bracket creation fails upon entry, the engine MUST NOT leave
    an unprotected naked short. It must trigger emergency square-off and enter SAFE_HALT.
    """
    from src.engine import TradingEngine

    # Make bracket creation fail on exchange
    mock_exchange.fail_bracket_creation = True

    engine = TradingEngine(settings=test_settings)
    engine.delta_adapter = mock_exchange
    engine.exchange_service.register_adapter(mock_exchange)
    engine.execution_engine.exchange = mock_exchange
    engine.strategy._active = True

    ce_inst = mock_exchange.instruments[1]
    pe_inst = mock_exchange.instruments[3]
    trade = engine.strategy.create_trade(95000.0, ce_inst, pe_inst, 100.0, 100.0)

    await engine._handle_strategy_entry_trigger(
        trade=trade,
        ce_inst=ce_inst,
        pe_inst=pe_inst,
        ce_est_prem=100.0,
        pe_est_prem=100.0,
    )

    # 1. State must be SAFE_HALT
    assert trade.state == StrategyState.SAFE_HALT
    # 2. Kill switch engaged
    assert engine.risk_manager.is_kill_switch_active is True
    # 3. Both positions flattened on exchange
    positions = await mock_exchange.get_positions()
    for p in positions:
        assert p.size == 0.0

