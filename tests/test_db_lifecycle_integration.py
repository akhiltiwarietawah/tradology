"""Integration tests for Database lifecycle hooks, PostgreSQL failure isolation, and restart recovery."""

import pytest
from datetime import datetime, date, timezone
from decimal import Decimal
from sqlalchemy import select

from src.engine import TradingEngine
from src.config.settings import Settings
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.models.order import Order, Fill, OrderSide, OrderType, OrderState
from src.core.models.instrument import Instrument, InstrumentType, OptionType
from src.persistence.db import DatabaseManager
from src.persistence.trade_repository import TradeRepository
from src.persistence.models import TradeModel, TradeLegModel, OrderModel, FillModel


@pytest.mark.asyncio
async def test_engine_safe_db_persist_entry(clean_db, test_settings):
    """Verify TradingEngine._safe_db_persist_entry writes complete trade hierarchy."""
    engine = TradingEngine(settings=test_settings)
    await engine.db_manager.connect()

    now_iso = datetime.now(timezone.utc).isoformat()
    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_INTEG_001",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_INTEG_001_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            sl_price=200.0,
            bracket_order_id="BRK_CE_001",
            fees=0.075,
            status=LegStatus.OPEN,
        ),
        pe_leg=StrategyLeg(
            leg_id="STRANGLE_INTEG_001_PE",
            option_type=OptionType.PUT,
            instrument_id="150402",
            symbol="P-BTC-92000-010926",
            strike=92000.0,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            sl_price=200.0,
            bracket_order_id="BRK_PE_001",
            fees=0.075,
            status=LegStatus.OPEN,
        ),
    )

    ce_order = Order(
        order_id="ORD_CE_001",
        client_order_id="cid_ce_001",
        instrument_id="150401",
        symbol="C-BTC-98000-010926",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=10.0,
        filled_quantity=10.0,
        average_fill_price=100.0,
        state=OrderState.FILLED,
    )

    pe_order = Order(
        order_id="ORD_PE_001",
        client_order_id="cid_pe_001",
        instrument_id="150402",
        symbol="P-BTC-92000-010926",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=10.0,
        filled_quantity=10.0,
        average_fill_price=100.0,
        state=OrderState.FILLED,
    )

    await engine._safe_db_persist_entry(trade, ce_order, pe_order)

    # Verify DB record
    async with clean_db.get_session() as session:
        t_res = await session.execute(select(TradeModel).where(TradeModel.trade_id == "STRANGLE_INTEG_001"))
        t = t_res.scalar_one()
        assert t.status == "ACTIVE"
        assert t.total_fees == Decimal("0.1500")

        l_res = await session.execute(select(TradeLegModel).where(TradeLegModel.trade_id == "STRANGLE_INTEG_001"))
        legs = l_res.scalars().all()
        assert len(legs) == 2

    await engine.db_manager.disconnect()


@pytest.mark.asyncio
async def test_engine_safe_db_persist_sl_exit(clean_db, test_settings):
    """Verify TradingEngine._safe_db_persist_leg_exit updates leg and parent trade."""
    engine = TradingEngine(settings=test_settings)
    await engine.db_manager.connect()

    now_iso = datetime.now(timezone.utc).isoformat()
    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_INTEG_SL",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_INTEG_SL_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            sl_price=200.0,
            status=LegStatus.OPEN,
        ),
        pe_leg=StrategyLeg(
            leg_id="STRANGLE_INTEG_SL_PE",
            option_type=OptionType.PUT,
            instrument_id="150402",
            symbol="P-BTC-92000-010926",
            strike=92000.0,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            sl_price=200.0,
            status=LegStatus.OPEN,
        ),
    )

    await engine._safe_db_persist_entry(trade)

    # Trigger SL on CE
    ce_leg = trade.ce_leg
    ce_leg.status = LegStatus.STOPPED_OUT
    ce_leg.exit_price = 202.0
    ce_leg.exit_timestamp = now_iso
    ce_leg.exit_reason = "STOP_LOSS"
    ce_leg.realized_pnl = -1.02  # (100 - 202) * 10 * 0.001
    trade.update_pnl()

    exit_order = Order(
        order_id="ORD_SL_EXIT_CE",
        client_order_id="cid_sl_exit_ce",
        instrument_id="150401",
        symbol="C-BTC-98000-010926",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10.0,
        filled_quantity=10.0,
        average_fill_price=202.0,
        state=OrderState.FILLED,
        reduce_only=True,
    )

    engine.strategy.current_trade = trade
    await engine._safe_db_persist_leg_exit(ce_leg, exit_order)

    # Verify CE leg is updated and PE leg remains OPEN
    async with clean_db.get_session() as session:
        ce_db = (await session.execute(select(TradeLegModel).where(TradeLegModel.leg_id == "STRANGLE_INTEG_SL_CE"))).scalar_one()
        pe_db = (await session.execute(select(TradeLegModel).where(TradeLegModel.leg_id == "STRANGLE_INTEG_SL_PE"))).scalar_one()
        assert ce_db.status == "STOPPED_OUT"
        assert ce_db.exit_price == Decimal("202.0000")
        assert pe_db.status == "OPEN"

    await engine.db_manager.disconnect()


@pytest.mark.asyncio
async def test_engine_safe_db_persist_eod_completion(clean_db, test_settings):
    """Verify TradingEngine._safe_db_persist_trade_completion finalizes trade as COMPLETED."""
    engine = TradingEngine(settings=test_settings)
    await engine.db_manager.connect()

    now_iso = datetime.now(timezone.utc).isoformat()
    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_INTEG_EOD",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_INTEG_EOD_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            status=LegStatus.OPEN,
        ),
        pe_leg=StrategyLeg(
            leg_id="STRANGLE_INTEG_EOD_PE",
            option_type=OptionType.PUT,
            instrument_id="150402",
            symbol="P-BTC-92000-010926",
            strike=92000.0,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            status=LegStatus.OPEN,
        ),
    )

    await engine._safe_db_persist_entry(trade)

    # Simulate 17:15 square off
    trade.ce_leg.status = LegStatus.FORCE_CLOSED
    trade.ce_leg.exit_price = 10.0
    trade.ce_leg.exit_reason = "EOD_EXIT"
    trade.ce_leg.realized_pnl = 0.90  # (100 - 10) * 10 * 0.001

    trade.pe_leg.status = LegStatus.FORCE_CLOSED
    trade.pe_leg.exit_price = 5.0
    trade.pe_leg.exit_reason = "EOD_EXIT"
    trade.pe_leg.realized_pnl = 0.95  # (100 - 5) * 10 * 0.001

    trade.state = StrategyState.COMPLETED
    trade.update_pnl()

    await engine._safe_db_persist_trade_completion(trade)

    async with clean_db.get_session() as session:
        t_db = (await session.execute(select(TradeModel).where(TradeModel.trade_id == "STRANGLE_INTEG_EOD"))).scalar_one()
        assert t_db.status == "COMPLETED"
        assert t_db.realized_pnl == Decimal("1.8500")

    await engine.db_manager.disconnect()


@pytest.mark.asyncio
async def test_engine_db_failure_isolation_does_not_block_trading(test_settings):
    """Verify that when PostgreSQL is unavailable or fails, TradingEngine continues operating normally."""
    offline_settings = test_settings.model_copy(
        update={
            "postgres_host": "127.0.0.1",
            "postgres_port": 59998,  # Non-existent DB port
            "db_timeout_seconds": 0.5,
        }
    )
    engine = TradingEngine(settings=offline_settings)

    # Attempt to start with offline DB
    await engine.start()
    assert engine.db_manager.is_connected is False

    # Perform entry persistence call -> must return without raising
    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_OFFLINE_TEST",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
    )
    await engine._safe_db_persist_entry(trade)
    await engine._safe_db_persist_trade_completion(trade)

    # Engine status reflects DB status without breaking
    status = engine.get_status()
    assert status["database"]["status"] == "UNAVAILABLE"
    assert status["database"]["connected"] is False

    await engine.stop()


@pytest.mark.asyncio
async def test_reconciliation_syncs_discovered_bracket_to_db(clean_db, test_settings):
    """Verify state reconciliation discovers active bracket and persists bracket_order_id to DB."""
    engine = TradingEngine(settings=test_settings)
    await engine.db_manager.connect()

    now_iso = datetime.now(timezone.utc).isoformat()
    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_BRK_SYNC",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_BRK_SYNC_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            sl_price=200.0,
            bracket_order_id=None,
            status=LegStatus.OPEN,
        ),
    )

    engine.strategy.current_trade = trade
    await engine._safe_db_persist_entry(trade)

    # Simulate reconciler discovering bracket
    trade.ce_leg.bracket_order_id = "BRK_EXCHANGE_12345"
    trade.ce_leg.exchange_sl_active = True
    await engine._safe_db_persist_reconciliation_update(trade)

    async with clean_db.get_session() as session:
        ce_db = (await session.execute(select(TradeLegModel).where(TradeLegModel.leg_id == "STRANGLE_BRK_SYNC_CE"))).scalar_one()
        assert ce_db.bracket_order_id == "BRK_EXCHANGE_12345"

    await engine.db_manager.disconnect()


@pytest.mark.asyncio
async def test_manual_close_syncs_to_db_without_duplicating_trades(clean_db, test_settings):
    """Verify manual closing of a leg updates DB leg status to MANUALLY_CLOSED without creating new trade rows."""
    engine = TradingEngine(settings=test_settings)
    await engine.db_manager.connect()

    now_iso = datetime.now(timezone.utc).isoformat()
    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_MANUAL_CLOSE_DB",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_MANUAL_CLOSE_DB_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            sl_price=200.0,
            status=LegStatus.OPEN,
        ),
    )

    engine.strategy.current_trade = trade
    await engine._safe_db_persist_entry(trade)

    # Reconciler marks leg manually closed
    trade.ce_leg.status = LegStatus.MANUALLY_CLOSED
    trade.ce_leg.exit_reason = "MANUAL_CLOSE"
    trade.ce_leg.exit_price = 90.0
    trade.ce_leg.exit_timestamp = now_iso
    trade.ce_leg.realized_pnl = 0.10  # (100 - 90) * 10 * 0.001
    trade.update_pnl()

    await engine._safe_db_persist_reconciliation_update(trade)

    async with clean_db.get_session() as session:
        t_rows = (await session.execute(select(TradeModel).where(TradeModel.trade_id == "STRANGLE_MANUAL_CLOSE_DB"))).scalars().all()
        assert len(t_rows) == 1
        assert t_rows[0].exit_reason == "MANUAL_CLOSE"

        ce_db = (await session.execute(select(TradeLegModel).where(TradeLegModel.leg_id == "STRANGLE_MANUAL_CLOSE_DB_CE"))).scalar_one()
        assert ce_db.status == "MANUALLY_CLOSED"

    await engine.db_manager.disconnect()


