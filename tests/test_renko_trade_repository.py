"""Tests for Renko Ichimoku PostgreSQL persistence."""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from src.persistence.models import TradeLegModel, OrderModel, FillModel
from src.persistence.renko_trade_repository import RenkoTradeRepository, make_renko_trade_id, RENKO_STRATEGY_NAME
from src.core.models.order import Order, OrderSide, OrderType, OrderState
from src.strategies.renko_ichimoku.renko import ConfirmedBrick


def _brick(index: int = 134, close: float = 2475.0) -> ConfirmedBrick:
    return ConfirmedBrick(
        index=index,
        timestamp=0.0,
        open=close - 15,
        close=close,
        high=close,
        low=close - 15,
        direction=1,
        source_bar_index=index,
    )


def _entry_order() -> Order:
    return Order(
        order_id="1530257400",
        client_order_id="RI134EL",
        instrument_id="3136",
        symbol="ETHUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=1.0,
        filled_quantity=1.0,
        average_fill_price=2477.35,
        state=OrderState.FILLED,
        strategy_id="renko_ichimoku",
    )


@pytest.mark.asyncio
async def test_renko_record_entry_and_exit(repo_and_db):
    _, db_mgr = repo_and_db
    repo = RenkoTradeRepository(db_mgr)
    trade_id = make_renko_trade_id(134)
    brick = _brick()
    entry = _entry_order()

    await repo.record_entry(
        trade_id=trade_id,
        order=entry,
        brick=brick,
        action_kind="enter_long",
        action_reason="long_entry",
        account_name="myalgo",
        symbol="ETHUSD",
        product_id="3136",
        quantity=1.0,
    )

    open_trade = await repo.get_open_trade()
    assert open_trade is not None
    assert open_trade.trade_id == trade_id
    assert open_trade.status == "ACTIVE"
    assert open_trade.strategy_name == RENKO_STRATEGY_NAME

    exit_order = Order(
        order_id="1530999999",
        client_order_id="RI140XL",
        instrument_id="3136",
        symbol="ETHUSD",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=1.0,
        filled_quantity=1.0,
        average_fill_price=2480.0,
        state=OrderState.FILLED,
        strategy_id="renko_ichimoku",
        reduce_only=True,
    )
    await repo.record_exit(
        trade_id=trade_id,
        order=exit_order,
        brick=_brick(index=140, close=2480.0),
        action_kind="exit_long",
        action_reason="long_exit_inside_cloud",
        entry_price=2477.35,
        entry_time=datetime.now(timezone.utc).timestamp(),
        quantity=1.0,
    )

    completed = await repo.get_trade(trade_id)
    assert completed is not None
    assert completed.status == "COMPLETED"
    assert completed.realized_pnl == Decimal("0.0265")  # (2480-2477.35)*1*0.01

    async with db_mgr.get_session() as session:
        legs = (await session.execute(select(TradeLegModel).where(TradeLegModel.trade_id == trade_id))).scalars().all()
        orders = (await session.execute(select(OrderModel).where(OrderModel.trade_id == trade_id))).scalars().all()
        fills = (
            await session.execute(
                select(FillModel).where(FillModel.order_id.in_([o.order_id for o in orders]))
            )
        ).scalars().all()
    assert len(legs) == 1
    assert legs[0].leg_type == "LONG"
    assert legs[0].strike is None
    assert len(orders) == 2
    assert len(fills) >= 2

    payload = await repo.trade_to_dict(completed)
    assert payload["legs"][0]["entry_price"] == 2477.35
    assert payload["exit_reason"] == "long_exit_inside_cloud"
