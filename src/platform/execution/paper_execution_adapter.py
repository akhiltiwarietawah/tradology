"""Paper execution — records fills without exchange calls."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.platform.execution.adapter_base import ExecutionAdapter
from src.platform.execution.models import ExecutionLayerMode, ExecutionResult, OrderIntent, OrderLifecycleStatus


class PaperExecutionAdapter(ExecutionAdapter):
    supports_live_submission = False

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("paper_execution_adapter")

    async def initialize(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def place_order(self, intent: OrderIntent) -> ExecutionResult:
        self.logger.info(
            "PAPER fill %s %s %s qty=%s",
            intent.client_order_id,
            intent.side,
            intent.symbol,
            intent.quantity,
        )
        return ExecutionResult(
            success=True,
            status=OrderLifecycleStatus.FILLED,
            client_order_id=intent.client_order_id,
            filled_quantity=intent.quantity,
            average_price=intent.price,
            mode=ExecutionLayerMode.PAPER,
        )

    async def cancel_order(self, exchange_order_id: str, instrument_id: Optional[str] = None) -> bool:
        return True

    async def get_order(self, client_order_id: str, exchange_order_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return {"client_order_id": client_order_id, "status": "filled"}

    async def get_open_orders(self) -> List[Dict[str, Any]]:
        return []

    async def get_positions(self) -> List[Dict[str, Any]]:
        return []
