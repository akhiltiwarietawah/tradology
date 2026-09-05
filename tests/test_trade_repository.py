"""Unit tests for TradeRepository operations, idempotency, multi-fill handling, and Decimal precision."""

import pytest
import pytest_asyncio
from datetime import datetime, date, timezone
from decimal import Decimal
from sqlalchemy import text, select

from src.persistence.db import DatabaseManager
from src.persistence.trade_repository import TradeRepository
from src.persistence.models import TradeModel, TradeLegModel, OrderModel, FillModel
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.models.order import Order, Fill, OrderSide, OrderType, OrderState
from src.core.models.instrument import OptionType


@pytest_asyncio.fixture
async def repo_and_db(test_settings):
    """Fixture providing DatabaseManager and TradeRepository with clean tables."""
    db_mgr = DatabaseManager(settings=test_settings)
    connected = await db_mgr.connect()
    assert connected is True

    await db_mgr.run_migrations(migrations_dir="migrations")

    async with db_mgr.get_session() as session:
        await session.execute(text("TRUNCATE TABLE fills, orders, trade_legs, trades CASCADE;"))
        await session.commit()

    repo = TradeRepository(db_manager=db_mgr)
    yield repo, db_mgr

    async with db_mgr.get_session() as session:
        await session.execute(text("TRUNCATE TABLE fills, orders, trade_legs, trades CASCADE;"))
        await session.commit()

    await db_mgr.disconnect()


@pytest.mark.asyncio
async def test_trade_repository_entry_and_query(repo_and_db):
    """Verify record_entry persists trade, legs, orders, and fills accurately."""
    repo, db_mgr = repo_and_db
    now_iso = datetime.now(timezone.utc).isoformat()

    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_20260901_090000",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_20260901_090000_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_order_id="ORD_CE_101",
            entry_client_order_id="cid_ce_entry_101",
            entry_fill_price=102.50,
            sl_price=205.00,
            bracket_order_id="BRK_CE_101",
            exchange_sl_active=True,
            fees=0.075,
            status=LegStatus.OPEN,
        ),
        pe_leg=StrategyLeg(
            leg_id="STRANGLE_20260901_090000_PE",
            option_type=OptionType.PUT,
            instrument_id="150402",
            symbol="P-BTC-92000-010926",
            strike=92000.0,
            expiry_date="2026-09-01",
            quantity=10.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_order_id="ORD_PE_102",
            entry_client_order_id="cid_pe_entry_102",
            entry_fill_price=98.50,
            sl_price=197.00,
            bracket_order_id="BRK_PE_102",
            exchange_sl_active=True,
            fees=0.075,
            status=LegStatus.OPEN,
        ),
    )

    ce_order = Order(
        order_id="ORD_CE_101",
        client_order_id="cid_ce_entry_101",
        instrument_id="150401",
        symbol="C-BTC-98000-010926",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=10.0,
        filled_quantity=10.0,
        average_fill_price=102.50,
        state=OrderState.FILLED,
        strategy_id=trade.strategy_trade_id,
        leg_id=trade.ce_leg.leg_id,
    )

    pe_order = Order(
        order_id="ORD_PE_102",
        client_order_id="cid_pe_entry_102",
        instrument_id="150402",
        symbol="P-BTC-92000-010926",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=10.0,
        filled_quantity=10.0,
        average_fill_price=98.50,
        state=OrderState.FILLED,
        strategy_id=trade.strategy_trade_id,
        leg_id=trade.pe_leg.leg_id,
    )

    config_snapshot = {
        "quantity": 10,
        "target_premium": 100.0,
        "tolerance_usd": 30.0,
        "sl_percentage": 1.0,
    }

    await repo.record_entry(
        trade=trade,
        ce_order=ce_order,
        pe_order=pe_order,
        config_snapshot=config_snapshot,
    )

    # Verify query
    queried = await repo.get_trade("STRANGLE_20260901_090000")
    assert queried is not None
    assert queried.strategy_name == "short_strangle"
    assert queried.status == "ACTIVE"
    assert queried.total_entry_premium == Decimal("2.0100")  # (102.50 * 10 * 0.001) + (98.50 * 10 * 0.001) = 1.025 + 0.985 = 2.0100
    assert queried.total_fees == Decimal("0.1500")
    assert queried.strategy_config["target_premium"] == 100.0


@pytest.mark.asyncio
async def test_trade_repository_multi_fill_persistence(repo_and_db):
    """Verify that multiple execution fills for a single order are stored individually."""
    repo, db_mgr = repo_and_db
    now_iso = datetime.now(timezone.utc).isoformat()

    order = Order(
        order_id="ORD_MULTI_FILL_1",
        client_order_id="cid_multi_1",
        instrument_id="150401",
        symbol="C-BTC-98000-010926",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=10.0,
        filled_quantity=10.0,
        average_fill_price=101.0,
        state=OrderState.FILLED,
    )

    await repo.upsert_order(order)

    # Add 2 separate fills for the same order
    fill1 = Fill(
        fill_id="FILL_EX_1",
        order_id="ORD_MULTI_FILL_1",
        client_order_id="cid_multi_1",
        instrument_id="150401",
        symbol="C-BTC-98000-010926",
        side=OrderSide.SELL,
        quantity=6.0,
        price=100.0,
        fee=0.045,
        fee_asset="USD",
        timestamp=now_iso,
    )

    fill2 = Fill(
        fill_id="FILL_EX_2",
        order_id="ORD_MULTI_FILL_1",
        client_order_id="cid_multi_1",
        instrument_id="150401",
        symbol="C-BTC-98000-010926",
        side=OrderSide.SELL,
        quantity=4.0,
        price=102.5,
        fee=0.030,
        fee_asset="USD",
        timestamp=now_iso,
    )

    await repo.upsert_fill(fill1, order_id="ORD_MULTI_FILL_1")
    await repo.upsert_fill(fill2, order_id="ORD_MULTI_FILL_1")

    # Verify both fills exist
    async with db_mgr.get_session() as session:
        stmt = select(FillModel).where(FillModel.order_id == "ORD_MULTI_FILL_1").order_by(FillModel.quantity.desc())
        res = await session.execute(stmt)
        fills = res.scalars().all()
        assert len(fills) == 2
        assert fills[0].quantity == Decimal("6.0000")
        assert fills[0].price == Decimal("100.0000")
        assert fills[1].quantity == Decimal("4.0000")
        assert fills[1].price == Decimal("102.5000")


@pytest.mark.asyncio
async def test_trade_repository_idempotency_on_repeated_reconciliation(repo_and_db):
    """Verify that repeated upserts with updated data do not fail or duplicate rows."""
    repo, db_mgr = repo_and_db
    now_iso = datetime.now(timezone.utc).isoformat()

    trade = StrategyTrade(
        strategy_trade_id="STRANGLE_IDEMPOTENT_TEST",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_IDEMPOTENT_TEST_CE",
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

    # 1st Upsert
    await repo.upsert_trade(trade)
    await repo.upsert_leg(trade.ce_leg, trade_id=trade.strategy_trade_id)

    # 2nd Upsert (Simulate bracket ID discovered during reconciliation)
    trade.ce_leg.bracket_order_id = "BRK_DISCOVERED_123"
    trade.ce_leg.exchange_sl_active = True
    await repo.upsert_trade(trade)
    await repo.upsert_leg(trade.ce_leg, trade_id=trade.strategy_trade_id)

    # 3rd Upsert (Simulate SL triggered)
    trade.ce_leg.status = LegStatus.STOPPED_OUT
    trade.ce_leg.exit_price = 205.0
    trade.ce_leg.exit_timestamp = now_iso
    trade.ce_leg.exit_reason = "STOP_LOSS"
    trade.ce_leg.realized_pnl = -1.05  # (100 - 205) * 10 * 0.001
    trade.update_pnl()
    await repo.record_leg_exit(trade.ce_leg, trade_id=trade.strategy_trade_id, parent_trade=trade)

    # Verify only 1 trade row and 1 leg row exist
    async with db_mgr.get_session() as session:
        t_res = await session.execute(select(TradeModel).where(TradeModel.trade_id == "STRANGLE_IDEMPOTENT_TEST"))
        trades = t_res.scalars().all()
        assert len(trades) == 1
        assert trades[0].realized_pnl == Decimal("-1.0500")
        assert trades[0].exit_reason == "STOP_LOSS"

        l_res = await session.execute(select(TradeLegModel).where(TradeLegModel.leg_id == "STRANGLE_IDEMPOTENT_TEST_CE"))
        legs = l_res.scalars().all()
        assert len(legs) == 1
        assert legs[0].bracket_order_id == "BRK_DISCOVERED_123"
        assert legs[0].status == "STOPPED_OUT"
        assert legs[0].exit_price == Decimal("205.0000")
