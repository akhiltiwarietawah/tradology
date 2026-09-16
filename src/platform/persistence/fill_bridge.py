"""Bridge platform fills into the normalized trade ledger with full attribution."""

from __future__ import annotations

import logging
from typing import Optional

from src.core.models.order import Fill, Order, OrderSide, OrderState, OrderType
from src.core.models.trade import LegStatus, StrategyLeg, StrategyTrade, StrategyState
from src.persistence.trade_repository import TradeRepository
from src.platform.execution.models import ExecutionResult
from src.platform.ledger.models import PlatformAttribution
from src.platform.ledger.repository import PlatformLedgerRepository


class PlatformFillBridge:
    """Persist platform execution results into TradeRepository with tenant attribution."""

    def __init__(
        self,
        trade_repository: TradeRepository,
        ledger_repository: Optional[PlatformLedgerRepository] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.trades = trade_repository
        self.ledger = ledger_repository
        self.logger = logger or logging.getLogger("platform_fill_bridge")

    async def record_strangle_entry(
        self,
        *,
        trade: StrategyTrade,
        ce_result: ExecutionResult,
        pe_result: ExecutionResult,
        attribution: PlatformAttribution,
        exchange: str = "delta_india",
    ) -> None:
        ce_order = self._result_to_order(ce_result, trade.ce_leg, OrderSide.SELL)
        pe_order = self._result_to_order(pe_result, trade.pe_leg, OrderSide.SELL)
        if trade.ce_leg and ce_result.average_price:
            trade.ce_leg.entry_fill_price = ce_result.average_price
            trade.ce_leg.entry_order_id = ce_result.exchange_order_id
            trade.ce_leg.entry_client_order_id = ce_result.client_order_id
            trade.ce_leg.status = LegStatus.OPEN
        if trade.pe_leg and pe_result.average_price:
            trade.pe_leg.entry_fill_price = pe_result.average_price
            trade.pe_leg.entry_order_id = pe_result.exchange_order_id
            trade.pe_leg.entry_client_order_id = pe_result.client_order_id
            trade.pe_leg.status = LegStatus.OPEN
        trade.state = StrategyState.ACTIVE
        try:
            await self.trades.record_entry(
                trade,
                ce_order,
                pe_order,
                attribution=attribution,
                ce_order_intent_id=ce_result.order_intent_id,
                pe_order_intent_id=pe_result.order_intent_id,
            )
            await self._maybe_snapshot(attribution, trade)
        except Exception as exc:
            self.logger.warning("Fill bridge record_entry failed: %s", type(exc).__name__)

    async def ensure_attributed_leg_entry(
        self,
        *,
        trade: StrategyTrade,
        leg: StrategyLeg,
        result: ExecutionResult,
        attribution: PlatformAttribution,
    ) -> None:
        """Persist a single attributed leg entry when full strangle entry was not recorded."""
        from src.core.models.order import OrderSide

        if leg.entry_fill_price is None and result.average_price:
            leg.entry_fill_price = result.average_price
        leg.status = LegStatus.OPEN
        order = self._result_to_order(result, leg, OrderSide.SELL)
        try:
            await self.trades.upsert_trade(trade, attribution=attribution)
            await self.trades.upsert_leg(leg, trade_id=trade.strategy_trade_id)
            db_ord_id = await self.trades.upsert_order(
                order,
                trade_id=trade.strategy_trade_id,
                leg_id=leg.leg_id,
                attribution=attribution,
                strategy_order_intent_id=result.order_intent_id,
            )
            synth_fill = Fill(
                fill_id=f"FILL_ENTRY_{db_ord_id}_{result.filled_quantity}_{result.average_price}",
                order_id=db_ord_id,
                client_order_id=result.client_order_id,
                instrument_id=leg.instrument_id,
                symbol=leg.symbol,
                side=OrderSide.SELL,
                quantity=result.filled_quantity,
                price=result.average_price or 0,
                fee=0.0,
                fee_asset="USD",
                timestamp=leg.entry_timestamp,
            )
            await self.trades.upsert_fill(
                synth_fill,
                order_id=db_ord_id,
                attribution=attribution,
                strategy_order_intent_id=result.order_intent_id,
            )
        except Exception as exc:
            self.logger.warning("ensure_attributed_leg_entry failed: %s", type(exc).__name__)

    async def record_leg_exit(
        self,
        *,
        trade: StrategyTrade,
        leg: StrategyLeg,
        result: ExecutionResult,
        attribution: PlatformAttribution,
        side: OrderSide = OrderSide.BUY,
        fee: float = 0.0,
        fill_id: Optional[str] = None,
    ) -> None:
        exit_order = self._result_to_order(result, leg, side)
        intent_id = attribution.strategy_order_intent_id or result.order_intent_id
        exit_fill = Fill(
            fill_id=fill_id or f"FILL_EXIT_{exit_order.order_id}_{result.filled_quantity}_{result.average_price}",
            order_id=exit_order.order_id,
            client_order_id=result.client_order_id,
            instrument_id=leg.instrument_id,
            symbol=leg.symbol,
            side=side,
            quantity=result.filled_quantity,
            price=result.average_price or 0,
            fee=fee,
            fee_asset="USD",
            timestamp=leg.exit_timestamp,
        )
        try:
            await self.trades.record_leg_exit(
                leg,
                trade_id=trade.strategy_trade_id,
                exit_order=exit_order,
                exit_fills=[exit_fill],
                parent_trade=trade,
                attribution=attribution,
                strategy_order_intent_id=intent_id,
            )
            await self._maybe_snapshot(attribution, trade)
        except Exception as exc:
            self.logger.warning("Fill bridge record_leg_exit failed: %s", type(exc).__name__)

    async def _maybe_snapshot(self, attribution: PlatformAttribution, trade: StrategyTrade) -> None:
        if not self.ledger:
            return
        realized = float(getattr(trade, "total_realized_pnl", 0) or 0)
        fees = sum(float(getattr(leg, "fees", 0) or 0) for leg in (trade.ce_leg, trade.pe_leg) if leg)
        entry_prem = sum(
            float(getattr(leg, "entry_fill_price", 0) or 0) * float(getattr(leg, "quantity", 0) or 0)
            for leg in (trade.ce_leg, trade.pe_leg)
            if leg and getattr(leg, "entry_fill_price", None) is not None
        )
        await self.ledger.record_strategy_equity_snapshot(
            attribution,
            equity=max(entry_prem + realized - fees, 0),
            realized_pnl=realized,
            unrealized_pnl=0.0,
            fees=fees,
        )

    @staticmethod
    def _result_to_order(result: ExecutionResult, leg: Optional[StrategyLeg], side: OrderSide) -> Order:
        return Order(
            order_id=result.exchange_order_id or result.client_order_id,
            client_order_id=result.client_order_id,
            instrument_id=leg.instrument_id if leg else "",
            symbol=leg.symbol if leg else "",
            side=side,
            order_type=OrderType.MARKET,
            quantity=leg.quantity if leg else result.filled_quantity,
            filled_quantity=result.filled_quantity or (leg.quantity if leg else 0),
            average_fill_price=result.average_price,
            state=OrderState.FILLED if result.filled_quantity else OrderState.OPEN,
        )

    @staticmethod
    def attribution_from_context(context) -> PlatformAttribution:
        return PlatformAttribution(
            user_id=context.user_id,
            subscription_id=context.subscription_id,
            strategy_account_id=context.strategy_account_id,
            exchange_account_id=context.exchange_account_id,
            strategy_code=context.strategy_code,
        )
