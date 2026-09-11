"""PostgreSQL persistence for Renko Ichimoku perpetual round-trips."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc
from sqlalchemy.dialects.postgresql import insert

from src.core.models.order import Fill, Order, OrderSide, OrderState
from src.persistence.db import DatabaseManager
from src.persistence.models import FillModel, OrderModel, TradeLegModel, TradeModel
from src.persistence.trade_repository import to_decimal, to_datetime

RENKO_STRATEGY_NAME = "renko_ichimoku"
RENKO_EXCHANGE = "delta_india_renko"
DEFAULT_CONTRACT_VALUE = Decimal("0.01")


def make_renko_trade_id(brick_index: int, when: Optional[datetime] = None) -> str:
    ts = when or datetime.now(timezone.utc)
    return f"RENKO_{ts.strftime('%Y%m%d')}_{int(brick_index)}"


def _leg_type_for_action(action_kind: str) -> str:
    if action_kind in ("enter_long", "exit_long"):
        return "LONG"
    if action_kind in ("enter_short", "exit_short"):
        return "SHORT"
    raise ValueError(f"Unknown Renko action: {action_kind}")


def _entry_side(action_kind: str) -> str:
    return "buy" if action_kind == "enter_long" else "sell"


def _perp_realized_pnl(
    leg_type: str,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
    contract_value: Decimal,
) -> Decimal:
    diff = exit_price - entry_price
    if leg_type == "SHORT":
        diff = -diff
    return round(diff * quantity * contract_value, 4)


class RenkoTradeRepository:
    """Persist Renko entries, exits, orders, and fills to the shared trades schema."""

    def __init__(self, db_manager: DatabaseManager, logger: Optional[logging.Logger] = None):
        self.db = db_manager
        self.logger = logger or logging.getLogger("renko_trade_repository")

    async def record_entry(
        self,
        *,
        trade_id: str,
        order: Order,
        brick: Any,
        action_kind: str,
        action_reason: str,
        account_name: str,
        symbol: str,
        product_id: str,
        quantity: float,
        contract_value: float = 0.01,
        config_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        leg_type = _leg_type_for_action(action_kind)
        leg_id = f"{trade_id}_{leg_type}"
        fill_px = to_decimal(order.average_fill_price or brick.close)
        qty = to_decimal(quantity)
        cv = to_decimal(contract_value)
        entry_notional = round(fill_px * qty * cv, 4)

        trade_values = {
            "trade_id": trade_id,
            "strategy_name": RENKO_STRATEGY_NAME,
            "exchange": RENKO_EXCHANGE,
            "trade_date": now.date(),
            "status": "ACTIVE",
            "entry_time": now,
            "exit_time": None,
            "total_entry_premium": entry_notional,
            "total_exit_premium": Decimal("0.0000"),
            "realized_pnl": Decimal("0.0000"),
            "total_fees": Decimal("0.0000"),
            "net_pnl": Decimal("0.0000"),
            "exit_reason": None,
            "strategy_config": {
                "account": account_name,
                "symbol": symbol,
                "product_id": product_id,
                "brick_index": brick.index,
                "brick_close": brick.close,
                "signal_reason": action_reason,
                "contract_value": float(cv),
                **(config_snapshot or {}),
            },
            "created_at": now,
            "updated_at": now,
        }
        await self._upsert_trade(trade_values)

        leg_values = {
            "leg_id": leg_id,
            "trade_id": trade_id,
            "leg_type": leg_type,
            "symbol": symbol,
            "product_id": str(product_id),
            "strike": None,
            "quantity": qty,
            "side": _entry_side(action_kind),
            "entry_price": fill_px,
            "exit_price": None,
            "entry_time": now,
            "exit_time": None,
            "stop_loss_price": None,
            "bracket_order_id": None,
            "realized_pnl": Decimal("0.0000"),
            "fees": Decimal("0.0000"),
            "status": "OPEN",
            "created_at": now,
            "updated_at": now,
        }
        await self._upsert_leg(leg_values)
        await self._upsert_order_and_fill(
            order=order,
            trade_id=trade_id,
            leg_id=leg_id,
            fill_time=now,
        )

    async def record_exit(
        self,
        *,
        trade_id: str,
        order: Order,
        brick: Any,
        action_kind: str,
        action_reason: str,
        entry_price: float,
        entry_time: Optional[float] = None,
        quantity: float,
        contract_value: float = 0.01,
    ) -> None:
        now = datetime.now(timezone.utc)
        leg_type = _leg_type_for_action(action_kind)
        leg_id = f"{trade_id}_{leg_type}"
        exit_px = to_decimal(order.average_fill_price or brick.close)
        entry_px = to_decimal(entry_price)
        qty = to_decimal(quantity)
        cv = to_decimal(contract_value)
        realized = _perp_realized_pnl(leg_type, entry_px, exit_px, qty, cv)
        exit_notional = round(exit_px * qty * cv, 4)
        entry_notional = round(entry_px * qty * cv, 4)
        entry_dt = (
            datetime.fromtimestamp(entry_time, timezone.utc)
            if entry_time
            else now
        )
        existing = await self.get_trade(trade_id)
        merged_config = dict(existing.strategy_config or {}) if existing else {}
        merged_config.update(
            {
                "exit_brick_index": brick.index,
                "exit_brick_close": brick.close,
                "exit_signal_reason": action_reason,
            }
        )

        leg_values = {
            "leg_id": leg_id,
            "trade_id": trade_id,
            "leg_type": leg_type,
            "symbol": order.symbol,
            "product_id": str(order.instrument_id),
            "strike": None,
            "quantity": qty,
            "side": _entry_side("enter_long" if leg_type == "LONG" else "enter_short"),
            "entry_price": entry_px,
            "exit_price": exit_px,
            "entry_time": entry_dt,
            "exit_time": now,
            "stop_loss_price": None,
            "bracket_order_id": None,
            "realized_pnl": realized,
            "fees": Decimal("0.0000"),
            "status": "CLOSED",
            "created_at": entry_dt,
            "updated_at": now,
        }
        await self._upsert_leg(leg_values)
        await self._upsert_order_and_fill(
            order=order,
            trade_id=trade_id,
            leg_id=leg_id,
            fill_time=now,
        )

        trade_values = {
            "trade_id": trade_id,
            "strategy_name": RENKO_STRATEGY_NAME,
            "exchange": RENKO_EXCHANGE,
            "trade_date": entry_dt.date(),
            "status": "COMPLETED",
            "entry_time": entry_dt,
            "exit_time": now,
            "total_entry_premium": entry_notional,
            "total_exit_premium": exit_notional,
            "realized_pnl": realized,
            "total_fees": Decimal("0.0000"),
            "net_pnl": realized,
            "exit_reason": action_reason,
            "strategy_config": merged_config,
            "created_at": entry_dt,
            "updated_at": now,
        }
        await self._upsert_trade(trade_values)

    async def get_open_trade(self) -> Optional[TradeModel]:
        async with self.db.get_session() as session:
            stmt = (
                select(TradeModel)
                .where(
                    TradeModel.strategy_name == RENKO_STRATEGY_NAME,
                    TradeModel.status == "ACTIVE",
                )
                .order_by(desc(TradeModel.entry_time))
                .limit(1)
            )
            res = await session.execute(stmt)
            return res.scalar_one_or_none()

    async def get_trade(self, trade_id: str) -> Optional[TradeModel]:
        async with self.db.get_session() as session:
            stmt = select(TradeModel).where(TradeModel.trade_id == trade_id)
            res = await session.execute(stmt)
            return res.scalar_one_or_none()

    async def list_trades(self, limit: int = 50) -> List[TradeModel]:
        async with self.db.get_session() as session:
            stmt = (
                select(TradeModel)
                .where(TradeModel.strategy_name == RENKO_STRATEGY_NAME)
                .order_by(desc(TradeModel.entry_time))
                .limit(limit)
            )
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def trade_to_dict(self, trade: TradeModel) -> Dict[str, Any]:
        async with self.db.get_session() as session:
            legs_stmt = select(TradeLegModel).where(TradeLegModel.trade_id == trade.trade_id)
            legs_res = await session.execute(legs_stmt)
            legs = list(legs_res.scalars().all())
        return {
            "trade_id": trade.trade_id,
            "strategy_name": trade.strategy_name,
            "exchange": trade.exchange,
            "trade_date": trade.trade_date.isoformat(),
            "status": trade.status,
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "realized_pnl": float(trade.realized_pnl),
            "net_pnl": float(trade.net_pnl),
            "total_fees": float(trade.total_fees),
            "exit_reason": trade.exit_reason,
            "strategy_config": trade.strategy_config or {},
            "legs": [
                {
                    "leg_id": leg.leg_id,
                    "leg_type": leg.leg_type,
                    "symbol": leg.symbol,
                    "side": leg.side,
                    "quantity": float(leg.quantity),
                    "entry_price": float(leg.entry_price) if leg.entry_price is not None else None,
                    "exit_price": float(leg.exit_price) if leg.exit_price is not None else None,
                    "realized_pnl": float(leg.realized_pnl),
                    "status": leg.status,
                }
                for leg in legs
            ],
        }

    async def _upsert_trade(self, values: Dict[str, Any]) -> None:
        stmt = insert(TradeModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[TradeModel.trade_id],
            set_={
                "status": stmt.excluded.status,
                "exit_time": stmt.excluded.exit_time,
                "total_entry_premium": stmt.excluded.total_entry_premium,
                "total_exit_premium": stmt.excluded.total_exit_premium,
                "realized_pnl": stmt.excluded.realized_pnl,
                "total_fees": stmt.excluded.total_fees,
                "net_pnl": stmt.excluded.net_pnl,
                "exit_reason": stmt.excluded.exit_reason,
                "strategy_config": stmt.excluded.strategy_config,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        async with self.db.get_session() as session:
            await session.execute(stmt)
            await session.commit()

    async def _upsert_leg(self, values: Dict[str, Any]) -> None:
        stmt = insert(TradeLegModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[TradeLegModel.leg_id],
            set_={
                "entry_price": stmt.excluded.entry_price,
                "exit_price": stmt.excluded.exit_price,
                "entry_time": stmt.excluded.entry_time,
                "exit_time": stmt.excluded.exit_time,
                "realized_pnl": stmt.excluded.realized_pnl,
                "fees": stmt.excluded.fees,
                "status": stmt.excluded.status,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        async with self.db.get_session() as session:
            await session.execute(stmt)
            await session.commit()

    async def _upsert_order_and_fill(
        self,
        *,
        order: Order,
        trade_id: str,
        leg_id: str,
        fill_time: datetime,
    ) -> None:
        order_id = str(order.order_id) if order.order_id else f"ORD_{order.client_order_id}"
        order_values = {
            "order_id": order_id,
            "trade_id": trade_id,
            "trade_leg_id": leg_id,
            "exchange": RENKO_EXCHANGE,
            "exchange_order_id": str(order.order_id) if order.order_id else None,
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "product_id": str(order.instrument_id),
            "side": order.side.value if hasattr(order.side, "value") else str(order.side),
            "order_type": order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type),
            "quantity": to_decimal(order.quantity),
            "filled_quantity": to_decimal(order.filled_quantity or order.quantity),
            "average_fill_price": to_decimal(order.average_fill_price, default=None),
            "status": order.state.value if hasattr(order.state, "value") else str(order.state),
            "reduce_only": bool(order.reduce_only),
            "created_at": to_datetime(order.created_at) or fill_time,
            "updated_at": to_datetime(order.updated_at) or fill_time,
        }
        stmt = insert(OrderModel).values(**order_values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[OrderModel.order_id],
            set_={
                "filled_quantity": stmt.excluded.filled_quantity,
                "average_fill_price": stmt.excluded.average_fill_price,
                "status": stmt.excluded.status,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        async with self.db.get_session() as session:
            await session.execute(stmt)
            await session.commit()

        if order.state == OrderState.FILLED or float(order.filled_quantity or 0) > 0:
            fill = Fill(
                fill_id=f"FILL_{order_id}",
                order_id=order_id,
                client_order_id=order.client_order_id,
                instrument_id=order.instrument_id,
                symbol=order.symbol,
                side=order.side,
                quantity=float(order.filled_quantity or order.quantity),
                price=float(order.average_fill_price or 0),
                fee=0.0,
                fee_asset="USD",
                timestamp=fill_time.isoformat(),
            )
            fill_stmt = insert(FillModel).values(
                fill_id=fill.fill_id,
                order_id=order_id,
                exchange_fill_id=str(order.order_id) if order.order_id else None,
                quantity=to_decimal(fill.quantity),
                price=to_decimal(fill.price),
                fee=to_decimal(fill.fee),
                fee_currency=fill.fee_asset or "USD",
                fill_time=fill_time,
            ).on_conflict_do_nothing(index_elements=[FillModel.fill_id])
            async with self.db.get_session() as session:
                await session.execute(fill_stmt)
                await session.commit()
