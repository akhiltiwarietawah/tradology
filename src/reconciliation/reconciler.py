"""State reconciliation and manual trade isolation service."""

import logging
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime, timezone, timedelta
from src.core.interfaces.exchange import BaseExchangeAdapter
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.models.position import Position
from src.core.models.order import Order
from src.logging_utils.logger import TradeLogger


class ReconciliationResult:
    def __init__(self, is_synchronized: bool, status: str, details: Dict[str, Any]):
        self.is_synchronized = is_synchronized
        self.status = status
        self.details = details


class StateReconciler:
    """Reconciles local strategy state against exchange source of truth while isolating manual trades."""

    # Local entry_timestamp can be a few hundred ms after Delta's fill created_at.
    _FILL_LOOKBACK = timedelta(seconds=30)

    def __init__(
        self,
        exchange_adapter: BaseExchangeAdapter,
        trade_logger: Optional[TradeLogger] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.exchange = exchange_adapter
        self.trade_logger = trade_logger or TradeLogger()
        self.logger = logger or logging.getLogger("state_reconciler")
        self._reconcile_count: int = 0
        self._last_logged_summary: Optional[str] = None

    @staticmethod
    def _parse_iso_dt(raw: Optional[str]) -> Optional[datetime]:
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    @staticmethod
    def _fill_price(fill: Dict[str, Any]) -> Optional[float]:
        raw = fill.get("price")
        if raw in (None, "", 0, "0"):
            raw = fill.get("fill_price")
        try:
            px = float(raw or 0)
            return px if px > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fill_size(fill: Dict[str, Any]) -> float:
        try:
            return abs(float(fill.get("size") or fill.get("quantity") or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _fill_commission(fill: Dict[str, Any]) -> float:
        commission = fill.get("commission") or fill.get("fees") or 0.0
        try:
            return abs(float(commission))
        except (TypeError, ValueError):
            return 0.0

    def _fills_after_entry(self, fills: List[Dict[str, Any]], entry_ts: Optional[str]) -> List[Dict[str, Any]]:
        entry_dt = self._parse_iso_dt(entry_ts)
        cutoff = (entry_dt - self._FILL_LOOKBACK) if entry_dt else None
        out = []
        for fill in fills:
            fill_ts = fill.get("created_at") or fill.get("timestamp") or ""
            fill_dt = self._parse_iso_dt(str(fill_ts) if fill_ts else None)
            if cutoff and fill_dt and fill_dt < cutoff:
                continue
            if cutoff and fill_ts and fill_dt is None:
                try:
                    if str(fill_ts) < str(entry_ts):
                        continue
                except Exception:
                    pass
            out.append(fill)
        return out

    async def capture_leg_exit_fill(self, leg: StrategyLeg) -> Tuple[Optional[float], float, Optional[str]]:
        """
        Fetch actual post-entry BUY fills for this product from Delta.
        Returns (vwap_exit_price, total_fees_entry_plus_exit, latest_exit_timestamp).
        """
        start_time_us = None
        entry_dt = self._parse_iso_dt(leg.entry_timestamp)
        if entry_dt:
            start_time_us = int((entry_dt - self._FILL_LOOKBACK).timestamp() * 1_000_000)

        fills = await self.exchange.get_recent_fills_for_product(
            instrument_id=str(leg.instrument_id),
            side=None,
            page_size=50,
            start_time_us=start_time_us,
        )
        fills = self._fills_after_entry(fills, leg.entry_timestamp)
        buy_fills = [f for f in fills if str(f.get("side", "")).lower() == "buy"]
        sell_fills = [f for f in fills if str(f.get("side", "")).lower() == "sell"]

        if not buy_fills:
            return None, 0.0, None

        qty_sum = 0.0
        notional = 0.0
        exit_fees = 0.0
        latest_ts: Optional[str] = None
        latest_dt: Optional[datetime] = None
        for fill in buy_fills:
            px = self._fill_price(fill)
            sz = self._fill_size(fill)
            if not px or sz <= 0:
                continue
            qty_sum += sz
            notional += px * sz
            exit_fees += self._fill_commission(fill)
            ts = fill.get("created_at") or fill.get("timestamp")
            dt = self._parse_iso_dt(str(ts) if ts else None)
            if dt and (latest_dt is None or dt > latest_dt):
                latest_dt = dt
                latest_ts = str(ts)

        if qty_sum <= 0:
            return None, 0.0, None

        entry_fees = sum(self._fill_commission(f) for f in sell_fills)
        return round(notional / qty_sum, 8), round(entry_fees + exit_fees, 8), latest_ts

    async def reconcile(self, trade: Optional[StrategyTrade]) -> ReconciliationResult:
        """
        Reconcile local trade against live exchange positions and orders.
        
        Rules:
        1. Non-strategy positions on the account are ignored and left untouched.
        2. If a strategy leg was closed externally/manually, update leg state to MANUALLY_CLOSED.
        3. If state is fully consistent, return synchronized.
        4. If ambiguous discrepancy is detected on a strategy symbol, signal SAFE_HALT.
        """
        self._reconcile_count += 1
        is_routine = (self._reconcile_count > 1)

        # Routine periodic log is DEBUG; initial startup or state change is INFO
        if is_routine:
            self.logger.debug("Starting exchange state reconciliation...")
        else:
            self.logger.info("Starting exchange state reconciliation...")

        try:
            exchange_positions = await self.exchange.get_positions()
            open_orders = await self.exchange.get_open_orders()
        except Exception as e:
            self.logger.error(f"Failed to fetch exchange state during reconciliation: {e}", exc_info=True)
            return ReconciliationResult(
                is_synchronized=False,
                status="EXCHANGE_QUERY_FAILED",
                details={"error": str(e)},
            )

        positions_map: Dict[str, Position] = {p.instrument_id: p for p in exchange_positions if p.is_open}
        positions_by_sym: Dict[str, Position] = {p.symbol: p for p in exchange_positions if p.is_open}

        # Check for non-strategy / manual positions
        strategy_syms = set()
        if trade:
            if trade.ce_leg:
                strategy_syms.add(trade.ce_leg.symbol)
            if trade.pe_leg:
                strategy_syms.add(trade.pe_leg.symbol)

        manual_positions = [p for p in exchange_positions if p.is_open and p.symbol not in strategy_syms]
        if manual_positions:
            manual_syms = [p.symbol for p in manual_positions]
            if is_routine:
                self.logger.debug(f"Isolated {len(manual_positions)} unrelated manual position(s): {manual_syms}")
            else:
                self.logger.info(
                    f"Isolated {len(manual_positions)} unrelated manual position(s) on account ({manual_syms}). These will NOT be touched."
                )

        # If no active strategy trade locally
        if not trade or not trade.is_active:
            # Check if any strategy symbols have unexpected open positions or open orders
            if strategy_syms:
                unexp_positions = [p for p in exchange_positions if p.is_open and p.symbol in strategy_syms]
                if unexp_positions:
                    self.logger.critical(
                        f"🚨 RECONCILIATION ERROR: Local trade is not active, but exchange has open position(s) for strategy symbol(s): {[p.symbol for p in unexp_positions]}! Setting SAFE_HALT."
                    )
                    if trade:
                        trade.state = StrategyState.SAFE_HALT
                    return ReconciliationResult(
                        is_synchronized=False,
                        status="SAFE_HALT",
                        details={"reason": "UNEXPECTED_EXCHANGE_POSITION", "positions": [p.symbol for p in unexp_positions]},
                    )

                unexp_orders = [o for o in open_orders if o.symbol in strategy_syms]
                if unexp_orders:
                    self.logger.critical(
                        f"🚨 RECONCILIATION ERROR: Local trade is not active, but exchange has open order(s) for strategy symbol(s): {[o.symbol for o in unexp_orders]}! Setting SAFE_HALT."
                    )
                    if trade:
                        trade.state = StrategyState.SAFE_HALT
                    return ReconciliationResult(
                        is_synchronized=False,
                        status="SAFE_HALT",
                        details={"reason": "UNEXPECTED_OPEN_ORDER", "orders": [o.symbol for o in unexp_orders]},
                    )

            return ReconciliationResult(
                is_synchronized=True,
                status="CLEAN_IDLE",
                details={"manual_positions_count": len(manual_positions)},
            )

        # If we have an active strategy trade, check each leg
        discrepancies = []
        updated_legs = []

        # Build map of open stop / bracket orders by instrument_id and symbol
        bracket_orders_by_inst: Dict[str, Any] = {}
        for o in open_orders:
            # Check raw data or order attributes for bracket/stop orders
            is_bracket = getattr(o, "bracket_order", False) or (
                hasattr(o, "raw_data") and (
                    o.raw_data.get("bracket_order") is True or o.raw_data.get("stop_order_type") == "stop_loss_order"
                )
            )
            if is_bracket:
                bracket_orders_by_inst[str(o.instrument_id)] = o
                bracket_orders_by_inst[str(o.symbol)] = o

        # Helper to reconcile a single strategy leg
        async def _reconcile_leg(leg: StrategyLeg, leg_name: str):
            if not leg.is_open:
                return

            pos = positions_map.get(leg.instrument_id) or positions_by_sym.get(leg.symbol)
            if not pos or not pos.is_open:
                # Leg was closed externally (manual close via UI, bracket TP, or expiry)!
                # Query Delta /v2/fills for THIS specific instrument to get actual exit fill.
                # Filtering by product_id ensures manual fills on OTHER instruments never appear.
                self.logger.warning(
                    f"Reconciliation: {leg_name} leg {leg.symbol} is 0 on exchange. "
                    f"Fetching actual exit fill from Delta (product_id={leg.instrument_id})..."
                )

                actual_exit_price: Optional[float] = None
                actual_fees: float = 0.0
                exit_timestamp_str: Optional[str] = None

                try:
                    actual_exit_price, actual_fees, exit_timestamp_str = await self.capture_leg_exit_fill(leg)
                    if actual_exit_price:
                        self.logger.info(
                            f"Reconciliation: Captured actual exit fill for {leg.symbol}: "
                            f"price=${actual_exit_price:.2f}, fees=${actual_fees:.4f}"
                        )
                    else:
                        self.logger.warning(
                            f"Reconciliation: Could not find exit fill for {leg.symbol} on Delta. "
                            f"Realized P&L will be recorded as 0 — check Delta order history."
                        )
                except Exception as e:
                    self.logger.warning(
                        f"Reconciliation: Failed to fetch fills for {leg.symbol}: {e}. "
                        f"Marking MANUALLY_CLOSED without fill data."
                    )

                # Calculate realized P&L from actual fill price (short: sold high, bought back low = profit)
                realized = 0.0
                if actual_exit_price and leg.entry_fill_price and leg.entry_fill_price > 0:
                    realized = round(
                        (leg.entry_fill_price - actual_exit_price) * leg.quantity * leg.contract_value,
                        4,
                    )

                leg.status = LegStatus.MANUALLY_CLOSED
                leg.exit_reason = "EXCHANGE_CLOSE"
                leg.exit_price = actual_exit_price
                leg.exit_timestamp = exit_timestamp_str or leg.exit_timestamp
                leg.fees = actual_fees
                leg.realized_pnl = realized
                leg.exchange_sl_active = False
                updated_legs.append(leg.symbol)
                self.trade_logger.log_reconciliation_event(
                    f"{leg_name}_LEG_CLOSED_ON_EXCHANGE",
                    {
                        "symbol": leg.symbol,
                        "prev_status": "OPEN",
                        "new_status": "MANUALLY_CLOSED",
                        "exit_price": actual_exit_price,
                        "realized_pnl": realized,
                        "fees": actual_fees,
                    },
                )
                return

            # Check position direction (strategy requires SHORT options, pos.size < 0)
            if pos.size > 0:
                discrepancies.append(
                    f"{leg_name} unexpected LONG position on {leg.symbol}: actual size is {pos.size}"
                )
                return

            # Check quantity match / handle partial fills and reductions gracefully
            actual_qty = abs(pos.size)
            if abs(actual_qty - leg.quantity) > 1e-4:
                old_qty = leg.quantity
                leg.quantity = actual_qty
                self.logger.warning(
                    f"Reconciliation: Partial size change detected on {leg_name} leg {leg.symbol}: "
                    f"tracked quantity was {old_qty}, updated to exchange quantity {actual_qty}. Continuing safely."
                )
                updated_legs.append(leg.symbol)
                self.trade_logger.log_reconciliation_event(
                    f"{leg_name}_LEG_PARTIAL_SIZE_UPDATE",
                    {
                        "symbol": leg.symbol,
                        "old_quantity": old_qty,
                        "new_quantity": actual_qty,
                    },
                )

            # Check native exchange bracket SL order
            existing_bracket = bracket_orders_by_inst.get(str(leg.instrument_id)) or bracket_orders_by_inst.get(str(leg.symbol))
            if existing_bracket:
                bracket_id = str(existing_bracket.order_id)
                leg.bracket_order_id = bracket_id
                leg.sl_order_id = bracket_id
                leg.exchange_sl_active = True
                if is_routine:
                    self.logger.debug(f"Active exchange bracket SL verified for {leg.symbol} (Bracket ID: {bracket_id})")
                else:
                    self.logger.info(
                        f"Reconciliation: Active exchange bracket SL verified for {leg.symbol} (Bracket ID: {bracket_id})"
                    )
            else:
                # Position confirmed to be strategy leg, but native bracket is missing on exchange
                # Rule: ONLY recreate if persisted entry_fill_price and sl_price are valid and unambiguous
                target_sl = leg.sl_price or (leg.calculate_sl_price(1.0) if leg.entry_fill_price and leg.entry_fill_price > 0 else 0.0)
                if leg.entry_fill_price and leg.entry_fill_price > 0 and target_sl > 0:
                    self.logger.warning(
                        f"Reconciliation: Missing native bracket SL for {leg.symbol}. Persisted state is valid (Entry=${leg.entry_fill_price:.2f}, SL=${target_sl:.2f}). Attaching bracket..."
                    )
                    try:
                        res = await self.exchange.create_bracket_order(
                            instrument_id=leg.instrument_id,
                            stop_loss_price=target_sl,
                            stop_trigger_method="mark_price",
                        )
                        b_id = str(res.get("id") or res.get("order_id") or "")
                        leg.bracket_order_id = b_id
                        leg.sl_order_id = b_id
                        leg.sl_price = target_sl
                        leg.exchange_sl_active = True
                        self.logger.info(f"✅ Reattached missing native bracket SL for {leg.symbol} (ID: {b_id})")
                    except Exception as e:
                        discrepancies.append(f"Failed to reattach missing native bracket SL for {leg.symbol}: {e}")
                else:
                    # Ambiguous / corrupt state: do NOT guess SL price -> SAFE_HALT
                    discrepancies.append(
                        f"Missing native bracket SL for {leg.symbol} and persisted state is ambiguous/corrupt (entry={leg.entry_fill_price}, sl={leg.sl_price})"
                    )

        # Evaluate CE Leg
        if trade.ce_leg:
            await _reconcile_leg(trade.ce_leg, "CE")

        # Evaluate PE Leg
        if trade.pe_leg:
            await _reconcile_leg(trade.pe_leg, "PE")

        # If discrepancies detected that cannot be safely resolved -> SAFE_HALT
        if discrepancies:
            self.logger.critical(f"🚨 UNRESOLVABLE RECONCILIATION DISCREPANCY: {discrepancies}. Setting SAFE_HALT.")
            trade.state = StrategyState.SAFE_HALT
            return ReconciliationResult(
                is_synchronized=False,
                status="SAFE_HALT",
                details={"discrepancies": discrepancies},
            )

        # If both legs were closed externally, complete the trade and recalculate totals
        if not trade.has_any_open_leg and trade.state == StrategyState.ACTIVE:
            trade.state = StrategyState.COMPLETED
            # Recalculate trade-level P&L totals from actual leg data
            ce_realized = trade.ce_leg.realized_pnl if trade.ce_leg else 0.0
            pe_realized = trade.pe_leg.realized_pnl if trade.pe_leg else 0.0
            ce_fees = trade.ce_leg.fees if trade.ce_leg else 0.0
            pe_fees = trade.pe_leg.fees if trade.pe_leg else 0.0
            trade.total_realized_pnl = round(ce_realized + pe_realized, 4)
            trade.total_unrealized_pnl = 0.0  # Trade is now fully closed
            self.logger.info(
                f"All strategy legs closed externally. Trade {trade.strategy_trade_id} marked COMPLETED. "
                f"Total Realized P&L: ${trade.total_realized_pnl:.4f} "
                f"(CE: ${ce_realized:.4f}, PE: ${pe_realized:.4f}) | "
                f"Fees: CE=${ce_fees:.4f} PE=${pe_fees:.4f}"
            )

        if is_routine and not updated_legs:
            self.logger.debug("Reconciliation completed successfully.")
        else:
            self.logger.info("Reconciliation completed successfully.")
        return ReconciliationResult(
            is_synchronized=True,
            status="SYNCHRONIZED",
            details={"updated_legs": updated_legs, "manual_positions": len(manual_positions)},
        )
