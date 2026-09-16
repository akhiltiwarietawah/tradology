"""Pre-flight checks before multi-leg strangle entry."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from src.platform.execution.group_repository import StrangleGroupRepository
from src.platform.runtime.models import ExecutionMode, RuntimeContext, SafetyCheckResult
from src.platform.runtime.safety import ExecutionSafetyChecker


class StranglePreflightChecker:
    """Comprehensive gate before any strangle entry attempt."""

    def __init__(
        self,
        *,
        safety_checker: ExecutionSafetyChecker,
        group_repository: StrangleGroupRepository,
    ):
        self.safety = safety_checker
        self.groups = group_repository

    async def run(
        self,
        ctx: RuntimeContext,
        *,
        signal_key: str,
        runtime_status: str,
        market_data_fresh: bool,
        adapter_supports_execution: bool,
        expected_positions: Optional[List[Dict[str, Any]]] = None,
        exchange_positions: Optional[List[Dict[str, Any]]] = None,
        runtime_in_recovery: bool = False,
    ) -> SafetyCheckResult:
        if runtime_in_recovery or runtime_status == "RECOVERY_REQUIRED":
            return SafetyCheckResult(approved=False, code="recovery_required", reason="Runtime requires recovery")

        incomplete = await self.groups.list_incomplete(ctx.strategy_account_id)
        if incomplete:
            return SafetyCheckResult(
                approved=False,
                code="pending_group",
                reason=f"Incomplete strangle group exists: {incomplete[0]['status']}",
            )

        existing = await self.groups.get_by_signal(ctx.strategy_account_id, signal_key)
        if existing and existing["status"] not in {"COMPLETE", "UNWOUND", "LEG_1_FAILED"}:
            return SafetyCheckResult(approved=False, code="duplicate_signal", reason="Signal group already in progress")

        safety = self.safety.check_order_submission(
            ctx,
            runtime_status=runtime_status,
            adapter_supports_execution=adapter_supports_execution,
            market_data_fresh=market_data_fresh,
            duplicate_signal=False,
        )
        if not safety.approved:
            return safety

        if ctx.execution_mode == ExecutionMode.LIVE:
            live = self.safety.check_live_enable(ctx)
            if not live.approved:
                return live

        if expected_positions and exchange_positions:
            exp_syms = {p.get("symbol") for p in expected_positions if p.get("symbol")}
            act_syms = {
                p.get("symbol")
                for p in exchange_positions
                if abs(float(p.get("size") or 0)) > 0
            }
            unexpected = act_syms - exp_syms
            if unexpected:
                return SafetyCheckResult(
                    approved=False,
                    code="conflicting_position",
                    reason=f"Unexpected exchange positions: {sorted(unexpected)}",
                )

        return SafetyCheckResult(approved=True)
