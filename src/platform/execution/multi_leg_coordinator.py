"""Multi-leg strangle execution coordinator with atomic unwind semantics."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, Optional

from src.core.models.instrument import Instrument
from src.core.models.trade import LegStatus, StrategyState, StrategyTrade
from src.platform.execution.activity_logger import ExecutionActivityLogger
from src.platform.execution.client_order_ids import build_client_order_id
from src.platform.execution.group_repository import StrangleGroupRepository
from src.platform.execution.models import (
    ExecutionResult,
    OrderIntent,
    OrderLifecycleStatus,
    StrangleExecutionResult,
    StrangleGroupStatus,
)
from src.platform.execution.pipeline import OrderExecutionPipeline
from src.platform.execution.preflight import StranglePreflightChecker
from src.platform.persistence.exit_ledger import PlatformExitLedger
from src.platform.persistence.fill_bridge import PlatformFillBridge
from src.platform.runtime.models import RuntimeContext


class StrangleExecutionCoordinator:
    """Coordinates two-leg strangle entry with preflight, state machine, and emergency unwind."""

    FILLED_STATUSES = {OrderLifecycleStatus.FILLED, OrderLifecycleStatus.WOULD_EXECUTE}

    def __init__(
        self,
        *,
        context: RuntimeContext,
        pipeline: OrderExecutionPipeline,
        group_repository: StrangleGroupRepository,
        preflight: StranglePreflightChecker,
        activity_logger: Optional[ExecutionActivityLogger] = None,
        fill_bridge: Optional[PlatformFillBridge] = None,
        exit_ledger: Optional[PlatformExitLedger] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.context = context
        self.pipeline = pipeline
        self.groups = group_repository
        self.preflight = preflight
        self.activity = activity_logger
        self.fill_bridge = fill_bridge
        self.exit_ledger = exit_ledger
        self.logger = logger or logging.getLogger("strangle_coordinator")

    async def execute_strangle_entry(
        self,
        trade: StrategyTrade,
        ce_inst: Instrument,
        pe_inst: Instrument,
        ce_est: float,
        pe_est: float,
        *,
        runtime_status: str,
        market_data_fresh_fn: Callable[[], bool],
        expected_positions: Optional[list] = None,
    ) -> StrangleExecutionResult:
        signal_key = f"strangle_{trade.strategy_trade_id}"
        ce_coid = build_client_order_id(
            strategy_account_id=self.context.strategy_account_id,
            signal_key=signal_key,
            leg_role="CE",
        )
        pe_coid = build_client_order_id(
            strategy_account_id=self.context.strategy_account_id,
            signal_key=signal_key,
            leg_role="PE",
        )

        exchange_positions = []
        adapter = self.pipeline._adapter
        if adapter:
            try:
                exchange_positions = await adapter.get_positions()
            except Exception:
                pass

        pre = await self.preflight.run(
            self.context,
            signal_key=signal_key,
            runtime_status=runtime_status,
            market_data_fresh=market_data_fresh_fn(),
            adapter_supports_execution=self.context.exchange == "delta_india",
            expected_positions=expected_positions,
            exchange_positions=exchange_positions,
            runtime_in_recovery=runtime_status == "RECOVERY_REQUIRED",
        )
        if not pre.approved:
            await self._log("preflight.rejected", "WARNING", signal_key=signal_key, metadata={"code": pre.code, "reason": pre.reason})
            return StrangleExecutionResult(False, StrangleGroupStatus.LEG_1_FAILED, pre.reason)

        group_id = await self.groups.create_group(
            strategy_account_id=self.context.strategy_account_id,
            runtime_id=self.context.runtime_id,
            signal_key=signal_key,
            trade_id=trade.strategy_trade_id,
            leg_1_client_order_id=ce_coid,
            leg_2_client_order_id=pe_coid,
            metadata={"ce_symbol": ce_inst.symbol, "pe_symbol": pe_inst.symbol},
        )
        await self.groups.update_status(group_id, StrangleGroupStatus.PRECHECKED)
        trade.state = StrategyState.PENDING_ENTRY

        if not market_data_fresh_fn():
            await self._fail_group(group_id, StrangleGroupStatus.RECOVERY_REQUIRED, "Stale market data before leg 1")
            self.pipeline.halt_new_entries("Stale market data")
            return StrangleExecutionResult(False, StrangleGroupStatus.RECOVERY_REQUIRED, "Stale market data")

        ce_result = await self._submit_leg(
            group_id=group_id,
            trade=trade,
            leg=trade.ce_leg,
            inst=ce_inst,
            est=ce_est,
            client_order_id=ce_coid,
            signal_key=signal_key,
            leg_role="CE",
            runtime_status=runtime_status,
            market_data_fresh_fn=market_data_fresh_fn,
            submitted_status=StrangleGroupStatus.LEG_1_SUBMITTED,
            filled_status=StrangleGroupStatus.LEG_1_FILLED,
            failed_status=StrangleGroupStatus.LEG_1_FAILED,
        )
        if not self._leg_succeeded(ce_result):
            status = StrangleGroupStatus.RECOVERY_REQUIRED if ce_result.status == OrderLifecycleStatus.UNKNOWN else StrangleGroupStatus.LEG_1_FAILED
            await self._fail_group(group_id, status, ce_result.message or "CE leg failed")
            if status == StrangleGroupStatus.RECOVERY_REQUIRED:
                self.pipeline.halt_new_entries("CE leg unknown state")
            return StrangleExecutionResult(False, status, ce_result.message, ce_result=ce_result, group_id=str(group_id))

        if not market_data_fresh_fn():
            await self.groups.update_status(group_id, StrangleGroupStatus.PARTIAL, last_error="Stale market data between legs")
            unwound = await self._emergency_unwind(
                group_id=group_id,
                trade=trade,
                leg=trade.ce_leg,
                ce_result=ce_result,
                instrument_id=ce_inst.instrument_id,
                symbol=ce_inst.symbol,
                quantity=trade.ce_leg.quantity if trade.ce_leg else 0,
                reason="STALE_DATA_BETWEEN_LEGS",
                runtime_status=runtime_status,
                market_data_fresh_fn=market_data_fresh_fn,
            )
            trade.state = StrategyState.FAILED_ENTRY
            if trade.ce_leg:
                trade.ce_leg.status = LegStatus.UNWOUND_ON_FAILURE if unwound else LegStatus.FAILED_ENTRY
            return StrangleExecutionResult(False, StrangleGroupStatus.UNWOUND if unwound else StrangleGroupStatus.UNWIND_FAILED, "Stale data between legs", ce_result=ce_result, group_id=str(group_id))

        pe_result = await self._submit_leg(
            group_id=group_id,
            trade=trade,
            leg=trade.pe_leg,
            inst=pe_inst,
            est=pe_est,
            client_order_id=pe_coid,
            signal_key=signal_key,
            leg_role="PE",
            runtime_status=runtime_status,
            market_data_fresh_fn=market_data_fresh_fn,
            submitted_status=StrangleGroupStatus.LEG_2_SUBMITTED,
            filled_status=StrangleGroupStatus.LEG_2_FILLED,
            failed_status=StrangleGroupStatus.LEG_2_FAILED,
        )

        if self._leg_succeeded(pe_result):
            await self.groups.update_status(group_id, StrangleGroupStatus.COMPLETE)
            if self.fill_bridge and trade.ce_leg and trade.pe_leg:
                from src.platform.persistence.fill_bridge import PlatformFillBridge

                await self.fill_bridge.record_strangle_entry(
                    trade=trade,
                    ce_result=ce_result,
                    pe_result=pe_result,
                    attribution=PlatformFillBridge.attribution_from_context(self.context),
                    exchange=self.context.exchange,
                )
            await self._verify_post_fill(group_id, trade, ce_result, pe_result)
            return StrangleExecutionResult(True, StrangleGroupStatus.COMPLETE, group_id=str(group_id), ce_result=ce_result, pe_result=pe_result)

        if pe_result.status == OrderLifecycleStatus.UNKNOWN:
            await self._fail_group(group_id, StrangleGroupStatus.RECOVERY_REQUIRED, "PE leg unknown")
            self.pipeline.halt_new_entries("PE leg unknown state")
            return StrangleExecutionResult(False, StrangleGroupStatus.RECOVERY_REQUIRED, pe_result.message, ce_result=ce_result, pe_result=pe_result, group_id=str(group_id))

        verified_pe = await self._verify_leg_on_exchange(pe_coid)
        if verified_pe and self._leg_succeeded(verified_pe):
            await self.groups.update_status(group_id, StrangleGroupStatus.COMPLETE)
            return StrangleExecutionResult(True, StrangleGroupStatus.COMPLETE, group_id=str(group_id), ce_result=ce_result, pe_result=verified_pe)

        self.logger.critical("Two-leg failure: CE ok, PE failed — emergency unwind CE")
        await self.groups.update_status(group_id, StrangleGroupStatus.UNWINDING, last_error="PE failed after CE filled")
        unwound = await self._emergency_unwind(
            group_id=group_id,
            trade=trade,
            leg=trade.ce_leg,
            ce_result=ce_result,
            instrument_id=ce_inst.instrument_id,
            symbol=ce_inst.symbol,
            quantity=trade.ce_leg.quantity if trade.ce_leg else 0,
            reason="PE_ENTRY_FAILED",
            runtime_status=runtime_status,
            market_data_fresh_fn=market_data_fresh_fn,
        )
        trade.state = StrategyState.FAILED_ENTRY
        if trade.ce_leg:
            trade.ce_leg.status = LegStatus.UNWOUND_ON_FAILURE if unwound else LegStatus.FAILED_ENTRY
        final = StrangleGroupStatus.UNWOUND if unwound else StrangleGroupStatus.UNWIND_FAILED
        if not unwound:
            self.pipeline.halt_new_entries("Emergency unwind failed")
            await self._log("strangle.unwind_failed", "CRITICAL", signal_key=signal_key, metadata={"reason": "PE_ENTRY_FAILED"})
        return StrangleExecutionResult(False, final, "PE failed — CE unwound" if unwound else "Unwind failed", ce_result=ce_result, pe_result=pe_result, group_id=str(group_id))

    async def _submit_leg(
        self,
        *,
        group_id: uuid.UUID,
        trade: StrategyTrade,
        leg,
        inst: Instrument,
        est: float,
        client_order_id: str,
        signal_key: str,
        leg_role: str,
        runtime_status: str,
        market_data_fresh_fn: Callable[[], bool],
        submitted_status: StrangleGroupStatus,
        filled_status: StrangleGroupStatus,
        failed_status: StrangleGroupStatus,
    ) -> ExecutionResult:
        existing = await self._resolve_existing_order(client_order_id)
        if existing:
            return existing

        await self.groups.update_status(group_id, submitted_status)
        intent = OrderIntent(
            signal_key=signal_key,
            client_order_id=client_order_id,
            symbol=inst.symbol,
            side="sell",
            quantity=leg.quantity if leg else 0,
            instrument_id=inst.instrument_id,
            metadata={
                "leg_id": leg.leg_id if leg else leg_role,
                "leg_role": leg_role,
                "estimated_premium": est,
                "group_id": str(group_id),
            },
        )
        result = await self.pipeline.process_intent(
            intent,
            runtime_status=runtime_status,
            market_data_fresh=market_data_fresh_fn(),
            group_id=group_id,
            leg_role=leg_role,
        )
        if self._leg_succeeded(result):
            await self.groups.update_status(group_id, filled_status)
        elif result.status == OrderLifecycleStatus.UNKNOWN:
            await self.groups.update_status(group_id, StrangleGroupStatus.RECOVERY_REQUIRED, last_error=result.message)
        else:
            await self.groups.update_status(group_id, failed_status, last_error=result.message)
        return result

    async def _resolve_existing_order(self, client_order_id: str) -> Optional[ExecutionResult]:
        adapter = self.pipeline._adapter
        if not adapter:
            return None
        try:
            row = await adapter.get_order(client_order_id)
            if not row:
                return None
            status_str = (row.get("status") or "").lower()
            if status_str in {"filled", "closed"}:
                return ExecutionResult(
                    success=True,
                    status=OrderLifecycleStatus.FILLED,
                    client_order_id=client_order_id,
                    exchange_order_id=str(row.get("order_id") or ""),
                    filled_quantity=float(row.get("filled_quantity") or row.get("quantity") or 0),
                    average_price=float(row["average_price"]) if row.get("average_price") else None,
                    message="Resolved existing exchange order",
                )
        except Exception:
            return None
        return None

    async def _verify_leg_on_exchange(self, client_order_id: str) -> Optional[ExecutionResult]:
        return await self._resolve_existing_order(client_order_id)

    async def _emergency_unwind(
        self,
        *,
        group_id: uuid.UUID,
        trade: StrategyTrade,
        leg,
        ce_result: Optional[ExecutionResult],
        instrument_id: str,
        symbol: str,
        quantity: float,
        reason: str,
        runtime_status: str,
        market_data_fresh_fn: Callable[[], bool],
    ) -> bool:
        unwind_coid = build_client_order_id(
            strategy_account_id=self.context.strategy_account_id,
            signal_key=f"unwind_{trade.strategy_trade_id}",
            leg_role="UNWIND",
            action="exit",
        )
        await self.groups.update_status(group_id, StrangleGroupStatus.UNWINDING, unwind_client_order_id=unwind_coid)
        intent = OrderIntent(
            signal_key=f"unwind_{trade.strategy_trade_id}",
            client_order_id=unwind_coid,
            symbol=symbol,
            side="buy",
            quantity=quantity,
            instrument_id=instrument_id,
            reduce_only=True,
            metadata={"allow_when_halted": True, "is_unwind": True, "reason": reason},
        )
        result = await self.pipeline.process_intent(
            intent,
            runtime_status=runtime_status,
            market_data_fresh=market_data_fresh_fn(),
            group_id=group_id,
            leg_role="UNWIND",
        )
        flat = await self._verify_position_flat(instrument_id, symbol)
        if flat and self._leg_succeeded(result):
            if leg and ce_result and ce_result.average_price and not leg.entry_fill_price:
                leg.entry_fill_price = ce_result.average_price
                leg.entry_order_id = ce_result.exchange_order_id
                leg.entry_client_order_id = ce_result.client_order_id
                leg.status = LegStatus.OPEN
                if self.fill_bridge:
                    await self.fill_bridge.ensure_attributed_leg_entry(
                        trade=trade,
                        leg=leg,
                        result=ce_result,
                        attribution=PlatformFillBridge.attribution_from_context(self.context),
                    )
            if self.exit_ledger and leg:
                await self.exit_ledger.persist_exit(
                    trade=trade,
                    leg=leg,
                    result=result,
                    exit_reason="EMERGENCY_UNWIND",
                    fee=float(result.fee or 0),
                )
            await self.groups.update_status(group_id, StrangleGroupStatus.UNWOUND, metadata_patch={"unwind_reason": reason})
            await self._log("strangle.unwound", "WARNING", signal_key=f"strangle_{trade.strategy_trade_id}", metadata={"reason": reason})
            return True
        await self.groups.update_status(group_id, StrangleGroupStatus.UNWIND_FAILED, last_error="Unwind verification failed")
        await self._log("strangle.unwind_failed", "CRITICAL", signal_key=f"strangle_{trade.strategy_trade_id}", metadata={"reason": reason})
        return False

    async def _verify_position_flat(self, instrument_id: str, symbol: str) -> bool:
        adapter = self.pipeline._adapter
        if not adapter:
            return True
        for _ in range(5):
            await asyncio.sleep(0.2)
            try:
                positions = await adapter.get_positions()
                matching = [p for p in positions if p.get("symbol") == symbol or p.get("instrument_id") == instrument_id]
                if not matching or abs(float(matching[0].get("size") or 0)) < 1e-9:
                    return True
            except Exception:
                pass
        return False

    async def _verify_post_fill(
        self,
        group_id: uuid.UUID,
        trade: StrategyTrade,
        ce_result: ExecutionResult,
        pe_result: ExecutionResult,
    ) -> None:
        adapter = self.pipeline._adapter
        if not adapter:
            return
        try:
            positions = await adapter.get_positions()
            symbols = {p.get("symbol") for p in positions if abs(float(p.get("size") or 0)) > 0}
            expected = set()
            if trade.ce_leg:
                expected.add(trade.ce_leg.symbol)
            if trade.pe_leg:
                expected.add(trade.pe_leg.symbol)
            if expected and not expected.issubset(symbols):
                self.pipeline.halt_new_entries("Post-fill position verification failed")
                await self.groups.update_status(group_id, StrangleGroupStatus.RECOVERY_REQUIRED, last_error="Post-fill position mismatch")
                await self._log("reconciliation.position_mismatch", "CRITICAL", signal_key=f"strangle_{trade.strategy_trade_id}")
        except Exception:
            pass

    async def _fail_group(self, group_id: uuid.UUID, status: StrangleGroupStatus, message: str) -> None:
        await self.groups.update_status(group_id, status, last_error=message)

    def _leg_succeeded(self, result: ExecutionResult) -> bool:
        return result.success and result.status in self.FILLED_STATUSES

    async def _log(self, event_type: str, severity: str, **kwargs) -> None:
        if not self.activity:
            return
        await self.activity.log(
            strategy_account_id=self.context.strategy_account_id,
            runtime_id=self.context.runtime_id,
            event_type=event_type,
            severity=severity,
            **kwargs,
        )
