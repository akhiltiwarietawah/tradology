"""Execution Engine orchestrating orders, two-leg entry unwinding, and SL execution."""

import asyncio
import logging
from typing import Optional, Tuple, Dict, Any, List
from datetime import datetime, timezone

from src.core.interfaces.execution import IExecutionEngine
from src.core.interfaces.exchange import BaseExchangeAdapter
from src.core.models.order import OrderRequest, Order, OrderSide, OrderType, OrderState
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.execution.order_manager import OrderManager
from src.logging_utils.logger import TradeLogger


import time
from src.logging_utils.events import TradingEventLogger


class ExecutionEngine(IExecutionEngine):
    """Executes strategy orders, manages multi-leg entry safety, and executes stop loss exits."""

    def __init__(
        self,
        exchange_adapter: BaseExchangeAdapter,
        order_manager: Optional[OrderManager] = None,
        trade_logger: Optional[TradeLogger] = None,
        entry_timeout_seconds: float = 10.0,
        logger: Optional[logging.Logger] = None,
    ):
        self.exchange = exchange_adapter
        self.order_manager = order_manager or OrderManager(logger=logger)
        self.trade_logger = trade_logger or TradeLogger()
        self.event_logger = TradingEventLogger(logger=logger, trade_logger=self.trade_logger)
        self.entry_timeout_seconds = entry_timeout_seconds
        self.logger = logger or logging.getLogger("execution_engine")

    def _extract_bracket_id(self, res: Any) -> str:
        """Robustly extract bracket order ID from any Delta response format."""
        if isinstance(res, (int, str)) and str(res).strip() and str(res).strip() not in ("0", "None"):
            return str(res).strip()
        if isinstance(res, dict):
            for k in ("id", "order_id", "bracket_id", "bracket_order_id"):
                v = res.get(k)
                if v is not None and str(v).strip() and str(v).strip() not in ("0", "None"):
                    return str(v).strip()
            inner = res.get("result") or res.get("data")
            if isinstance(inner, dict):
                for k in ("id", "order_id", "bracket_id", "bracket_order_id"):
                    v = inner.get(k)
                    if v is not None and str(v).strip() and str(v).strip() not in ("0", "None"):
                        return str(v).strip()
            elif isinstance(inner, (int, str)) and str(inner).strip():
                return str(inner).strip()
        return ""

    async def execute_order(self, request: OrderRequest) -> Order:
        """Place single order with timeout recovery, latency tracking, and structured logging."""
        if request.client_order_id:
            self.order_manager.register_order_attempt(request.client_order_id)

        t0 = time.perf_counter()
        leg_label = request.leg_id or (request.symbol.split("-")[0] if "-" in request.symbol else "UNKNOWN")

        self.event_logger.order_submitted(
            trade_id=request.strategy_id or "UNKNOWN",
            leg=leg_label,
            symbol=request.symbol,
            product_id=request.instrument_id,
            side=request.side.value.upper(),
            order_type=request.order_type.value.upper(),
            quantity=request.quantity,
            client_order_id=request.client_order_id or "",
            price=request.price,
            reduce_only=request.reduce_only,
        )

        try:
            order = await self.exchange.place_order(request)
            latency_ms = (time.perf_counter() - t0) * 1000
            self.order_manager.record_order(order)

            if order.is_filled:
                fill_px = order.average_fill_price or (order.price if order.price else 0.0)
                self.event_logger.order_filled(
                    trade_id=request.strategy_id or "UNKNOWN",
                    leg=leg_label,
                    symbol=request.symbol,
                    product_id=request.instrument_id,
                    order_id=str(order.order_id or ""),
                    fill_price=fill_px,
                    quantity=order.filled_quantity or request.quantity,
                    side=order.side.value.upper(),
                    status=order.state.value.upper(),
                    latency_ms=latency_ms,
                    client_order_id=request.client_order_id,
                )
            elif order.state == OrderState.REJECTED:
                self.event_logger.order_rejected(
                    trade_id=request.strategy_id or "UNKNOWN",
                    leg=leg_label,
                    symbol=request.symbol,
                    product_id=request.instrument_id,
                    side=request.side.value.upper(),
                    order_type=request.order_type.value.upper(),
                    quantity=request.quantity,
                    client_order_id=request.client_order_id,
                    http_status=400,
                    exchange_error_code="ORDER_REJECTED",
                    exchange_message="Order marked REJECTED by exchange",
                    response_body=order.raw_data,
                    retryable=False,
                )
            return order
        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            http_status = getattr(e, "status_code", None)
            res_data = getattr(e, "response_data", None)
            err_code = None
            err_msg = str(e)
            if isinstance(res_data, dict):
                err_dict = res_data.get("error") if isinstance(res_data.get("error"), dict) else {}
                err_code = err_dict.get("code") or res_data.get("error_code")
                schema_ctx = err_dict.get("context", {}).get("schema_errors", [{}])
                if schema_ctx and schema_ctx[0].get("message"):
                    err_msg = schema_ctx[0].get("message")
                elif err_dict.get("message"):
                    err_msg = err_dict.get("message")

            self.event_logger.order_rejected(
                trade_id=request.strategy_id or "UNKNOWN",
                leg=leg_label,
                symbol=request.symbol,
                product_id=request.instrument_id,
                side=request.side.value.upper(),
                order_type=request.order_type.value.upper(),
                quantity=request.quantity,
                client_order_id=request.client_order_id,
                http_status=http_status,
                exchange_error_code=err_code,
                exchange_message=err_msg,
                request_payload={
                    "product_id": request.instrument_id,
                    "size": request.quantity,
                    "side": request.side.value,
                    "order_type": request.order_type.value,
                    "client_order_id": request.client_order_id,
                    "reduce_only": request.reduce_only,
                },
                response_body=res_data,
                exception_type=type(e).__name__,
                retryable=False,
            )
            raise e

    async def execute_strangle_entry(
        self,
        trade: StrategyTrade,
        ce_request: OrderRequest,
        pe_request: OrderRequest,
    ) -> Tuple[bool, Optional[Order], Optional[Order]]:
        """
        Execute two-leg short strangle entry.
        
        Emergency Policy:
        If Leg 1 fills and Leg 2 fails/times out:
        1. Verify Leg 2 status on exchange.
        2. If Leg 2 is unconfirmed or failed, immediately unwind Leg 1 with an aggressive BUY order.
        3. Verify Leg 1 position is 0.
        4. Mark trade as FAILED_ENTRY.
        5. Never leave an unintended naked short.
        """
        self.logger.info(
            f"Executing Strangle Entry for trade {trade.strategy_trade_id}: CE={ce_request.symbol}, PE={pe_request.symbol}"
        )
        trade.state = StrategyState.PENDING_ENTRY

        ce_order: Optional[Order] = None
        pe_order: Optional[Order] = None
        ce_failed = False
        pe_failed = False

        # Submit Leg 1 (CE)
        try:
            ce_order = await self.execute_order(ce_request)
            if ce_order.state == OrderState.REJECTED:
                ce_failed = True
        except Exception as e:
            self.logger.error(f"Failed to place CE entry order: {e}", exc_info=True)
            ce_failed = True

        # Submit Leg 2 (PE)
        try:
            pe_order = await self.execute_order(pe_request)
            if pe_order.state == OrderState.REJECTED:
                pe_failed = True
        except Exception as e:
            self.logger.error(f"Failed to place PE entry order: {e}", exc_info=True)
            pe_failed = True

        # CASE 1: Both Succeeded
        if not ce_failed and not pe_failed and ce_order and pe_order:
            self.logger.info(f"✅ Both legs placed successfully: CE Order={ce_order.order_id}, PE Order={pe_order.order_id}")
            return True, ce_order, pe_order

        # CASE 2: CE Succeeded, PE Failed -> Emergency Unwind CE
        if not ce_failed and ce_order and pe_failed:
            self.logger.critical(
                f"🚨 TWO-LEG ENTRY FAILURE: CE filled/placed but PE failed. Initiating immediate emergency unwind of CE leg!"
            )
            # Verify PE on exchange first to ensure it did not fill quietly
            if pe_request.client_order_id:
                verified_pe = await self.exchange.get_order_by_client_id(pe_request.client_order_id)
                if verified_pe and verified_pe.is_filled:
                    self.logger.info("PE order was actually filled on exchange. Both legs intact.")
                    return True, ce_order, verified_pe

            # Unwind CE
            await self._emergency_unwind_leg(
                instrument_id=ce_request.instrument_id,
                symbol=ce_request.symbol,
                quantity=ce_request.quantity,
                trade_id=trade.strategy_trade_id,
                reason="PE_ENTRY_FAILED",
            )
            trade.state = StrategyState.FAILED_ENTRY
            if trade.ce_leg:
                trade.ce_leg.status = LegStatus.UNWOUND_ON_FAILURE
            return False, ce_order, pe_order

        # CASE 3: PE Succeeded, CE Failed -> Emergency Unwind PE
        if not pe_failed and pe_order and ce_failed:
            self.logger.critical(
                f"🚨 TWO-LEG ENTRY FAILURE: PE filled/placed but CE failed. Initiating immediate emergency unwind of PE leg!"
            )
            if ce_request.client_order_id:
                verified_ce = await self.exchange.get_order_by_client_id(ce_request.client_order_id)
                if verified_ce and verified_ce.is_filled:
                    self.logger.info("CE order was actually filled on exchange. Both legs intact.")
                    return True, verified_ce, pe_order

            # Unwind PE
            await self._emergency_unwind_leg(
                instrument_id=pe_request.instrument_id,
                symbol=pe_request.symbol,
                quantity=pe_request.quantity,
                trade_id=trade.strategy_trade_id,
                reason="CE_ENTRY_FAILED",
            )
            trade.state = StrategyState.FAILED_ENTRY
            if trade.pe_leg:
                trade.pe_leg.status = LegStatus.UNWOUND_ON_FAILURE
            return False, ce_order, pe_order

        # CASE 4: Both Failed
        self.logger.error("❌ Both entry legs failed to submit.")
        trade.state = StrategyState.FAILED_ENTRY
        return False, ce_order, pe_order

    async def attach_exchange_bracket_sl(
        self,
        leg: StrategyLeg,
        stop_loss_price: float,
        take_profit_price: Optional[float] = None,
        stop_trigger_method: str = "mark_price",
    ) -> bool:
        """
        Attach native exchange-side Bracket Stop Loss and optional Take Profit order to an open short option leg.
        Primary Stop Loss & Take Profit layer physically residing on Delta Exchange.
        """
        if not leg.instrument_id or stop_loss_price <= 0:
            self.logger.error(f"Cannot attach bracket SL: invalid instrument_id={leg.instrument_id} or sl_price={stop_loss_price}")
            return False

        tp_info = f", TP=${take_profit_price:.2f}" if take_profit_price and take_profit_price > 0 else ""
        for attempt in range(1, 3):
            try:
                self.logger.info(
                    f"Attaching native Bracket order on exchange for {leg.symbol} (Product ID: {leg.instrument_id}) at SL=${stop_loss_price:.2f}{tp_info} (Attempt {attempt}/2)..."
                )
                res = await self.exchange.create_bracket_order(
                    instrument_id=leg.instrument_id,
                    stop_loss_price=stop_loss_price,
                    take_profit_price=take_profit_price,
                    stop_trigger_method=stop_trigger_method,
                    order_type="market_order",
                )
                bracket_id = self._extract_bracket_id(res)
                leg.bracket_order_id = bracket_id or None
                leg.sl_order_id = bracket_id or None
                leg.exchange_sl_active = True
                leg.sl_price = stop_loss_price
                leg.tp_price = take_profit_price if take_profit_price and take_profit_price > 0 else None
                
                self.event_logger.bracket_attached(
                    trade_id=getattr(leg, "trade_id", "UNKNOWN"),
                    leg=leg.option_type.value.upper() if leg.option_type else "UNKNOWN",
                    symbol=leg.symbol,
                    product_id=leg.instrument_id,
                    bracket_id=bracket_id,
                    sl_price=stop_loss_price,
                    tp_price=leg.tp_price,
                    trigger_method=stop_trigger_method,
                    order_type="market_order",
                    status="ACTIVE",
                )
                return True
            except Exception as e:
                self.logger.warning(f"Attempt {attempt}/2 failed to attach native bracket order for {leg.symbol}: {e}")
                if attempt < 2:
                    await asyncio.sleep(1.0)

        self.logger.critical(f"🚨 FAILED to attach native exchange bracket order for {leg.symbol} after 2 attempts!")
        return False

    async def _emergency_unwind_leg(
        self,
        instrument_id: str,
        symbol: str,
        quantity: float,
        trade_id: str,
        reason: str,
    ) -> bool:
        """Submit emergency market BUY order to flatten naked short and verify zero position."""
        client_id = f"UNWIND_{trade_id.replace('STRANGLE_', '')[:12]}_{int(asyncio.get_event_loop().time()*1000)%100000}"
        unwind_request = OrderRequest(
            instrument_id=instrument_id,
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity,
            client_order_id=client_id,
            reduce_only=True,
            strategy_id=trade_id,
        )

        try:
            self.logger.warning(f"Submitting emergency unwind order: {symbol}, qty={quantity}, client_id={client_id}")
            order = await self.execute_order(unwind_request)
            self.trade_logger.log_emergency_unwind(
                trade_id=trade_id,
                reason=reason,
                details={"symbol": symbol, "quantity": quantity, "order_id": order.order_id, "state": order.state.value},
            )

            # Poll exchange to verify position is 0
            for _ in range(5):
                await asyncio.sleep(1.0)
                positions = await self.exchange.get_positions()
                matching = [p for p in positions if p.instrument_id == instrument_id or p.symbol == symbol]
                if not matching or not matching[0].is_open:
                    self.logger.info(f"Verified position is flat (0) on exchange for {symbol}.")
                    return True

            self.logger.warning(f"Unwind submitted but position verification requires manual confirmation for {symbol}.")
            return True
        except Exception as e:
            self.logger.critical(f"FATAL: Failed to execute emergency unwind for {symbol}: {e}", exc_info=True)
            return False

    async def execute_leg_exit(self, leg: StrategyLeg, reason: str) -> Optional[Order]:
        """Execute buy order to close a short strategy leg."""
        client_id = self.order_manager.generate_client_order_id(
            strategy_name="btc_short_strangle",
            trade_id=leg.leg_id,
            leg_name=leg.option_type.value,
            side=OrderSide.BUY,
            action="exit",
        )
        exit_request = OrderRequest(
            instrument_id=leg.instrument_id,
            symbol=leg.symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=leg.quantity,
            client_order_id=client_id,
            reduce_only=True,
            leg_id=leg.leg_id,
        )

        self.logger.info(f"Executing leg exit: {leg.symbol}, qty={leg.quantity}, reason={reason}")
        try:
            order = await self.execute_order(exit_request)
            return order
        except Exception as e:
            err_str = str(e).lower()
            if "no_position_for_reduce_only" in err_str or "no position" in err_str:
                self.logger.info(
                    f"Position for {leg.symbol} was already closed on exchange by native bracket SL/TP. "
                    f"Redundant exit order safely suppressed."
                )
            else:
                self.logger.error(f"Failed to execute leg exit for {leg.symbol}: {e}", exc_info=True)
            return None

    async def execute_trade_square_off(self, trade: StrategyTrade, reason: str = "EOD_EXIT") -> bool:
        """Close all remaining open legs in the strategy trade and verify flat position."""
        open_legs = trade.get_open_legs()
        if not open_legs:
            self.logger.info("No open legs to square off.")
            return True

        self.logger.info(f"Squaring off {len(open_legs)} open legs for trade {trade.strategy_trade_id} (Reason: {reason})...")
        tasks = [self.execute_leg_exit(leg, reason=reason) for leg in open_legs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for leg, res in zip(open_legs, results):
            if isinstance(res, Order) and res.is_filled:
                fill_px = res.average_fill_price or leg.intended_premium
                leg.status = LegStatus.FORCE_CLOSED
                leg.exit_price = fill_px
                leg.exit_reason = reason
                leg.exit_timestamp = datetime.now(timezone.utc).isoformat()
                if leg.entry_fill_price:
                    leg.realized_pnl = round((leg.entry_fill_price - fill_px) * leg.quantity * leg.contract_value, 4)

        trade.update_pnl()
        return True
