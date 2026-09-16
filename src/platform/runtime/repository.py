"""Runtime persistence — runtimes, state, idempotency."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from src.persistence.db import DatabaseManager
from src.persistence.platform_models import (
    ExchangeAccountModel,
    StrategyAccountModel,
    StrategyOrderIdempotencyModel,
    StrategyRuntimeModel,
    StrategyRuntimeStateModel,
    SubscriptionModel,
)


class RuntimeRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    async def get_strategy_account_for_user(
        self,
        user_id: uuid.UUID,
        strategy_account_id: uuid.UUID,
    ) -> Optional[StrategyAccountModel]:
        async with self.db.get_session() as session:
            stmt = (
                select(StrategyAccountModel)
                .join(SubscriptionModel, StrategyAccountModel.subscription_id == SubscriptionModel.id)
                .options(
                    selectinload(StrategyAccountModel.subscription).selectinload(SubscriptionModel.strategy),
                    selectinload(StrategyAccountModel.exchange_account),
                )
                .where(
                    StrategyAccountModel.id == strategy_account_id,
                    SubscriptionModel.user_id == user_id,
                )
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_strategy_accounts_for_user_detailed(self, user_id: uuid.UUID) -> List[StrategyAccountModel]:
        async with self.db.get_session() as session:
            stmt = (
                select(StrategyAccountModel)
                .join(SubscriptionModel, StrategyAccountModel.subscription_id == SubscriptionModel.id)
                .options(
                    selectinload(StrategyAccountModel.subscription).selectinload(SubscriptionModel.strategy),
                    selectinload(StrategyAccountModel.exchange_account),
                    selectinload(StrategyAccountModel.runtime).selectinload(StrategyRuntimeModel.state),
                )
                .where(SubscriptionModel.user_id == user_id)
                .order_by(StrategyAccountModel.created_at.desc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_strategy_account_controls(
        self,
        strategy_account_id: uuid.UUID,
        *,
        execution_mode: Optional[str] = None,
        trading_enabled: Optional[bool] = None,
        runtime_status: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[StrategyAccountModel]:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            row = await session.get(StrategyAccountModel, strategy_account_id)
            if not row:
                return None
            if execution_mode is not None:
                row.execution_mode = execution_mode
            if trading_enabled is not None:
                row.trading_enabled = trading_enabled
            if runtime_status is not None:
                row.runtime_status = runtime_status
            if status is not None:
                row.status = status
            row.updated_at = now
            await session.commit()
            await session.refresh(row)
            return row

    async def upsert_runtime(
        self,
        strategy_account_id: uuid.UUID,
        *,
        status: str,
        worker_id: Optional[str] = None,
        last_error: Optional[str] = None,
        clear_error: bool = False,
    ) -> StrategyRuntimeModel:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            stmt = select(StrategyRuntimeModel).where(StrategyRuntimeModel.strategy_account_id == strategy_account_id)
            result = await session.execute(stmt)
            runtime = result.scalar_one_or_none()
            if runtime is None:
                runtime = StrategyRuntimeModel(
                    id=uuid.uuid4(),
                    strategy_account_id=strategy_account_id,
                    status=status,
                    worker_id=worker_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(runtime)
            else:
                runtime.status = status
                runtime.worker_id = worker_id
                runtime.updated_at = now

            if status == "RUNNING" and runtime.started_at is None:
                runtime.started_at = now
            if status in {"STOPPED", "PAUSED", "ERROR", "RECOVERY_REQUIRED"}:
                runtime.stopped_at = now
            if clear_error:
                runtime.last_error = None
                runtime.last_error_at = None
            elif last_error:
                runtime.last_error = last_error[:500]
                runtime.last_error_at = now

            await session.commit()
            await session.refresh(runtime)
            return runtime

    async def touch_heartbeat(self, runtime_id: uuid.UUID) -> None:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            runtime = await session.get(StrategyRuntimeModel, runtime_id)
            if not runtime:
                return
            runtime.last_heartbeat_at = now
            runtime.updated_at = now
            await session.commit()

    async def save_runtime_state(self, runtime_id: uuid.UUID, state: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        safe_state = {k: v for k, v in state.items() if k not in {"api_key", "api_secret", "passphrase", "credentials"}}
        async with self.db.get_session() as session:
            row = await session.get(StrategyRuntimeStateModel, runtime_id)
            if row is None:
                session.add(StrategyRuntimeStateModel(runtime_id=runtime_id, state=safe_state, updated_at=now))
            else:
                row.state = safe_state
                row.updated_at = now
            await session.commit()

    async def get_runtime_state(self, runtime_id: uuid.UUID) -> Dict[str, Any]:
        async with self.db.get_session() as session:
            row = await session.get(StrategyRuntimeStateModel, runtime_id)
            return dict(row.state) if row else {}

    async def list_recoverable_runtimes(self) -> List[StrategyRuntimeModel]:
        async with self.db.get_session() as session:
            stmt = select(StrategyRuntimeModel).where(
                StrategyRuntimeModel.status.in_(["RUNNING", "STARTING", "PAUSED"])
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def try_acquire_runtime_lock(self, strategy_account_id: uuid.UUID, worker_id: str) -> bool:
        """PostgreSQL advisory lock for cross-process duplicate prevention."""
        async with self.db.get_session() as session:
            key = abs(hash(str(strategy_account_id))) % (2**31 - 1)
            locked = await session.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
            if not locked:
                return False
            stmt = select(StrategyRuntimeModel).where(StrategyRuntimeModel.strategy_account_id == strategy_account_id)
            result = await session.execute(stmt)
            runtime = result.scalar_one_or_none()
            if runtime and runtime.status in {"RUNNING", "STARTING"} and runtime.worker_id not in {None, worker_id}:
                await session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                return False
            await session.commit()
            return True

    async def reserve_idempotency_key(
        self,
        strategy_account_id: uuid.UUID,
        client_order_id: str,
        signal_key: Optional[str] = None,
    ) -> bool:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            stmt = (
                insert(StrategyOrderIdempotencyModel)
                .values(
                    id=uuid.uuid4(),
                    strategy_account_id=strategy_account_id,
                    client_order_id=client_order_id,
                    signal_key=signal_key,
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["strategy_account_id", "client_order_id"])
                .returning(StrategyOrderIdempotencyModel.id)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.scalar_one_or_none() is not None

    async def update_idempotency_status(
        self,
        strategy_account_id: uuid.UUID,
        client_order_id: str,
        status: str,
        exchange_order_id: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            stmt = select(StrategyOrderIdempotencyModel).where(
                StrategyOrderIdempotencyModel.strategy_account_id == strategy_account_id,
                StrategyOrderIdempotencyModel.client_order_id == client_order_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return
            row.status = status
            if exchange_order_id:
                row.exchange_order_id = exchange_order_id
            row.updated_at = now
            await session.commit()

    async def get_runtime_by_strategy_account(self, strategy_account_id: uuid.UUID) -> Optional[StrategyRuntimeModel]:
        async with self.db.get_session() as session:
            stmt = select(StrategyRuntimeModel).where(StrategyRuntimeModel.strategy_account_id == strategy_account_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_exchange_account(self, user_id: uuid.UUID, account_id: uuid.UUID) -> Optional[ExchangeAccountModel]:
        async with self.db.get_session() as session:
            stmt = select(ExchangeAccountModel).where(
                ExchangeAccountModel.id == account_id,
                ExchangeAccountModel.user_id == user_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
