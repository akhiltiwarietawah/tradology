"""Order and position reconciliation for platform runtimes."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from src.platform.execution.adapter_base import ExecutionAdapter
from src.platform.execution.lifecycle_repository import OrderLifecycleRepository
from src.platform.execution.models import ReconciliationReport


class OrderReconciliationService:
    def __init__(
        self,
        lifecycle_repo: OrderLifecycleRepository,
        logger: Optional[logging.Logger] = None,
    ):
        self.lifecycle_repo = lifecycle_repo
        self.logger = logger or logging.getLogger("order_reconciliation")

    async def reconcile(
        self,
        *,
        strategy_account_id,
        execution_adapter: ExecutionAdapter,
        halt_callback: Optional[Callable[[str], Any]] = None,
        audit_callback: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> ReconciliationReport:
        local_open = await self.lifecycle_repo.list_open_intents(strategy_account_id)
        exchange_open = await execution_adapter.get_open_orders()
        local_ids = {row["client_order_id"] for row in local_open}
        exchange_client_ids = {str(o.get("client_order_id") or "") for o in exchange_open if o.get("client_order_id")}

        unknown_local = [r for r in local_open if r["status"] == "UNKNOWN"]
        if unknown_local:
            msg = f"{len(unknown_local)} orders in UNKNOWN state"
            if halt_callback:
                halt_callback(msg)
            await self._audit(audit_callback, "reconciliation.order_unknown", {"count": len(unknown_local)})
            return ReconciliationReport(False, "UNKNOWN", msg, len(local_open), len(exchange_open))

        if len(local_open) != len(exchange_open) and local_ids != exchange_client_ids:
            msg = "Open order count mismatch"
            if halt_callback:
                halt_callback(msg)
            await self._audit(audit_callback, "reconciliation.order_mismatch", {
                "local": len(local_open),
                "exchange": len(exchange_open),
            })
            return ReconciliationReport(False, "MISMATCH", msg, len(local_open), len(exchange_open))

        return ReconciliationReport(True, "MATCH", local_count=len(local_open), exchange_count=len(exchange_open))

    @staticmethod
    async def _audit(callback: Optional[Callable], event_type: str, payload: Dict[str, Any]) -> None:
        if not callback:
            return
        result = callback(event_type, payload)
        if hasattr(result, "__await__"):
            await result


class PositionReconciliationService:
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("position_reconciliation")

    async def reconcile(
        self,
        *,
        expected_positions: List[Dict[str, Any]],
        execution_adapter: ExecutionAdapter,
    ) -> ReconciliationReport:
        actual = await execution_adapter.get_positions()
        expected_symbols = {p.get("symbol"): p for p in expected_positions}
        actual_symbols = {p.get("symbol"): p for p in actual if abs(float(p.get("size") or 0)) > 0}

        if set(expected_symbols.keys()) == set(actual_symbols.keys()):
            for sym in expected_symbols:
                exp_size = float(expected_symbols[sym].get("size") or expected_symbols[sym].get("quantity") or 0)
                act_size = float(actual_symbols[sym].get("size") or 0)
                if abs(exp_size - act_size) > 1e-6:
                    return ReconciliationReport(
                        False,
                        "MISMATCH",
                        f"Position size mismatch on {sym}",
                        details={"expected": exp_size, "actual": act_size},
                    )
            return ReconciliationReport(True, "MATCH")

        if not expected_symbols and not actual_symbols:
            return ReconciliationReport(True, "MATCH")

        return ReconciliationReport(
            False,
            "MISMATCH",
            "Expected positions differ from exchange",
            details={"expected": list(expected_symbols.keys()), "actual": list(actual_symbols.keys())},
        )
