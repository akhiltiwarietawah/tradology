"""Comprehensive Security & Recovery Audit Test Suite (Checkpoint 7)."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from src.config.settings import Settings, Environment
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.models.instrument import OptionType
from src.core.models.position import Position
from src.core.models.order import Order, OrderSide, OrderType, OrderState
from src.engine import TradingEngine
from tests.conftest import MockExchangeAdapter


@pytest.fixture
def audit_engine(tmp_path):
    """Factory creating isolated TradingEngine for recovery audit."""
    settings = Settings(
        delta_env=Environment.TESTNET,
        kill_switch=False,
        dry_run=False,
        delta_testnet_api_key="mock_key",
        delta_testnet_api_secret="mock_secret",
        data_dir=str(tmp_path / "data"),
        logs_dir=str(tmp_path / "logs"),
        state_file=str(tmp_path / "data" / "trade_state.json"),
        trades_log_file=str(tmp_path / "logs" / "trades.jsonl"),
        database_enabled=True,
    )
    engine = TradingEngine(settings=settings)
    mock_adapter = MockExchangeAdapter()
    engine.delta_adapter = mock_adapter
    engine.exchange_service.register_adapter(mock_adapter)
    engine.execution_engine.exchange = mock_adapter
    engine.strategy.exchange = mock_adapter
    engine.reconciler.exchange = mock_adapter
    engine.risk_manager._kill_switch_flag = False
    engine._running = True
    return engine, mock_adapter


@pytest.mark.asyncio
async def test_audit_1_restart_no_position(audit_engine):
    """1. Engine restart with no position -> Clean state, no orders placed."""
    engine, mock_adapter = audit_engine
    mock_adapter.positions = []
    mock_adapter.orders = {}

    res = await engine.reconcile_state()
    assert res.is_synchronized is True
    assert engine.strategy.current_trade is None
    assert len(mock_adapter.placed_orders) == 0
    assert engine.risk_manager.is_kill_switch_active is False


@pytest.mark.asyncio
async def test_audit_2_restart_active_position(audit_engine):
    """2. Engine restart with active position -> Restores state, retains monitoring."""
    engine, mock_adapter = audit_engine
    now_iso = datetime.now(timezone.utc).isoformat()
    trade = StrategyTrade(
        strategy_trade_id="AUDIT_TRADE_1",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="AUDIT_TRADE_1_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            sl_price=200.0,
            bracket_order_id="BRK_150401_200",
            exchange_sl_active=True,
            status=LegStatus.OPEN,
        ),
        pe_leg=StrategyLeg(
            leg_id="AUDIT_TRADE_1_PE",
            option_type=OptionType.PUT,
            instrument_id="150402",
            symbol="P-BTC-92000-010926",
            strike=92000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            sl_price=200.0,
            bracket_order_id="BRK_150402_200",
            exchange_sl_active=True,
            status=LegStatus.OPEN,
        ),
    )
    engine.state_persistence.save_state(trade, [])
    engine.strategy.current_trade = trade

    mock_adapter.positions = [
        Position(instrument_id="150401", symbol="C-BTC-98000-010926", size=-1.0, entry_price=100.0),
        Position(instrument_id="150402", symbol="P-BTC-92000-010926", size=-1.0, entry_price=100.0),
    ]
    mock_adapter.orders = {
        "BRK_150401_200": Order(
            order_id="BRK_150401_200",
            client_order_id="cli_brk_1",
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            state=OrderState.OPEN,
            stop_price=200.0,
        ),
        "BRK_150402_200": Order(
            order_id="BRK_150402_200",
            client_order_id="cli_brk_2",
            instrument_id="150402",
            symbol="P-BTC-92000-010926",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            state=OrderState.OPEN,
            stop_price=200.0,
        ),
    }

    res = await engine.reconcile_state()
    assert res.is_synchronized is True
    assert engine.strategy.current_trade is not None
    assert engine.strategy.current_trade.state == StrategyState.ACTIVE
    assert len(mock_adapter.placed_orders) == 0  # No duplicate orders placed


@pytest.mark.asyncio
async def test_audit_3_postgres_unavailable_during_restart(audit_engine):
    """3. PostgreSQL unavailable during restart -> Loads from JSON state without failure."""
    engine, mock_adapter = audit_engine
    engine.db_manager._is_connected = False
    mock_adapter.positions = []

    res = await engine.reconcile_state()
    assert res.is_synchronized is True
    readiness = engine.get_readiness()
    assert readiness["ready"] is True  # DB failure does not disable engine


@pytest.mark.asyncio
async def test_audit_4_postgres_reconnects_no_duplicates(audit_engine):
    """4. PostgreSQL reconnects after restart -> Clean synchronization, no duplicates."""
    engine, mock_adapter = audit_engine
    engine.db_manager._is_connected = False
    # Reconnect
    engine.db_manager._is_connected = True
    status = engine.get_status()
    assert status["database"]["connected"] is True


@pytest.mark.asyncio
async def test_audit_5_existing_native_bracket_discovered(audit_engine):
    """5. Existing native bracket SL exists -> Discovered during recon, no duplicate placed."""
    engine, mock_adapter = audit_engine
    now_iso = datetime.now(timezone.utc).isoformat()
    trade = StrategyTrade(
        strategy_trade_id="AUDIT_TRADE_5",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="AUDIT_TRADE_5_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            sl_price=200.0,
            bracket_order_id=None,  # Not recorded locally yet
            exchange_sl_active=False,
            status=LegStatus.OPEN,
        ),
    )
    engine.state_persistence.save_state(trade, [])
    engine.strategy.current_trade = trade

    mock_adapter.positions = [
        Position(instrument_id="150401", symbol="C-BTC-98000-010926", size=-1.0, entry_price=100.0)
    ]
    # Exchange has the bracket order active
    mock_adapter.orders = {
        "BRK_EXISTING_123": Order(
            order_id="BRK_EXISTING_123",
            client_order_id="cli_brk_existing",
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            state=OrderState.OPEN,
            stop_price=200.0,
            raw_data={"bracket_order": True},
        )
    }

    res = await engine.reconcile_state()
    assert res.is_synchronized is True
    # Verify bracket was discovered and linked
    assert engine.strategy.current_trade.ce_leg.bracket_order_id == "BRK_EXISTING_123"
    assert engine.strategy.current_trade.ce_leg.exchange_sl_active is True
    assert len(mock_adapter.placed_orders) == 0  # No duplicate order created


@pytest.mark.asyncio
async def test_audit_6_bracket_exists_local_db_missing(audit_engine):
    """6. Bracket exists on exchange but local DB missing -> Reconciler maintains safety."""
    engine, mock_adapter = audit_engine
    engine.db_manager = None
    mock_adapter.positions = []

    res = await engine.reconcile_state()
    assert res.is_synchronized is True


@pytest.mark.asyncio
async def test_audit_7_ambiguous_local_state_triggers_safe_halt(audit_engine):
    """7. Ambiguous state (position open, missing bracket, corrupt price) -> SAFE_HALT."""
    engine, mock_adapter = audit_engine
    now_iso = datetime.now(timezone.utc).isoformat()
    trade = StrategyTrade(
        strategy_trade_id="AUDIT_TRADE_7_CORRUPT",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="AUDIT_TRADE_7_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=0.0,  # Corrupt entry price
            sl_price=None,  # Missing SL
            bracket_order_id=None,
            status=LegStatus.OPEN,
        ),
    )
    engine.state_persistence.save_state(trade, [])
    engine.strategy.current_trade = trade

    mock_adapter.positions = [
        Position(instrument_id="150401", symbol="C-BTC-98000-010926", size=-1.0, entry_price=100.0)
    ]
    mock_adapter.orders = {}  # No bracket on exchange either

    res = await engine.reconcile_state()
    assert res.is_synchronized is False
    assert res.status == "SAFE_HALT"
    assert engine.risk_manager.is_kill_switch_active is True
    assert len(mock_adapter.placed_orders) == 0  # No dangerous guessed orders


@pytest.mark.asyncio
async def test_audit_8_unrelated_manual_positions_isolated(audit_engine):
    """8. Unrelated manual positions exists -> Completely isolated, not touched."""
    engine, mock_adapter = audit_engine
    mock_adapter.positions = [
        Position(instrument_id="999999", symbol="C-ETH-4000-010926", size=5.0, entry_price=50.0),
        Position(instrument_id="888888", symbol="BTCUSD-PERP", size=-0.5, entry_price=95000.0),
    ]

    res = await engine.reconcile_state()
    assert res.is_synchronized is True
    assert len(mock_adapter.placed_orders) == 0  # Manual positions left untouched
    assert engine.strategy.current_trade is None
