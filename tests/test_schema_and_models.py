"""Tests for PostgreSQL Schema Migration, SQLAlchemy Models, Relationships, Constraints, and Decimal Handling."""

import pytest
import pytest_asyncio
from datetime import datetime, date, timezone
from decimal import Decimal
from sqlalchemy import text, select
from sqlalchemy.exc import IntegrityError

from src.persistence.db import DatabaseManager
from src.persistence.models import (
    TradeModel,
    TradeLegModel,
    OrderModel,
    FillModel,
)


@pytest_asyncio.fixture
async def db_manager(test_settings):
    """Fixture providing connected DatabaseManager with clean tables."""
    db_mgr = DatabaseManager(settings=test_settings)
    connected = await db_mgr.connect()
    assert connected is True

    # Run migrations
    await db_mgr.run_migrations(migrations_dir="migrations")

    # Clean test data before test
    async with db_mgr.get_session() as session:
        await session.execute(text("TRUNCATE TABLE fills, orders, trade_legs, trades CASCADE;"))
        await session.commit()

    yield db_mgr

    # Cleanup after test
    async with db_mgr.get_session() as session:
        await session.execute(text("TRUNCATE TABLE fills, orders, trade_legs, trades CASCADE;"))
        await session.commit()

    await db_mgr.disconnect()



@pytest.mark.asyncio
async def test_run_migrations_idempotency(db_manager):
    """Verify migrations run cleanly and subsequent runs are no-ops."""
    applied_second_run = await db_manager.run_migrations(migrations_dir="migrations")
    assert applied_second_run == []

    # Verify all expected tables exist
    async with db_manager.get_session() as session:
        res = await session.execute(text("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name;
        """))
        tables = {row[0] for row in res.fetchall()}
        assert "trades" in tables
        assert "trade_legs" in tables
        assert "orders" in tables
        assert "fills" in tables
        assert "schema_migrations" in tables


@pytest.mark.asyncio
async def test_insert_and_query_synthetic_trade_hierarchy(db_manager):
    """Verify inserting and querying a complete multi-leg trade hierarchy with ORM models and Decimals."""
    now = datetime.now(timezone.utc)
    today = date(2026, 9, 1)

    # 1. Create Trade with JSONB strategy config
    trade = TradeModel(
        trade_id="STRANGLE_20260901_090000",
        strategy_name="short_strangle",
        exchange="delta_india",
        trade_date=today,
        status="ACTIVE",
        entry_time=now,
        total_entry_premium=Decimal("200.5000"),
        total_exit_premium=Decimal("0.0000"),
        realized_pnl=Decimal("0.0000"),
        total_fees=Decimal("0.1500"),
        net_pnl=Decimal("-0.1500"),
        strategy_config={
            "quantity": 10,
            "target_premium": 100.0,
            "tolerance_usd": 30.0,
            "sl_percentage": 1.0,
        },
    )

    # 2. Create CE and PE Legs
    ce_leg = TradeLegModel(
        leg_id="STRANGLE_20260901_090000_CE",
        trade_id=trade.trade_id,
        leg_type="CE",
        symbol="C-BTC-98000-010926",
        product_id="150401",
        strike=Decimal("98000.00"),
        quantity=Decimal("10.0000"),
        side="sell",
        entry_price=Decimal("100.2500"),
        entry_time=now,
        stop_loss_price=Decimal("200.5000"),
        bracket_order_id="BRK_CE_991",
        realized_pnl=Decimal("0.0000"),
        fees=Decimal("0.0750"),
        status="OPEN",
    )

    pe_leg = TradeLegModel(
        leg_id="STRANGLE_20260901_090000_PE",
        trade_id=trade.trade_id,
        leg_type="PE",
        symbol="P-BTC-92000-010926",
        product_id="150402",
        strike=Decimal("92000.00"),
        quantity=Decimal("10.0000"),
        side="sell",
        entry_price=Decimal("100.2500"),
        entry_time=now,
        stop_loss_price=Decimal("200.5000"),
        bracket_order_id="BRK_PE_992",
        realized_pnl=Decimal("0.0000"),
        fees=Decimal("0.0750"),
        status="OPEN",
    )

    # 3. Create Entry Orders & Fills
    ce_order = OrderModel(
        order_id="ORD_CE_ENTRY_1",
        trade_id=trade.trade_id,
        trade_leg_id=ce_leg.leg_id,
        exchange="delta_india",
        exchange_order_id="EX_ORD_1001",
        client_order_id="cid_ce_entry_1",
        symbol=ce_leg.symbol,
        product_id=ce_leg.product_id,
        side="sell",
        order_type="market_order",
        quantity=Decimal("10.0000"),
        filled_quantity=Decimal("10.0000"),
        average_fill_price=Decimal("100.2500"),
        status="filled",
        reduce_only=False,
    )

    ce_fill = FillModel(
        fill_id="FILL_CE_1",
        order_id=ce_order.order_id,
        exchange_fill_id="EX_FILL_5001",
        quantity=Decimal("10.0000"),
        price=Decimal("100.2500"),
        fee=Decimal("0.0750"),
        fee_currency="USD",
        fill_time=now,
    )
    ce_order.fills.append(ce_fill)

    trade.legs.extend([ce_leg, pe_leg])
    trade.orders.append(ce_order)

    # Persist in session
    async with db_manager.get_session() as session:
        session.add(trade)
        await session.commit()

    # Query back and verify relationships and Decimal precision
    async with db_manager.get_session() as session:
        stmt = (
            select(TradeModel)
            .where(TradeModel.trade_id == "STRANGLE_20260901_090000")
        )
        res = await session.execute(stmt)
        queried_trade = res.scalar_one()

        assert queried_trade.trade_id == "STRANGLE_20260901_090000"
        assert queried_trade.strategy_name == "short_strangle"
        assert queried_trade.total_entry_premium == Decimal("200.5000")
        assert queried_trade.strategy_config["target_premium"] == 100.0

        # Query legs
        stmt_legs = select(TradeLegModel).where(TradeLegModel.trade_id == queried_trade.trade_id).order_by(TradeLegModel.leg_type)
        legs_res = await session.execute(stmt_legs)
        legs = legs_res.scalars().all()
        assert len(legs) == 2
        assert legs[0].leg_type == "CE"
        assert legs[0].strike == Decimal("98000.00")
        assert legs[0].entry_price == Decimal("100.2500")
        assert legs[1].leg_type == "PE"
        assert legs[1].strike == Decimal("92000.00")

        # Query orders and fills
        stmt_orders = select(OrderModel).where(OrderModel.trade_id == queried_trade.trade_id)
        orders_res = await session.execute(stmt_orders)
        orders = orders_res.scalars().all()
        assert len(orders) == 1
        assert orders[0].client_order_id == "cid_ce_entry_1"
        assert orders[0].filled_quantity == Decimal("10.0000")

        stmt_fills = select(FillModel).where(FillModel.order_id == orders[0].order_id)
        fills_res = await session.execute(stmt_fills)
        fills = fills_res.scalars().all()
        assert len(fills) == 1
        assert fills[0].exchange_fill_id == "EX_FILL_5001"
        assert fills[0].fee == Decimal("0.0750")


@pytest.mark.asyncio
async def test_unique_constraint_client_order_id(db_manager):
    """Verify unique constraint on orders(client_order_id) prevents duplicate orders."""
    order1 = OrderModel(
        order_id="ORD_1",
        exchange="delta_india",
        client_order_id="duplicate_cid_123",
        symbol="C-BTC-98000-010926",
        product_id="150401",
        side="sell",
        order_type="market_order",
        quantity=Decimal("1.0000"),
        status="filled",
    )
    order2 = OrderModel(
        order_id="ORD_2",
        exchange="delta_india",
        client_order_id="duplicate_cid_123",
        symbol="C-BTC-98000-010926",
        product_id="150401",
        side="sell",
        order_type="market_order",
        quantity=Decimal("1.0000"),
        status="filled",
    )

    async with db_manager.get_session() as session:
        session.add(order1)
        await session.commit()

    with pytest.raises(IntegrityError):
        async with db_manager.get_session() as session:
            session.add(order2)
            await session.commit()


@pytest.mark.asyncio
async def test_unique_constraint_exchange_order_id(db_manager):
    """Verify unique constraint on orders(exchange, exchange_order_id) prevents duplicate exchange orders."""
    order1 = OrderModel(
        order_id="ORD_10",
        exchange="delta_india",
        exchange_order_id="EX_DUPLICATE_999",
        symbol="C-BTC-98000-010926",
        product_id="150401",
        side="sell",
        order_type="market_order",
        quantity=Decimal("1.0000"),
        status="filled",
    )
    order2 = OrderModel(
        order_id="ORD_20",
        exchange="delta_india",
        exchange_order_id="EX_DUPLICATE_999",
        symbol="C-BTC-98000-010926",
        product_id="150401",
        side="sell",
        order_type="market_order",
        quantity=Decimal("1.0000"),
        status="filled",
    )

    async with db_manager.get_session() as session:
        session.add(order1)
        await session.commit()

    with pytest.raises(IntegrityError):
        async with db_manager.get_session() as session:
            session.add(order2)
            await session.commit()


@pytest.mark.asyncio
async def test_unique_constraint_exchange_fill_id(db_manager):
    """Verify unique constraint on fills(exchange_fill_id) prevents duplicate fill records."""
    order = OrderModel(
        order_id="ORD_FILL_PARENT",
        exchange="delta_india",
        symbol="C-BTC-98000-010926",
        product_id="150401",
        side="sell",
        order_type="market_order",
        quantity=Decimal("1.0000"),
        status="filled",
    )
    fill1 = FillModel(
        fill_id="FILL_100",
        order_id=order.order_id,
        exchange_fill_id="EX_FILL_DUP_777",
        quantity=Decimal("1.0000"),
        price=Decimal("100.0000"),
    )
    fill2 = FillModel(
        fill_id="FILL_200",
        order_id=order.order_id,
        exchange_fill_id="EX_FILL_DUP_777",
        quantity=Decimal("1.0000"),
        price=Decimal("100.0000"),
    )

    async with db_manager.get_session() as session:
        session.add(order)
        session.add(fill1)
        await session.commit()

    with pytest.raises(IntegrityError):
        async with db_manager.get_session() as session:
            session.add(fill2)
            await session.commit()


@pytest.mark.asyncio
async def test_cascade_delete_trade(db_manager):
    """Verify deleting a trade cascades to trade_legs and sets trade_id to NULL on orders."""
    trade = TradeModel(
        trade_id="STRANGLE_CASCADE_TEST",
        strategy_name="short_strangle",
        exchange="delta_india",
        trade_date=date(2026, 9, 1),
        status="COMPLETED",
    )
    leg = TradeLegModel(
        leg_id="LEG_CASCADE_TEST",
        trade_id=trade.trade_id,
        leg_type="CE",
        symbol="C-BTC-98000-010926",
        product_id="150401",
        strike=Decimal("98000.00"),
        quantity=Decimal("1.0000"),
        status="FORCE_CLOSED",
    )
    order = OrderModel(
        order_id="ORD_CASCADE_TEST",
        trade_id=trade.trade_id,
        trade_leg_id=leg.leg_id,
        exchange="delta_india",
        symbol="C-BTC-98000-010926",
        product_id="150401",
        side="sell",
        order_type="market_order",
        quantity=Decimal("1.0000"),
        status="filled",
    )

    async with db_manager.get_session() as session:
        session.add_all([trade, leg, order])
        await session.commit()

    # Delete Trade
    async with db_manager.get_session() as session:
        stmt = select(TradeModel).where(TradeModel.trade_id == "STRANGLE_CASCADE_TEST")
        res = await session.execute(stmt)
        t = res.scalar_one()
        await session.delete(t)
        await session.commit()

    # Verify leg was deleted (CASCADE)
    async with db_manager.get_session() as session:
        res_leg = await session.execute(select(TradeLegModel).where(TradeLegModel.leg_id == "LEG_CASCADE_TEST"))
        assert res_leg.scalar_one_or_none() is None

        # Verify order still exists but trade_id and trade_leg_id are SET NULL
        res_ord = await session.execute(select(OrderModel).where(OrderModel.order_id == "ORD_CASCADE_TEST"))
        ord_obj = res_ord.scalar_one()
        assert ord_obj.trade_id is None
        assert ord_obj.trade_leg_id is None
