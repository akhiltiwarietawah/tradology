"""Persisted multi-leg strangle execution group state machine."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.persistence.db import DatabaseManager
from src.platform.execution.models import StrangleGroupStatus


class StrangleGroupRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    async def get_by_signal(self, strategy_account_id: uuid.UUID, signal_key: str) -> Optional[Dict[str, Any]]:
        async with self.db.get_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, signal_key, trade_id, status, leg_1_client_order_id, leg_2_client_order_id,
                           unwind_client_order_id, metadata, last_error, created_at, updated_at
                    FROM strategy_order_groups
                    WHERE strategy_account_id = :sa_id AND signal_key = :signal_key
                    """
                ),
                {"sa_id": strategy_account_id, "signal_key": signal_key},
            )
            row = result.fetchone()
            return dict(row._mapping) if row else None

    async def create_group(
        self,
        *,
        strategy_account_id: uuid.UUID,
        runtime_id: Optional[uuid.UUID],
        signal_key: str,
        trade_id: str,
        leg_1_client_order_id: str,
        leg_2_client_order_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        group_id = uuid.uuid4()
        async with self.db.get_session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO strategy_order_groups (
                        id, strategy_account_id, runtime_id, signal_key, trade_id, status,
                        leg_1_client_order_id, leg_2_client_order_id, metadata, created_at, updated_at
                    ) VALUES (
                        :id, :sa_id, :runtime_id, :signal_key, :trade_id, :status,
                        :leg1, :leg2, CAST(:metadata AS jsonb), :now, :now
                    )
                    ON CONFLICT (strategy_account_id, signal_key) DO NOTHING
                    """
                ),
                {
                    "id": group_id,
                    "sa_id": strategy_account_id,
                    "runtime_id": runtime_id,
                    "signal_key": signal_key,
                    "trade_id": trade_id,
                    "status": StrangleGroupStatus.PENDING.value,
                    "leg1": leg_1_client_order_id,
                    "leg2": leg_2_client_order_id,
                    "metadata": json.dumps(metadata or {}),
                    "now": now,
                },
            )
            await session.commit()
        existing = await self.get_by_signal(strategy_account_id, signal_key)
        return existing["id"] if existing else group_id

    async def update_status(
        self,
        group_id: uuid.UUID,
        status: StrangleGroupStatus,
        *,
        last_error: Optional[str] = None,
        unwind_client_order_id: Optional[str] = None,
        metadata_patch: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            sets = ["status = :status", "updated_at = :now"]
            params: Dict[str, Any] = {"status": status.value, "now": now, "id": group_id}
            if last_error:
                sets.append("last_error = :last_error")
                params["last_error"] = last_error[:500]
            if unwind_client_order_id:
                sets.append("unwind_client_order_id = :unwind_id")
                params["unwind_id"] = unwind_client_order_id
            if metadata_patch:
                sets.append("metadata = metadata || CAST(:meta AS jsonb)")
                params["meta"] = json.dumps(metadata_patch)
            await session.execute(
                text(f"UPDATE strategy_order_groups SET {', '.join(sets)} WHERE id = :id"),
                params,
            )
            await session.commit()

    async def list_incomplete(self, strategy_account_id: uuid.UUID) -> List[Dict[str, Any]]:
        terminal = {
            StrangleGroupStatus.COMPLETE.value,
            StrangleGroupStatus.UNWOUND.value,
            StrangleGroupStatus.LEG_1_FAILED.value,
        }
        async with self.db.get_session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT id, signal_key, trade_id, status, leg_1_client_order_id, leg_2_client_order_id
                    FROM strategy_order_groups
                    WHERE strategy_account_id = :sa_id
                      AND status NOT IN ('COMPLETE', 'UNWOUND', 'LEG_1_FAILED')
                    ORDER BY updated_at DESC
                    """
                ),
                {"sa_id": strategy_account_id},
            )
            rows = [dict(r._mapping) for r in result.fetchall()]
            return [r for r in rows if r["status"] not in terminal]
