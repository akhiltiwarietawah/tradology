"""Order intent persistence and lifecycle tracking."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.persistence.db import DatabaseManager
from src.platform.execution.models import OrderIntent, OrderLifecycleStatus


class OrderLifecycleRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    async def create_intent(
        self,
        *,
        strategy_account_id: uuid.UUID,
        runtime_id: Optional[uuid.UUID],
        intent: OrderIntent,
        execution_mode: str,
        status: OrderLifecycleStatus = OrderLifecycleStatus.ORDER_INTENT,
        group_id: Optional[uuid.UUID] = None,
        leg_role: Optional[str] = None,
    ) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        intent_id = uuid.uuid4()
        async with self.db.get_session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO strategy_order_intents (
                        id, strategy_account_id, runtime_id, signal_key, client_order_id,
                        symbol, side, order_type, quantity, price, status, execution_mode,
                        metadata, group_id, leg_role, created_at, updated_at
                    ) VALUES (
                        :id, :sa_id, :runtime_id, :signal_key, :client_order_id,
                        :symbol, :side, :order_type, :quantity, :price, :status, :execution_mode,
                        CAST(:metadata AS jsonb), :group_id, :leg_role, :now, :now
                    )
                    ON CONFLICT (strategy_account_id, client_order_id) DO NOTHING
                    """
                ),
                {
                    "id": intent_id,
                    "sa_id": strategy_account_id,
                    "runtime_id": runtime_id,
                    "signal_key": intent.signal_key,
                    "client_order_id": intent.client_order_id,
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "order_type": intent.order_type,
                    "quantity": intent.quantity,
                    "price": intent.price,
                    "status": status.value,
                    "execution_mode": execution_mode,
                    "metadata": json.dumps(intent.metadata or {}),
                    "group_id": group_id,
                    "leg_role": leg_role,
                    "now": now,
                },
            )
            await session.commit()
        existing = await self.get_intent_id(strategy_account_id, intent.client_order_id)
        return existing or intent_id

    async def get_intent_id(self, strategy_account_id: uuid.UUID, client_order_id: str) -> Optional[uuid.UUID]:
        async with self.db.get_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id FROM strategy_order_intents
                    WHERE strategy_account_id = :sa_id AND client_order_id = :coid
                    """
                ),
                {"sa_id": strategy_account_id, "coid": client_order_id},
            )
            row = result.fetchone()
            return row[0] if row else None

    async def get_by_client_id(self, strategy_account_id: uuid.UUID, client_order_id: str) -> Optional[Dict[str, Any]]:
        async with self.db.get_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, client_order_id, exchange_order_id, symbol, side, quantity, status,
                           filled_quantity, average_fill_price, group_id, leg_role
                    FROM strategy_order_intents
                    WHERE strategy_account_id = :sa_id AND client_order_id = :coid
                    """
                ),
                {"sa_id": strategy_account_id, "coid": client_order_id},
            )
            row = result.fetchone()
            return dict(row._mapping) if row else None

    async def update_status(
        self,
        strategy_account_id: uuid.UUID,
        client_order_id: str,
        status: OrderLifecycleStatus,
        *,
        exchange_order_id: Optional[str] = None,
        last_error: Optional[str] = None,
        filled_quantity: Optional[float] = None,
        average_fill_price: Optional[float] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            params: Dict[str, Any] = {
                "status": status.value,
                "now": now,
                "sa_id": strategy_account_id,
                "client_order_id": client_order_id,
            }
            sets = ["status = :status", "updated_at = :now"]
            if exchange_order_id:
                sets.append("exchange_order_id = :exchange_order_id")
                params["exchange_order_id"] = exchange_order_id
            if last_error:
                sets.append("last_error = :last_error")
                params["last_error"] = last_error[:500]
            if filled_quantity is not None:
                sets.append("filled_quantity = :filled_quantity")
                params["filled_quantity"] = filled_quantity
            if average_fill_price is not None:
                sets.append("average_fill_price = :average_fill_price")
                params["average_fill_price"] = average_fill_price
            if status == OrderLifecycleStatus.SUBMITTED:
                sets.append("submitted_at = :now")
            if status in {OrderLifecycleStatus.FILLED, OrderLifecycleStatus.WOULD_EXECUTE}:
                sets.append("filled_at = :now")

            await session.execute(
                text(
                    f"""
                    UPDATE strategy_order_intents
                    SET {", ".join(sets)}
                    WHERE strategy_account_id = :sa_id AND client_order_id = :client_order_id
                    """
                ),
                params,
            )
            await session.commit()

    async def list_open_intents(self, strategy_account_id: uuid.UUID) -> List[Dict[str, Any]]:
        async with self.db.get_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT client_order_id, exchange_order_id, symbol, side, quantity, status
                    FROM strategy_order_intents
                    WHERE strategy_account_id = :sa_id
                      AND status IN ('SUBMITTED', 'ACKNOWLEDGED', 'PARTIALLY_FILLED', 'UNKNOWN')
                    """
                ),
                {"sa_id": strategy_account_id},
            )
            return [dict(row._mapping) for row in result.fetchall()]

    async def list_execution_history(
        self,
        strategy_account_id: uuid.UUID,
        *,
        limit: int = 100,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        async with self.db.get_session() as session:
            sql = """
                SELECT signal_key, client_order_id, symbol, side, quantity, status,
                       execution_mode, exchange_order_id, filled_quantity, average_fill_price,
                       created_at, filled_at
                FROM strategy_order_intents
                WHERE strategy_account_id = :sa_id
            """
            params: Dict[str, Any] = {"sa_id": strategy_account_id, "limit": limit}
            if status:
                sql += " AND status = :status"
                params["status"] = status
            sql += " ORDER BY created_at DESC LIMIT :limit"
            result = await session.execute(text(sql), params)
            rows = []
            for row in result.fetchall():
                d = dict(row._mapping)
                for k in ("created_at", "filled_at"):
                    if d.get(k):
                        d[k] = d[k].isoformat()
                rows.append(d)
            return rows
