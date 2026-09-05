"""Asynchronous, idempotent repository for persisting trades, legs, orders, and fills to PostgreSQL."""

import logging
from decimal import Decimal
from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.persistence.db import DatabaseManager
from src.persistence.models import (
    TradeModel,
    TradeLegModel,
    OrderModel,
    FillModel,
)
from src.core.models.trade import StrategyTrade, StrategyLeg
from src.core.models.order import Order, Fill


def to_decimal(val: Any, default: Optional[str] = "0.0000", places: Optional[int] = None) -> Optional[Decimal]:
    """Safely convert numeric value to Decimal."""
    if val is None:
        return Decimal(default) if default is not None else None
    try:
        d = Decimal(str(val))
        if places is not None:
            return round(d, places)
        return d
    except Exception:
        return Decimal(default) if default is not None else None



def to_datetime(val: Any) -> Optional[datetime]:
    """Safely convert string or datetime to timezone-aware UTC datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    return None


class TradeRepository:
    """Provides idempotent database persistence for StrategyTrades, legs, orders, and execution fills."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        logger: Optional[logging.Logger] = None,
    ):
        self.db = db_manager
        self.logger = logger or logging.getLogger("trade_repository")

    async def upsert_trade(
        self,
        trade: StrategyTrade,
        config_snapshot: Optional[Dict[str, Any]] = None,
        exchange: Optional[str] = None,
    ) -> None:
        """Idempotently insert or update a Trade record."""
        trade_date_val = datetime.strptime(trade.trade_date, "%Y-%m-%d").date() if isinstance(trade.trade_date, str) else trade.trade_date
        entry_time_val = None
        exit_time_val = None

        if trade.ce_leg and trade.ce_leg.entry_timestamp:
            entry_time_val = to_datetime(trade.ce_leg.entry_timestamp)
        elif trade.pe_leg and trade.pe_leg.entry_timestamp:
            entry_time_val = to_datetime(trade.pe_leg.entry_timestamp)
        else:
            entry_time_val = to_datetime(trade.created_at)

        if not trade.has_any_open_leg and trade.state.value == "COMPLETED":
            if trade.ce_leg and trade.ce_leg.exit_timestamp:
                exit_time_val = to_datetime(trade.ce_leg.exit_timestamp)
            elif trade.pe_leg and trade.pe_leg.exit_timestamp:
                exit_time_val = to_datetime(trade.pe_leg.exit_timestamp)
            else:
                exit_time_val = to_datetime(trade.updated_at)

        # Compute fees and premiums
        total_entry_prem = Decimal("0.0000")
        total_exit_prem = Decimal("0.0000")
        total_fees = Decimal("0.0000")
        realized_pnl = Decimal("0.0000")
        exit_reasons = []

        for leg in (trade.ce_leg, trade.pe_leg):
            if leg:
                if leg.entry_fill_price is not None:
                    total_entry_prem += to_decimal(leg.entry_fill_price * leg.quantity * leg.contract_value)
                if leg.exit_price is not None:
                    total_exit_prem += to_decimal(leg.exit_price * leg.quantity * leg.contract_value)
                total_fees += to_decimal(leg.fees)
                realized_pnl += to_decimal(leg.realized_pnl)
                if leg.exit_reason and leg.exit_reason not in exit_reasons:
                    exit_reasons.append(leg.exit_reason)

        net_pnl = realized_pnl - total_fees
        exit_reason_str = ", ".join(exit_reasons) if exit_reasons else None
        active_exchange = getattr(trade, "exchange", None) or exchange or "delta_india"

        values = {
            "trade_id": trade.strategy_trade_id,
            "strategy_name": trade.strategy_name or "short_strangle",
            "exchange": active_exchange,
            "trade_date": trade_date_val,
            "status": trade.state.value,
            "entry_time": entry_time_val,
            "exit_time": exit_time_val,
            "total_entry_premium": total_entry_prem,
            "total_exit_premium": total_exit_prem,
            "realized_pnl": realized_pnl,
            "total_fees": total_fees,
            "net_pnl": net_pnl,
            "exit_reason": exit_reason_str,
            "strategy_config": config_snapshot or {},
            "updated_at": datetime.now(timezone.utc),
        }

        stmt = insert(TradeModel).values(
            trade_id=values["trade_id"],
            strategy_name=values["strategy_name"],
            exchange=values["exchange"],

            trade_date=values["trade_date"],
            status=values["status"],
            entry_time=values["entry_time"],
            exit_time=values["exit_time"],
            total_entry_premium=values["total_entry_premium"],
            total_exit_premium=values["total_exit_premium"],
            realized_pnl=values["realized_pnl"],
            total_fees=values["total_fees"],
            net_pnl=values["net_pnl"],
            exit_reason=values["exit_reason"],
            strategy_config=values["strategy_config"],
            created_at=to_datetime(trade.created_at) or datetime.now(timezone.utc),
            updated_at=values["updated_at"],
        )

        update_dict = {
            "status": stmt.excluded.status,
            "exit_time": stmt.excluded.exit_time,
            "total_entry_premium": stmt.excluded.total_entry_premium,
            "total_exit_premium": stmt.excluded.total_exit_premium,
            "realized_pnl": stmt.excluded.realized_pnl,
            "total_fees": stmt.excluded.total_fees,
            "net_pnl": stmt.excluded.net_pnl,
            "exit_reason": stmt.excluded.exit_reason,
            "updated_at": stmt.excluded.updated_at,
        }
        if config_snapshot:
            update_dict["strategy_config"] = stmt.excluded.strategy_config

        stmt = stmt.on_conflict_do_update(
            index_elements=[TradeModel.trade_id],
            set_=update_dict,
        )

        async with self.db.get_session() as session:
            await session.execute(stmt)
            await session.commit()

    async def upsert_leg(self, leg: StrategyLeg, trade_id: str) -> None:
        """Idempotently insert or update a TradeLeg record."""
        stmt = insert(TradeLegModel).values(
            leg_id=leg.leg_id,
            trade_id=trade_id,
            leg_type=leg.option_type.value if hasattr(leg.option_type, "value") else str(leg.option_type),
            symbol=leg.symbol,
            product_id=str(leg.instrument_id),
            strike=to_decimal(leg.strike, places=2),
            quantity=to_decimal(leg.quantity),
            side="sell",
            entry_price=to_decimal(leg.entry_fill_price, default=None),
            exit_price=to_decimal(leg.exit_price, default=None),
            entry_time=to_datetime(leg.entry_timestamp),
            exit_time=to_datetime(leg.exit_timestamp),
            stop_loss_price=to_decimal(leg.sl_price, default=None),
            bracket_order_id=str(leg.bracket_order_id) if leg.bracket_order_id else None,
            realized_pnl=to_decimal(leg.realized_pnl),
            fees=to_decimal(leg.fees),
            status=leg.status.value if hasattr(leg.status, "value") else str(leg.status),
            created_at=to_datetime(leg.entry_timestamp) or datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        stmt = stmt.on_conflict_do_update(
            index_elements=[TradeLegModel.leg_id],
            set_={
                "entry_price": stmt.excluded.entry_price,
                "exit_price": stmt.excluded.exit_price,
                "entry_time": stmt.excluded.entry_time,
                "exit_time": stmt.excluded.exit_time,
                "stop_loss_price": stmt.excluded.stop_loss_price,
                "bracket_order_id": stmt.excluded.bracket_order_id,
                "realized_pnl": stmt.excluded.realized_pnl,
                "fees": stmt.excluded.fees,
                "status": stmt.excluded.status,
                "updated_at": stmt.excluded.updated_at,
            },
        )

        async with self.db.get_session() as session:
            await session.execute(stmt)
            await session.commit()

    async def upsert_order(
        self,
        order: Order,
        trade_id: Optional[str] = None,
        leg_id: Optional[str] = None,
    ) -> str:
        """Idempotently insert or update an Order record. Returns the order_id."""
        order_id = str(order.order_id) if order.order_id else f"ORD_{order.client_order_id}"
        exchange_order_id = str(order.order_id) if order.order_id else None

        stmt = insert(OrderModel).values(
            order_id=order_id,
            trade_id=trade_id or order.strategy_id,
            trade_leg_id=leg_id or order.leg_id,
            exchange="delta_india",
            exchange_order_id=exchange_order_id,
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            product_id=str(order.instrument_id),
            side=order.side.value if hasattr(order.side, "value") else str(order.side),
            order_type=order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type),
            quantity=to_decimal(order.quantity),
            filled_quantity=to_decimal(order.filled_quantity),
            average_fill_price=to_decimal(order.average_fill_price, default=None),
            status=order.state.value if hasattr(order.state, "value") else str(order.state),
            reduce_only=bool(order.reduce_only),
            created_at=to_datetime(order.created_at) or datetime.now(timezone.utc),
            updated_at=to_datetime(order.updated_at) or datetime.now(timezone.utc),
        )

        stmt = stmt.on_conflict_do_update(
            index_elements=[OrderModel.order_id],
            set_={
                "exchange_order_id": stmt.excluded.exchange_order_id,
                "filled_quantity": stmt.excluded.filled_quantity,
                "average_fill_price": stmt.excluded.average_fill_price,
                "status": stmt.excluded.status,
                "updated_at": stmt.excluded.updated_at,
            },
        )

        async with self.db.get_session() as session:
            await session.execute(stmt)
            await session.commit()

        return order_id

    async def upsert_fill(self, fill: Fill, order_id: str) -> None:
        """Idempotently insert an execution fill record."""
        fill_id = str(fill.fill_id) if fill.fill_id else f"FILL_{order_id}_{fill.quantity}_{fill.price}"
        stmt = insert(FillModel).values(
            fill_id=fill_id,
            order_id=order_id,
            exchange_fill_id=str(fill.fill_id) if fill.fill_id else None,
            quantity=to_decimal(fill.quantity),
            price=to_decimal(fill.price),
            fee=to_decimal(fill.fee),
            fee_currency=fill.fee_asset or "USD",
            fill_time=to_datetime(fill.timestamp) or datetime.now(timezone.utc),
        )

        stmt = stmt.on_conflict_do_nothing(
            index_elements=[FillModel.fill_id],
        )

        async with self.db.get_session() as session:
            await session.execute(stmt)
            await session.commit()

    async def record_entry(
        self,
        trade: StrategyTrade,
        ce_order: Optional[Order] = None,
        pe_order: Optional[Order] = None,
        ce_fills: Optional[List[Fill]] = None,
        pe_fills: Optional[List[Fill]] = None,
        config_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist complete entry lifecycle: trade, legs, entry orders, and execution fills."""
        # 1. Upsert Trade
        await self.upsert_trade(trade, config_snapshot=config_snapshot)

        # 2. Upsert Legs
        if trade.ce_leg:
            await self.upsert_leg(trade.ce_leg, trade_id=trade.strategy_trade_id)
        if trade.pe_leg:
            await self.upsert_leg(trade.pe_leg, trade_id=trade.strategy_trade_id)

        # 3. Upsert CE Order & Fills
        if ce_order and trade.ce_leg:
            db_ord_id = await self.upsert_order(
                ce_order,
                trade_id=trade.strategy_trade_id,
                leg_id=trade.ce_leg.leg_id,
            )
            if ce_fills:
                for f in ce_fills:
                    await self.upsert_fill(f, order_id=db_ord_id)
            elif ce_order.filled_quantity > 0 and ce_order.average_fill_price:
                # Synthesize primary fill record if individual fills not separately streamed
                synth_fill = Fill(
                    fill_id=f"FILL_ENTRY_{db_ord_id}",
                    order_id=db_ord_id,
                    client_order_id=ce_order.client_order_id,
                    instrument_id=ce_order.instrument_id,
                    symbol=ce_order.symbol,
                    side=ce_order.side,
                    quantity=ce_order.filled_quantity,
                    price=ce_order.average_fill_price,
                    fee=trade.ce_leg.fees,
                    fee_asset="USD",
                    timestamp=trade.ce_leg.entry_timestamp,
                )
                await self.upsert_fill(synth_fill, order_id=db_ord_id)

        # 4. Upsert PE Order & Fills
        if pe_order and trade.pe_leg:
            db_ord_id = await self.upsert_order(
                pe_order,
                trade_id=trade.strategy_trade_id,
                leg_id=trade.pe_leg.leg_id,
            )
            if pe_fills:
                for f in pe_fills:
                    await self.upsert_fill(f, order_id=db_ord_id)
            elif pe_order.filled_quantity > 0 and pe_order.average_fill_price:
                synth_fill = Fill(
                    fill_id=f"FILL_ENTRY_{db_ord_id}",
                    order_id=db_ord_id,
                    client_order_id=pe_order.client_order_id,
                    instrument_id=pe_order.instrument_id,
                    symbol=pe_order.symbol,
                    side=pe_order.side,
                    quantity=pe_order.filled_quantity,
                    price=pe_order.average_fill_price,
                    fee=trade.pe_leg.fees,
                    fee_asset="USD",
                    timestamp=trade.pe_leg.entry_timestamp,
                )
                await self.upsert_fill(synth_fill, order_id=db_ord_id)

    async def record_leg_exit(
        self,
        leg: StrategyLeg,
        trade_id: str,
        exit_order: Optional[Order] = None,
        exit_fills: Optional[List[Fill]] = None,
        parent_trade: Optional[StrategyTrade] = None,
    ) -> None:
        """Persist leg exit details, exit order/fills, and update parent trade status and P&L."""
        # 1. Upsert Leg
        await self.upsert_leg(leg, trade_id=trade_id)

        # 2. Upsert Exit Order & Fills
        if exit_order:
            db_ord_id = await self.upsert_order(
                exit_order,
                trade_id=trade_id,
                leg_id=leg.leg_id,
            )
            if exit_fills:
                for f in exit_fills:
                    await self.upsert_fill(f, order_id=db_ord_id)
            elif exit_order.filled_quantity > 0 and exit_order.average_fill_price:
                synth_fill = Fill(
                    fill_id=f"FILL_EXIT_{db_ord_id}",
                    order_id=db_ord_id,
                    client_order_id=exit_order.client_order_id,
                    instrument_id=exit_order.instrument_id,
                    symbol=exit_order.symbol,
                    side=exit_order.side,
                    quantity=exit_order.filled_quantity,
                    price=exit_order.average_fill_price,
                    fee=0.0,
                    fee_asset="USD",
                    timestamp=leg.exit_timestamp,
                )
                await self.upsert_fill(synth_fill, order_id=db_ord_id)

        # 3. Update Parent Trade
        if parent_trade:
            await self.upsert_trade(parent_trade)

    async def record_trade_completion(
        self,
        trade: StrategyTrade,
        exit_orders: Optional[List[Order]] = None,
    ) -> None:
        """Finalize trade completion in database."""
        if trade.ce_leg:
            await self.upsert_leg(trade.ce_leg, trade_id=trade.strategy_trade_id)
        if trade.pe_leg:
            await self.upsert_leg(trade.pe_leg, trade_id=trade.strategy_trade_id)

        if exit_orders:
            for ord_obj in exit_orders:
                leg_id = None
                if trade.ce_leg and ord_obj.symbol == trade.ce_leg.symbol:
                    leg_id = trade.ce_leg.leg_id
                elif trade.pe_leg and ord_obj.symbol == trade.pe_leg.symbol:
                    leg_id = trade.pe_leg.leg_id
                await self.upsert_order(ord_obj, trade_id=trade.strategy_trade_id, leg_id=leg_id)

        await self.upsert_trade(trade)

    async def get_trade(self, trade_id: str) -> Optional[TradeModel]:
        """Fetch a single trade record with legs and orders by trade_id."""
        async with self.db.get_session() as session:
            stmt = select(TradeModel).where(TradeModel.trade_id == trade_id)
            res = await session.execute(stmt)
            return res.scalar_one_or_none()
