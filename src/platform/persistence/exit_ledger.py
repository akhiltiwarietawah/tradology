"""Canonical platform exit fill attribution — all exit paths route here."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from src.core.models.order import Fill, OrderSide
from src.core.models.trade import LegStatus, StrategyLeg, StrategyTrade
from src.platform.execution.lifecycle_repository import OrderLifecycleRepository
from src.platform.execution.models import ExecutionResult, OrderLifecycleStatus
from src.platform.ledger.pnl import compute_leg_realized_pnl
from src.platform.persistence.fill_bridge import PlatformFillBridge
from src.persistence.trade_repository import TradeRepository

if TYPE_CHECKING:
    from src.platform.runtime.models import RuntimeContext
    from src.strategies.short_strangle.strategy import BTCShortStrangleStrategy


class PlatformExitLedger:
    """Apply attributed exit fills with idempotency and per-leg P&L."""

    def __init__(
        self,
        *,
        context: "RuntimeContext",
        strategy: Optional["BTCShortStrangleStrategy"],
        fill_bridge: PlatformFillBridge,
        lifecycle_repo: OrderLifecycleRepository,
        trade_repository: TradeRepository,
        logger: Optional[logging.Logger] = None,
    ):
        self.context = context
        self.strategy = strategy
        self.fill_bridge = fill_bridge
        self.lifecycle_repo = lifecycle_repo
        self.trades = trade_repository
        self.logger = logger or logging.getLogger("platform_exit_ledger")

    @staticmethod
    def stable_fill_id(result: ExecutionResult) -> str:
        if result.exchange_fill_id:
            return f"XFILL_{result.exchange_fill_id}"
        ex_id = result.exchange_order_id or result.client_order_id
        return f"FILL_EXIT_{ex_id}_{result.filled_quantity}_{result.average_price}"

    async def _resolve_intent_id(self, result: ExecutionResult) -> Optional[uuid.UUID]:
        if result.order_intent_id:
            return result.order_intent_id
        row = await self.lifecycle_repo.get_by_client_id(self.context.strategy_account_id, result.client_order_id)
        if row and row.get("id"):
            return row["id"]
        return await self.lifecycle_repo.get_intent_id(self.context.strategy_account_id, result.client_order_id)

    def _is_filled(self, result: ExecutionResult) -> bool:
        return result.success and result.status in {
            OrderLifecycleStatus.FILLED,
            OrderLifecycleStatus.WOULD_EXECUTE,
            OrderLifecycleStatus.PARTIALLY_FILLED,
        }

    async def persist_exit(
        self,
        *,
        trade: StrategyTrade,
        leg: StrategyLeg,
        result: ExecutionResult,
        exit_reason: str,
        fee: float = 0.0,
    ) -> bool:
        """
        Record one exit execution with full attribution.
        Returns True when a new economic fill was persisted (False if duplicate/no-op).
        """
        if not self._is_filled(result):
            return False
        if not result.average_price or result.filled_quantity <= 0:
            return False
        if leg.entry_fill_price is None:
            self.logger.warning("Exit skipped — leg has no entry fill price: %s", leg.leg_id)
            return False

        fill_id = self.stable_fill_id(result)
        if await self.trades.fill_exists(fill_id):
            return False

        intent_id = await self._resolve_intent_id(result)
        attribution = PlatformFillBridge.attribution_from_context(self.context).with_intent(intent_id)
        exit_qty = float(result.filled_quantity)
        exit_price = float(result.average_price)
        remaining = float(leg.quantity) - exit_qty

        if remaining > 1e-9:
            partial_pnl = compute_leg_realized_pnl(
                side="sell",
                entry_qty=Decimal(str(leg.quantity)),
                exit_qty=Decimal(str(exit_qty)),
                entry_price=Decimal(str(leg.entry_fill_price)),
                exit_price=Decimal(str(exit_price)),
                contract_value=Decimal(str(leg.contract_value)),
                fees=Decimal(str(fee)),
            )
            leg.realized_pnl = float(leg.realized_pnl or 0) + float(partial_pnl)
            leg.fees = float(leg.fees or 0) + fee
            leg.quantity = remaining
        elif self.strategy is not None:
            self.strategy.on_leg_closed(
                leg,
                exit_price=exit_price,
                exit_reason=exit_reason,
                exit_order_id=result.exchange_order_id,
                exit_client_order_id=result.client_order_id,
                fees=fee,
            )
        else:
            leg.exit_price = exit_price
            leg.exit_reason = exit_reason
            leg.fees = float(leg.fees or 0) + fee
            if exit_reason == "EMERGENCY_UNWIND":
                leg.status = LegStatus.UNWOUND_ON_FAILURE
            elif exit_reason == "STOP_LOSS":
                leg.status = LegStatus.STOPPED_OUT
            else:
                leg.status = LegStatus.FORCE_CLOSED
            if leg.entry_fill_price is not None:
                leg.realized_pnl = round(
                    (leg.entry_fill_price - exit_price) * leg.quantity * leg.contract_value - fee,
                    4,
                )

        trade.update_pnl()
        if self.strategy is not None:
            self.strategy.check_completion(trade)

        await self.fill_bridge.record_leg_exit(
            trade=trade,
            leg=leg,
            result=result,
            attribution=attribution,
            side=OrderSide.BUY,
            fee=fee,
            fill_id=fill_id,
        )
        return True

    async def persist_reconciled_exit(self, trade: StrategyTrade, leg: StrategyLeg) -> bool:
        """Persist exit detected by StateReconciler after restart (recovery path)."""
        if not leg.exit_price or leg.entry_fill_price is None:
            return False
        fill_id = f"RECON_EXIT_{leg.leg_id}_{leg.exit_price}_{leg.quantity}"
        if await self.trades.fill_exists(fill_id):
            return False

        result = ExecutionResult(
            success=True,
            status=OrderLifecycleStatus.FILLED,
            client_order_id=leg.sl_client_order_id or f"recon_{leg.leg_id}",
            exchange_order_id=leg.sl_order_id,
            filled_quantity=float(leg.quantity),
            average_price=float(leg.exit_price),
            message="Reconciliation recovery exit",
        )
        intent_id = await self.lifecycle_repo.get_intent_id(
            self.context.strategy_account_id,
            result.client_order_id,
        )
        result.order_intent_id = intent_id
        attribution = PlatformFillBridge.attribution_from_context(self.context).with_intent(intent_id)
        trade.update_pnl()
        if not trade.has_any_open_leg and trade.state.value != "COMPLETED":
            from src.core.models.trade import StrategyState

            trade.state = StrategyState.COMPLETED

        await self.fill_bridge.record_leg_exit(
            trade=trade,
            leg=leg,
            result=result,
            attribution=attribution,
            side=OrderSide.BUY,
            fee=float(leg.fees or 0),
            fill_id=fill_id,
        )
        return True
