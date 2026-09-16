"""User-scoped platform ledger queries and snapshot writes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, desc, select
from src.persistence.db import DatabaseManager
from src.persistence.models import FillModel, OrderModel, TradeLegModel, TradeModel
from src.persistence.platform_models import AccountPositionModel, EquitySnapshotModel, StrategyAccountModel, SubscriptionModel
from src.platform.ledger.models import PlatformAttribution


class PlatformLedgerRepository:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    async def verify_strategy_account_access(
        self,
        user_id: uuid.UUID,
        strategy_account_id: uuid.UUID,
    ) -> Optional[StrategyAccountModel]:
        async with self.db.get_session() as session:
            stmt = (
                select(StrategyAccountModel)
                .join(SubscriptionModel, StrategyAccountModel.subscription_id == SubscriptionModel.id)
                .where(
                    StrategyAccountModel.id == strategy_account_id,
                    SubscriptionModel.user_id == user_id,
                )
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def verify_exchange_account_access(
        self,
        user_id: uuid.UUID,
        exchange_account_id: uuid.UUID,
    ) -> bool:
        from src.persistence.platform_models import ExchangeAccountModel

        async with self.db.get_session() as session:
            stmt = select(ExchangeAccountModel.id).where(
                ExchangeAccountModel.id == exchange_account_id,
                ExchangeAccountModel.user_id == user_id,
            )
            return (await session.execute(stmt)).scalar_one_or_none() is not None

    async def list_user_trades(
        self,
        user_id: uuid.UUID,
        *,
        strategy_code: Optional[str] = None,
        strategy_account_id: Optional[uuid.UUID] = None,
        exchange_account_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        async with self.db.get_session() as session:
            stmt = (
                select(TradeModel, StrategyAccountModel.exchange_account_id)
                .outerjoin(StrategyAccountModel, TradeModel.strategy_account_id == StrategyAccountModel.id)
                .where(
                    TradeModel.user_id == user_id,
                    TradeModel.strategy_account_id.is_not(None),
                )
            )
            if strategy_code:
                stmt = stmt.where(TradeModel.strategy_name == strategy_code)
            if strategy_account_id:
                stmt = stmt.where(TradeModel.strategy_account_id == strategy_account_id)
            if exchange_account_id:
                stmt = stmt.where(StrategyAccountModel.exchange_account_id == exchange_account_id)
            if status:
                stmt = stmt.where(TradeModel.status == status)
            if from_date:
                stmt = stmt.where(TradeModel.entry_time >= from_date)
            if to_date:
                stmt = stmt.where(TradeModel.entry_time <= to_date)
            stmt = stmt.order_by(desc(TradeModel.entry_time)).limit(limit)
            rows = list((await session.execute(stmt)).all())
            return [self._trade_to_api_dict(trade, acct_id) for trade, acct_id in rows]

    async def get_trades_for_strategy_accounts(
        self,
        user_id: uuid.UUID,
        strategy_account_ids: List[uuid.UUID],
        *,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        if not strategy_account_ids:
            return []
        async with self.db.get_session() as session:
            stmt = select(TradeModel).where(
                TradeModel.user_id == user_id,
                TradeModel.strategy_account_id.in_(strategy_account_ids),
            )
            if from_date:
                stmt = stmt.where(TradeModel.entry_time >= from_date)
            if to_date:
                stmt = stmt.where(TradeModel.entry_time <= to_date)
            stmt = stmt.order_by(desc(TradeModel.entry_time))
            rows = list((await session.execute(stmt)).scalars().all())
            return [self._trade_to_dict(r) for r in rows]

    async def get_open_legs_for_strategy_accounts(
        self,
        user_id: uuid.UUID,
        strategy_account_ids: List[uuid.UUID],
    ) -> List[Dict[str, Any]]:
        if not strategy_account_ids:
            return []
        async with self.db.get_session() as session:
            stmt = (
                select(TradeLegModel, TradeModel.strategy_account_id)
                .join(TradeModel, TradeLegModel.trade_id == TradeModel.trade_id)
                .where(
                    TradeModel.user_id == user_id,
                    TradeModel.strategy_account_id.in_(strategy_account_ids),
                    TradeLegModel.status.in_(["OPEN", "open", "ACTIVE"]),
                )
            )
            rows = (await session.execute(stmt)).all()
            return [
                {
                    "leg_id": leg.leg_id,
                    "trade_id": leg.trade_id,
                    "strategy_account_id": str(sa_id),
                    "symbol": leg.symbol,
                    "side": leg.side,
                    "quantity": float(leg.quantity or 0),
                    "entry_price": float(leg.entry_price) if leg.entry_price is not None else None,
                }
                for leg, sa_id in rows
            ]

    async def build_symbol_ownership_map(
        self,
        user_id: uuid.UUID,
        exchange_account_id: uuid.UUID,
    ) -> Dict[str, str]:
        """Map symbol -> strategy_account_id for open attributed legs on an account."""
        async with self.db.get_session() as session:
            stmt = (
                select(TradeLegModel.symbol, TradeModel.strategy_account_id)
                .join(TradeModel, TradeLegModel.trade_id == TradeModel.trade_id)
                .join(StrategyAccountModel, TradeModel.strategy_account_id == StrategyAccountModel.id)
                .where(
                    TradeModel.user_id == user_id,
                    StrategyAccountModel.exchange_account_id == exchange_account_id,
                    TradeLegModel.status.in_(["OPEN", "open", "ACTIVE"]),
                )
            )
            rows = (await session.execute(stmt)).all()
            owners: Dict[str, str] = {}
            conflicts: set[str] = set()
            for symbol, sa_id in rows:
                key = str(symbol)
                val = str(sa_id)
                if key in owners and owners[key] != val:
                    conflicts.add(key)
                else:
                    owners[key] = val
            for key in conflicts:
                owners.pop(key, None)
            return owners

    async def get_account_mark_prices(
        self,
        user_id: uuid.UUID,
        exchange_account_id: uuid.UUID,
    ) -> Dict[str, Decimal]:
        async with self.db.get_session() as session:
            stmt = select(AccountPositionModel).where(
                AccountPositionModel.user_id == user_id,
                AccountPositionModel.exchange_account_id == exchange_account_id,
            )
            rows = list((await session.execute(stmt)).scalars().all())
            return {
                str(r.symbol): Decimal(str(r.mark_price or r.entry_price or 0))
                for r in rows
                if r.symbol and (r.mark_price is not None or r.entry_price is not None)
            }

    async def record_strategy_equity_snapshot(
        self,
        attribution: PlatformAttribution,
        *,
        equity: float,
        realized_pnl: float,
        unrealized_pnl: float,
        fees: float = 0.0,
        funding: float = 0.0,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            session.add(
                EquitySnapshotModel(
                    id=uuid.uuid4(),
                    user_id=attribution.user_id,
                    exchange_account_id=attribution.exchange_account_id,
                    subscription_id=attribution.subscription_id,
                    strategy_account_id=attribution.strategy_account_id,
                    scope="strategy_account",
                    equity=equity,
                    unrealized_pnl=unrealized_pnl,
                    realized_pnl=realized_pnl,
                    snapshot_at=now,
                    metadata_json={"fees": fees, "funding": funding, "strategy_code": attribution.strategy_code},
                )
            )
            await session.commit()

    async def get_strategy_equity_curve(
        self,
        user_id: uuid.UUID,
        strategy_account_id: uuid.UUID,
        *,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        async with self.db.get_session() as session:
            if not await self.verify_strategy_account_access(user_id, strategy_account_id):
                return []
            stmt = (
                select(EquitySnapshotModel)
                .where(
                    EquitySnapshotModel.user_id == user_id,
                    EquitySnapshotModel.strategy_account_id == strategy_account_id,
                    EquitySnapshotModel.scope == "strategy_account",
                )
                .order_by(EquitySnapshotModel.snapshot_at.asc())
                .limit(limit)
            )
            rows = list((await session.execute(stmt)).scalars().all())
            return [
                {
                    "timestamp": r.snapshot_at.isoformat(),
                    "equity": float(r.equity),
                    "realized_pnl": float(r.realized_pnl or 0),
                    "unrealized_pnl": float(r.unrealized_pnl or 0),
                }
                for r in rows
            ]

    @staticmethod
    def _trade_to_dict(row: TradeModel) -> Dict[str, Any]:
        return {
            "trade_id": row.trade_id,
            "strategy": row.strategy_name,
            "strategy_account_id": str(row.strategy_account_id) if row.strategy_account_id else None,
            "subscription_id": str(row.subscription_id) if row.subscription_id else None,
            "exchange": row.exchange,
            "status": row.status,
            "entry_time": row.entry_time.isoformat() if row.entry_time else None,
            "exit_time": row.exit_time.isoformat() if row.exit_time else None,
            "realized_pnl": float(row.realized_pnl or 0),
            "net_pnl": float(row.net_pnl or 0),
            "total_fees": float(row.total_fees or 0),
            "total_entry_premium": float(row.total_entry_premium or 0),
            "total_exit_premium": float(row.total_exit_premium or 0),
            "exit_reason": row.exit_reason,
        }

    @staticmethod
    def _trade_to_api_dict(row: TradeModel, exchange_account_id: Optional[uuid.UUID]) -> Dict[str, Any]:
        base = PlatformLedgerRepository._trade_to_dict(row)
        return {
            **base,
            "account_id": str(exchange_account_id) if exchange_account_id else None,
            "entry": base["total_entry_premium"],
            "exit": base["total_exit_premium"],
            "quantity": None,
            "fees": base["total_fees"],
            "funding": 0.0,
            "opened_at": base["entry_time"],
            "closed_at": base["exit_time"],
        }
