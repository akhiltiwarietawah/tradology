"""Validation statistics for LIVE_DRY_RUN inspection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import text

from src.persistence.db import DatabaseManager


class ValidationStatsRepository:
    COUNTERS = (
        "signals_generated",
        "would_execute",
        "risk_rejected",
        "duplicate_prevented",
        "market_data_rejected",
        "runtime_errors",
    )

    def __init__(self, db: DatabaseManager):
        self.db = db

    async def increment(self, strategy_account_id: uuid.UUID, counter: str, amount: int = 1) -> None:
        if counter not in self.COUNTERS:
            return
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            await session.execute(
                text(
                    f"""
                    INSERT INTO platform_validation_stats (strategy_account_id, {counter}, updated_at)
                    VALUES (:sa_id, :amount, :now)
                    ON CONFLICT (strategy_account_id) DO UPDATE
                    SET {counter} = platform_validation_stats.{counter} + :amount,
                        updated_at = :now
                    """
                ),
                {"sa_id": strategy_account_id, "amount": amount, "now": now},
            )
            await session.commit()

    async def set_reconciliation(self, strategy_account_id: uuid.UUID, status: str) -> None:
        now = datetime.now(timezone.utc)
        async with self.db.get_session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO platform_validation_stats (strategy_account_id, last_reconciliation, updated_at)
                    VALUES (:sa_id, :status, :now)
                    ON CONFLICT (strategy_account_id) DO UPDATE
                    SET last_reconciliation = :status, updated_at = :now
                    """
                ),
                {"sa_id": strategy_account_id, "status": status, "now": now},
            )
            await session.commit()

    async def get_stats(self, strategy_account_id: uuid.UUID) -> Dict[str, Any]:
        async with self.db.get_session() as session:
            result = await session.execute(
                text("SELECT * FROM platform_validation_stats WHERE strategy_account_id = :sa_id"),
                {"sa_id": strategy_account_id},
            )
            row = result.fetchone()
            if not row:
                return {c: 0 for c in self.COUNTERS} | {"last_reconciliation": None}
            data = dict(row._mapping)
            return {
                "signals_generated": data.get("signals_generated", 0),
                "would_execute": data.get("would_execute", 0),
                "risk_rejected": data.get("risk_rejected", 0),
                "duplicate_prevented": data.get("duplicate_prevented", 0),
                "market_data_rejected": data.get("market_data_rejected", 0),
                "runtime_errors": data.get("runtime_errors", 0),
                "last_reconciliation": data.get("last_reconciliation"),
                "updated_at": data.get("updated_at").isoformat() if data.get("updated_at") else None,
            }

    async def list_activity(
        self,
        strategy_account_id: uuid.UUID,
        *,
        limit: int = 100,
        event_type: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        async with self.db.get_session() as session:
            sql = """
                SELECT event_type, severity, signal_key, symbol, side, quantity,
                       execution_mode, order_status, exchange_order_id, metadata, created_at
                FROM platform_execution_activity
                WHERE strategy_account_id = :sa_id
            """
            params: Dict[str, Any] = {"sa_id": strategy_account_id, "limit": limit}
            if event_type:
                sql += " AND event_type = :event_type"
                params["event_type"] = event_type
            sql += " ORDER BY created_at DESC LIMIT :limit"
            result = await session.execute(text(sql), params)
            rows = []
            for row in result.fetchall():
                d = dict(row._mapping)
                if d.get("created_at"):
                    d["created_at"] = d["created_at"].isoformat()
                rows.append(d)
            return rows
