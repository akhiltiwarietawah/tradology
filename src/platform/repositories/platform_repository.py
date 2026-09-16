"""Platform repositories — user-scoped data access."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects.postgresql import insert

from src.persistence.db import DatabaseManager
from src.persistence.platform_models import (
    AuditEventModel,
    EquitySnapshotModel,
    ExchangeAccountModel,
    StrategyAccountModel,
    StrategyCatalogModel,
    SubscriptionModel,
    UserModel,
)
from src.platform.security.credentials import CredentialVault


class PlatformRepository:
    def __init__(self, db: DatabaseManager, vault: Optional[CredentialVault] = None):
        self.db = db
        self.vault = vault or CredentialVault()

    async def upsert_user(
        self,
        *,
        email: str,
        google_id: Optional[str] = None,
        name: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> UserModel:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            stmt = (
                insert(UserModel)
                .values(
                    id=uuid.uuid4(),
                    email=email.lower().strip(),
                    google_id=google_id,
                    name=name,
                    avatar_url=avatar_url,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[UserModel.email],
                    set_={
                        "google_id": google_id,
                        "name": name,
                        "avatar_url": avatar_url,
                        "updated_at": now,
                    },
                )
                .returning(UserModel)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.scalar_one()

    async def get_user_by_email(self, email: str) -> Optional[UserModel]:
        async with self.db.get_session() as session:
            stmt = select(UserModel).where(UserModel.email == email.lower().strip())
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_strategies(self, active_only: bool = True) -> List[StrategyCatalogModel]:
        async with self.db.get_session() as session:
            stmt = select(StrategyCatalogModel)
            if active_only:
                stmt = stmt.where(StrategyCatalogModel.is_active.is_(True))
            stmt = stmt.order_by(StrategyCatalogModel.name)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_strategy_by_code(self, code: str) -> Optional[StrategyCatalogModel]:
        async with self.db.get_session() as session:
            stmt = select(StrategyCatalogModel).where(StrategyCatalogModel.code == code)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create_subscription(self, user_id: uuid.UUID, strategy_id: uuid.UUID) -> SubscriptionModel:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            existing = await session.execute(
                select(SubscriptionModel).where(
                    SubscriptionModel.user_id == user_id,
                    SubscriptionModel.strategy_id == strategy_id,
                )
            )
            row = existing.scalar_one_or_none()
            if row:
                return row

            sub = SubscriptionModel(
                id=uuid.uuid4(),
                user_id=user_id,
                strategy_id=strategy_id,
                status="ACTIVE",
                billing_plan="free",
                subscribed_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(sub)
            await session.commit()
            await session.refresh(sub)
            return sub

    async def list_user_subscriptions(self, user_id: uuid.UUID) -> List[SubscriptionModel]:
        async with self.db.get_session() as session:
            stmt = (
                select(SubscriptionModel)
                .options(selectinload(SubscriptionModel.strategy))
                .where(SubscriptionModel.user_id == user_id)
                .order_by(desc(SubscriptionModel.subscribed_at))
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def create_exchange_account(
        self,
        *,
        user_id: uuid.UUID,
        exchange: str,
        label: str,
        api_key: str,
        api_secret: str,
        passphrase: Optional[str] = None,
        is_testnet: bool = False,
    ) -> ExchangeAccountModel:
        now = datetime.now(timezone.utc)
        creds = self.vault.encrypt_credentials(
            {"api_key": api_key, "api_secret": api_secret, "passphrase": passphrase}
        )
        async with self.db.get_session() as session:
            account = ExchangeAccountModel(
                id=uuid.uuid4(),
                user_id=user_id,
                exchange=exchange.lower(),
                label=label,
                credentials_encrypted=creds,
                connection_status="pending",
                health_status="DISCONNECTED",
                is_testnet=is_testnet,
                created_at=now,
                updated_at=now,
            )
            session.add(account)
            await session.commit()
            await session.refresh(account)
            return account

    async def list_exchange_accounts(self, user_id: uuid.UUID) -> List[ExchangeAccountModel]:
        async with self.db.get_session() as session:
            stmt = (
                select(ExchangeAccountModel)
                .where(ExchangeAccountModel.user_id == user_id)
                .order_by(ExchangeAccountModel.created_at.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_exchange_account(self, user_id: uuid.UUID, account_id: uuid.UUID) -> Optional[ExchangeAccountModel]:
        async with self.db.get_session() as session:
            stmt = select(ExchangeAccountModel).where(
                ExchangeAccountModel.id == account_id,
                ExchangeAccountModel.user_id == user_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def link_strategy_account(
        self,
        *,
        subscription_id: uuid.UUID,
        exchange_account_id: uuid.UUID,
        status: str = "paused",
        execution_mode: str = "PAPER",
        allocation_pct: float = 100.0,
        risk_overrides: Optional[Dict[str, Any]] = None,
    ) -> StrategyAccountModel:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            existing = await session.execute(
                select(StrategyAccountModel).where(
                    StrategyAccountModel.subscription_id == subscription_id,
                    StrategyAccountModel.exchange_account_id == exchange_account_id,
                )
            )
            row = existing.scalar_one_or_none()
            if row:
                row.status = status
                row.execution_mode = execution_mode
                row.allocation_pct = allocation_pct
                if risk_overrides is not None:
                    row.risk_overrides = risk_overrides
                row.updated_at = now
                await session.commit()
                await session.refresh(row)
                return row

            link = StrategyAccountModel(
                id=uuid.uuid4(),
                subscription_id=subscription_id,
                exchange_account_id=exchange_account_id,
                status=status,
                execution_mode=execution_mode,
                trading_enabled=False,
                runtime_status="STOPPED",
                allocation_pct=allocation_pct,
                risk_overrides=risk_overrides or {},
                created_at=now,
                updated_at=now,
            )
            session.add(link)
            await session.commit()
            await session.refresh(link)
            return link

    async def list_strategy_accounts_for_user(self, user_id: uuid.UUID) -> List[StrategyAccountModel]:
        async with self.db.get_session() as session:
            stmt = (
                select(StrategyAccountModel)
                .join(SubscriptionModel, StrategyAccountModel.subscription_id == SubscriptionModel.id)
                .where(SubscriptionModel.user_id == user_id)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_strategy_account(self, user_id: uuid.UUID, strategy_account_id: uuid.UUID) -> Optional[StrategyAccountModel]:
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

    async def record_audit(
        self,
        *,
        user_id: Optional[uuid.UUID],
        event_type: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        async with self.db.get_session() as session:
            session.add(
                AuditEventModel(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    event_type=event_type,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    payload=payload or {},
                    created_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    async def latest_equity_snapshots(
        self,
        user_id: uuid.UUID,
        scope: Optional[str] = None,
        limit: int = 100,
    ) -> List[EquitySnapshotModel]:
        async with self.db.get_session() as session:
            stmt = select(EquitySnapshotModel).where(EquitySnapshotModel.user_id == user_id)
            if scope:
                stmt = stmt.where(EquitySnapshotModel.scope == scope)
            stmt = stmt.order_by(desc(EquitySnapshotModel.snapshot_at)).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())
