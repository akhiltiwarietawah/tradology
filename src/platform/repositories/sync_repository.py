"""Platform sync repository — balances, positions, orders, equity snapshots."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import delete, desc, select

from src.persistence.db import DatabaseManager
from src.persistence.platform_models import (
    AccountBalanceModel,
    AccountOrderModel,
    AccountPositionModel,
    EquitySnapshotModel,
    ExchangeAccountModel,
)
from src.platform.sync.models import AccountSyncSnapshot


class SyncRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    async def list_accounts_for_background_sync(self) -> List[ExchangeAccountModel]:
        async with self.db.get_session() as session:
            stmt = select(ExchangeAccountModel).where(
                ExchangeAccountModel.health_status.in_(
                    ["CONNECTED", "DEGRADED", "SYNCING", "ERROR", "pending", "PENDING"]
                )
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def set_account_health(
        self,
        account_id: uuid.UUID,
        *,
        health_status: str,
        connection_status: str | None = None,
        last_error: str | None = None,
        clear_error: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            account = await session.get(ExchangeAccountModel, account_id)
            if not account:
                return
            account.health_status = health_status
            if connection_status:
                account.connection_status = connection_status
            if clear_error:
                account.last_error = None
                account.last_error_at = None
            elif last_error:
                account.last_error = last_error[:500]
                account.last_error_at = now
            account.updated_at = now
            await session.commit()

    async def persist_snapshot(
        self,
        *,
        account: ExchangeAccountModel,
        snapshot: AccountSyncSnapshot,
    ) -> ExchangeAccountModel:
        now = snapshot.synced_at or datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            row = await session.get(ExchangeAccountModel, account.id)
            if not row:
                return account

            row.equity = snapshot.equity
            row.available_balance = snapshot.available_balance
            row.unrealized_pnl = snapshot.unrealized_pnl
            row.realized_pnl = snapshot.realized_pnl
            row.currency = snapshot.currency
            row.last_sync_at = now
            row.last_successful_sync_at = now
            row.health_status = "CONNECTED"
            row.connection_status = "connected"
            row.last_error = None
            row.last_error_at = None
            row.updated_at = now

            await session.execute(delete(AccountBalanceModel).where(AccountBalanceModel.exchange_account_id == row.id))
            for bal in snapshot.balances[:50]:
                session.add(
                    AccountBalanceModel(
                        id=uuid.uuid4(),
                        exchange_account_id=row.id,
                        asset=bal.asset,
                        total_balance=bal.total_balance,
                        available_balance=bal.available_balance,
                        equity=bal.equity,
                        used_margin=bal.used_margin,
                        unrealized_pnl=bal.unrealized_pnl,
                        realized_pnl=bal.realized_pnl,
                        currency=bal.currency,
                        recorded_at=now,
                    )
                )

            await session.execute(delete(AccountPositionModel).where(AccountPositionModel.exchange_account_id == row.id))
            for pos in snapshot.positions:
                session.add(
                    AccountPositionModel(
                        id=uuid.uuid4(),
                        user_id=row.user_id,
                        exchange_account_id=row.id,
                        symbol=pos.symbol,
                        exchange_symbol=pos.symbol,
                        side=pos.side,
                        quantity=pos.quantity,
                        entry_price=pos.entry_price,
                        mark_price=pos.mark_price,
                        unrealized_pnl=pos.unrealized_pnl,
                        realized_pnl=pos.realized_pnl,
                        leverage=pos.leverage,
                        liquidation_price=pos.liquidation_price,
                        updated_at=now,
                    )
                )

            await session.execute(delete(AccountOrderModel).where(AccountOrderModel.exchange_account_id == row.id))
            for order in snapshot.orders[:100]:
                if not order.exchange_order_id:
                    continue
                session.add(
                    AccountOrderModel(
                        id=uuid.uuid4(),
                        exchange_account_id=row.id,
                        exchange_order_id=order.exchange_order_id,
                        symbol=order.symbol,
                        side=order.side,
                        order_type=order.order_type,
                        quantity=order.quantity,
                        price=order.price,
                        status=order.status,
                        updated_at=now,
                    )
                )

            await self._maybe_insert_equity_snapshot(session, row, snapshot, now)
            await session.commit()
            await session.refresh(row)
            return row

    async def _maybe_insert_equity_snapshot(
        self,
        session,
        account: ExchangeAccountModel,
        snapshot: AccountSyncSnapshot,
        now: datetime,
    ) -> None:
        stmt = (
            select(EquitySnapshotModel)
            .where(
                EquitySnapshotModel.exchange_account_id == account.id,
                EquitySnapshotModel.scope == "account",
            )
            .order_by(desc(EquitySnapshotModel.snapshot_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        last = result.scalar_one_or_none()
        if last:
            last_at = last.snapshot_at
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=timezone.utc)
            current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
            age = (current - last_at).total_seconds()
            last_equity = float(last.equity or 0)
            if last_equity > 0:
                change_pct = abs(snapshot.equity - last_equity) / last_equity
            else:
                change_pct = 1.0 if snapshot.equity else 0.0
            if age < 300 and change_pct < 0.0001:
                return

        session.add(
            EquitySnapshotModel(
                id=uuid.uuid4(),
                user_id=account.user_id,
                exchange_account_id=account.id,
                subscription_id=None,
                scope="account",
                equity=snapshot.equity,
                available_balance=snapshot.available_balance,
                unrealized_pnl=snapshot.unrealized_pnl,
                realized_pnl=snapshot.realized_pnl,
                snapshot_at=now,
                metadata_json={"currency": snapshot.currency},
            )
        )

    async def get_equity_curve(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        range_key: str,
    ) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        start = {
            "1D": now - timedelta(days=1),
            "1W": now - timedelta(weeks=1),
            "1M": now - timedelta(days=30),
            "3M": now - timedelta(days=90),
            "ALL": None,
        }.get(range_key.upper(), now - timedelta(days=30))

        async with self.db.get_session() as session:
            account = await session.get(ExchangeAccountModel, account_id)
            if not account or account.user_id != user_id:
                return []

            stmt = (
                select(EquitySnapshotModel)
                .where(
                    EquitySnapshotModel.exchange_account_id == account_id,
                    EquitySnapshotModel.scope == "account",
                )
                .order_by(EquitySnapshotModel.snapshot_at.asc())
            )
            if start:
                stmt = stmt.where(EquitySnapshotModel.snapshot_at >= start)
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
            return [
                {
                    "timestamp": row.snapshot_at.isoformat(),
                    "equity": float(row.equity),
                    "available_balance": float(row.available_balance or 0),
                    "unrealized_pnl": float(row.unrealized_pnl or 0),
                }
                for row in rows
            ]

    async def get_account_positions(self, user_id: uuid.UUID, account_id: uuid.UUID) -> List[AccountPositionModel]:
        async with self.db.get_session() as session:
            stmt = select(AccountPositionModel).where(
                AccountPositionModel.exchange_account_id == account_id,
                AccountPositionModel.user_id == user_id,
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_account_orders(self, account_id: uuid.UUID) -> List[AccountOrderModel]:
        async with self.db.get_session() as session:
            stmt = select(AccountOrderModel).where(AccountOrderModel.exchange_account_id == account_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())
