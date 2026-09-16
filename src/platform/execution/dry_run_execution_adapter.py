"""Live dry-run execution — full pipeline without submitting to exchange."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.platform.execution.adapter_base import ExecutionAdapter
from src.platform.execution.models import ExecutionLayerMode, ExecutionResult, OrderIntent, OrderLifecycleStatus


class LiveDryRunExecutionAdapter(ExecutionAdapter):
    supports_live_submission = False

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("live_dry_run_adapter")

    async def initialize(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def place_order(self, intent: OrderIntent) -> ExecutionResult:
        self.logger.info(
            "WOULD EXECUTE LIVE %s %s %s qty=%s @ %s",
            intent.client_order_id,
            intent.side,
            intent.symbol,
            intent.quantity,
            intent.price or "MKT",
        )
        return ExecutionResult(
            success=True,
            status=OrderLifecycleStatus.WOULD_EXECUTE,
            client_order_id=intent.client_order_id,
            filled_quantity=intent.quantity,
            message="Live dry-run — order not submitted",
            mode=ExecutionLayerMode.LIVE_DRY_RUN,
        )

    async def cancel_order(self, exchange_order_id: str, instrument_id: Optional[str] = None) -> bool:
        return True

    async def get_order(self, client_order_id: str, exchange_order_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return None

    async def get_open_orders(self) -> List[Dict[str, Any]]:
        return []

    async def get_positions(self) -> List[Dict[str, Any]]:
        return []
