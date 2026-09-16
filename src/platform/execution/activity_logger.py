"""Structured execution activity logging — no secrets."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text

from src.persistence.db import DatabaseManager


class ExecutionActivityLogger:
    SENSITIVE_KEYS = {"api_key", "api_secret", "passphrase", "credentials", "credentials_encrypted"}

    def __init__(self, db: DatabaseManager, logger: Optional[logging.Logger] = None):
        self.db = db
        self.logger = logger or logging.getLogger("execution_activity")

    @staticmethod
    def _sanitize(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in payload.items() if k not in ExecutionActivityLogger.SENSITIVE_KEYS}

    async def log(
        self,
        *,
        strategy_account_id: uuid.UUID,
        event_type: str,
        severity: str = "INFO",
        runtime_id: Optional[uuid.UUID] = None,
        signal_key: Optional[str] = None,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        quantity: Optional[float] = None,
        execution_mode: Optional[str] = None,
        order_status: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        safe_meta = self._sanitize(metadata or {})
        now = datetime.now(timezone.utc)
        self.logger.log(
            getattr(logging, severity.upper(), logging.INFO),
            "execution.%s sa=%s signal=%s symbol=%s status=%s",
            event_type,
            strategy_account_id,
            signal_key,
            symbol,
            order_status,
        )
        try:
            async with self.db.get_session() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO platform_execution_activity (
                            id, strategy_account_id, runtime_id, event_type, severity,
                            signal_key, symbol, side, quantity, execution_mode,
                            order_status, exchange_order_id, metadata, created_at
                        ) VALUES (
                            :id, :sa_id, :runtime_id, :event_type, :severity,
                            :signal_key, :symbol, :side, :quantity, :execution_mode,
                            :order_status, :exchange_order_id, CAST(:metadata AS jsonb), :now
                        )
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "sa_id": strategy_account_id,
                        "runtime_id": runtime_id,
                        "event_type": event_type,
                        "severity": severity,
                        "signal_key": signal_key,
                        "symbol": symbol,
                        "side": side,
                        "quantity": quantity,
                        "execution_mode": execution_mode,
                        "order_status": order_status,
                        "exchange_order_id": exchange_order_id,
                        "metadata": json.dumps(safe_meta),
                        "now": now,
                    },
                )
                await session.commit()
        except Exception as exc:
            self.logger.warning("Failed to persist execution activity: %s", type(exc).__name__)
