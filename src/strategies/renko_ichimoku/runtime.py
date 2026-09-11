"""Live runtime for ETHUSDT Renko + Ichimoku. Isolated account, orders, and state."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

from src.core.models.order import Order, OrderRequest, OrderSide, OrderState, OrderType
from src.core.models.position import Position
from src.execution.execution_engine import ExecutionEngine
from src.execution.order_manager import OrderManager
from src.strategies.renko_ichimoku.ichimoku import IncrementalIchimoku
from src.strategies.renko_ichimoku.params import RENKO_ICHIMOKU_FIXED_PARAMS
from src.strategies.renko_ichimoku.prefix_logger import PrefixLogger
from src.strategies.renko_ichimoku.renko import TraditionalRenko, ConfirmedBrick
from src.strategies.renko_ichimoku.signals import evaluate_confirmed_brick
from src.strategies.renko_ichimoku.state import RenkoIchimokuState, RenkoIchimokuStateStore


RESOLUTION_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}

ACTION_CODES = {
    "enter_long": "EL",
    "enter_short": "ES",
    "exit_long": "XL",
    "exit_short": "XS",
}


@dataclass
class ClosedCandle:
    time: float  # unix seconds, candle open
    close: float


class CandleSource(Protocol):
    async def fetch_closed_candles(self, symbol: str, resolution: str, limit: int) -> List[ClosedCandle]:
        ...


class ProductSource(Protocol):
    async def resolve_perpetual(self, symbol: str) -> Optional[Dict[str, Any]]:
        ...


class ExchangeOps(Protocol):
    async def get_positions(self) -> List[Position]:
        ...

    async def get_order_by_client_id(self, client_order_id: str) -> Optional[Order]:
        ...


def signed_position_size(pos: Position) -> float:
    """Delta may send signed size or absolute size + side."""
    size = float(pos.size or 0.0)
    raw = pos.raw_data or {}
    side = str(raw.get("side") or "").lower()
    if size < 0:
        return size
    if side in ("sell", "short"):
        return -abs(size)
    if side in ("buy", "long"):
        return abs(size)
    return size


def local_side_from_exchange(signed: float) -> int:
    if signed > 1e-9:
        return 1
    if signed < -1e-9:
        return -1
    return 0


def deterministic_client_order_id(brick_index: int, action_kind: str) -> str:
    code = ACTION_CODES.get(action_kind, action_kind[:2].upper())
    return f"RI{int(brick_index)}{code}"[:32]


POSITION_RECONCILE_INTERVAL_SECONDS = 30.0
TRANSIENT_RECONCILE_HALT_REASON = (
    "Could not read exchange positions for reconcile. Trading halted."
)


class RenkoIchimokuRuntime:
    """Independent strategy process living beside the existing short strangle."""

    TAG = "RENKO_ICHIMOKU"

    def __init__(
        self,
        account_name: str,
        symbol: str,
        position_size: float,
        candle_resolution: str,
        state_file: str,
        execution_engine: ExecutionEngine,
        order_manager: OrderManager,
        candle_source: CandleSource,
        product_source: ProductSource,
        logger: logging.Logger,
        dry_run: bool = False,
        kill_switch: bool = False,
        now_fn: Callable[[], float] = lambda: time.time(),
        allow_trade_on_warmup: bool = False,
        exchange_ops: Optional[ExchangeOps] = None,
        flatten: bool = False,
    ):
        self.account_name = account_name
        self.configured_symbol = symbol
        self.symbol = symbol
        self.position_size = float(position_size)
        self.candle_resolution = candle_resolution
        self.execution_engine = execution_engine
        self.order_manager = order_manager
        self.candle_source = candle_source
        self.product_source = product_source
        self.exchange_ops = exchange_ops
        self.logger = PrefixLogger(logger, self.TAG)
        self.dry_run = dry_run
        self.kill_switch = kill_switch
        self.now_fn = now_fn
        self.allow_trade_on_warmup = allow_trade_on_warmup
        self.flatten = flatten
        self._last_position_reconcile_ts = 0.0

        self.store = RenkoIchimokuStateStore(state_file, self.logger)
        self.state = self.store.load()
        self.state.account = account_name
        self.state.symbol = symbol

        self.renko = TraditionalRenko(box_size=RENKO_ICHIMOKU_FIXED_PARAMS.box_size)
        self.ichimoku = IncrementalIchimoku()
        self.instrument_id: Optional[str] = self.state.instrument_id
        self._started = False
        self._trading_unlocked = False
        self.orders_placed: List[Order] = []

    @property
    def position(self) -> int:
        return self.state.position

    def _halt(self, reason: str) -> None:
        self.state.orders_halted = True
        self.state.halt_reason = reason
        self._trading_unlocked = False
        self.logger.critical(f"ORDERS HALTED: {reason}")
        self.store.save(self.state)

    def _clear_transient_reconcile_halt(self) -> None:
        """Resume after a transient API/network reconcile failure once positions read OK."""
        if not self.state.orders_halted:
            return
        if self.state.halt_reason != TRANSIENT_RECONCILE_HALT_REASON:
            return
        self.state.orders_halted = False
        self.state.halt_reason = None
        self._trading_unlocked = True
        self.logger.info(
            "Exchange position reconcile recovered after transient failure. Renko trading resumed."
        )
        self.store.save(self.state)

    async def start(self) -> None:
        if self.position_size < 0:
            self._halt(f"RENKO_ICHIMOKU_POSITION_SIZE is negative ({self.position_size}).")
            return
        if self.position_size > 0 and abs(self.position_size - round(self.position_size)) > 1e-6:
            self._halt(
                f"RENKO_ICHIMOKU_POSITION_SIZE={self.position_size} is not a whole number of contracts."
            )
            return

        product = await self.product_source.resolve_perpetual(self.configured_symbol)
        if not product:
            self.logger.error(
                f"Could not resolve perpetual product for {self.configured_symbol}. Strategy will not trade."
            )
            self._halt(f"No perpetual product for {self.configured_symbol}")
            return
        itype = str(product.get("instrument_type") or "").lower()
        ctype = str(product.get("contract_type") or "").lower()
        if itype and itype != "perpetual":
            self._halt(f"Resolved product is not a perpetual (instrument_type={itype}).")
            return
        if ctype and "perpetual" not in ctype:
            self._halt(f"Resolved product is not a perpetual (contract_type={ctype}).")
            return
        resolved_symbol = str(product.get("symbol") or self.configured_symbol)
        if not product.get("exact_symbol_match", True):
            self.logger.warning(
                f"Configured symbol {self.configured_symbol} was not listed; using perpetual {resolved_symbol}."
            )
        self.symbol = resolved_symbol
        self.instrument_id = str(product.get("instrument_id") or product.get("id") or "")
        if not self.instrument_id:
            self._halt("Resolved perpetual is missing instrument_id.")
            return
        self.state.instrument_id = self.instrument_id
        self.state.resolved_symbol = resolved_symbol
        self.logger.info(
            f"Started on account={self.account_name} configured_symbol={self.configured_symbol} "
            f"order_symbol={self.symbol} instrument_id={self.instrument_id} size={self.position_size} "
            f"resolution={self.candle_resolution} box={RENKO_ICHIMOKU_FIXED_PARAMS.box_size} "
            f"Ichimoku {RENKO_ICHIMOKU_FIXED_PARAMS.tenkan}/{RENKO_ICHIMOKU_FIXED_PARAMS.kijun}/"
            f"{RENKO_ICHIMOKU_FIXED_PARAMS.span_b} disp={RENKO_ICHIMOKU_FIXED_PARAMS.cloud_displacement}"
        )

        await self._recover_in_flight_order()
        await self._warmup()

        if self.flatten:
            await self.flatten_position()
            self._halt("RENKO_ICHIMOKU_FLATTEN=true: flatten attempted; trading stays halted until flatten is false.")
            self._started = True
            self.store.save(self.state)
            return

        await self._reconcile_exchange_position()
        self._started = True
        if not self.state.orders_halted:
            self._trading_unlocked = True
        self.store.save(self.state)

    async def on_timer(self, now_ist: Optional[datetime] = None) -> None:
        if not self._started or self.state.orders_halted:
            return
        now = self.now_fn()
        if now - self._last_position_reconcile_ts >= POSITION_RECONCILE_INTERVAL_SECONDS:
            await self._reconcile_exchange_position()
            self._last_position_reconcile_ts = now
            if self.state.orders_halted:
                return
        try:
            candles = await self.candle_source.fetch_closed_candles(self.symbol, self.candle_resolution, 50)
        except Exception as e:
            self.logger.error(f"Candle fetch failed; skipping this tick (no orders): {e}")
            return
        if not candles:
            self.logger.warning("No closed candles returned; skipping this tick.")
            return
        step = RESOLUTION_SECONDS.get(self.candle_resolution, 900)
        newest_close_ts = candles[-1].time + step
        if self.now_fn() - newest_close_ts > 3 * step:
            self.logger.error(
                f"Stale market data: newest closed candle ended at {newest_close_ts}. Skipping tick."
            )
            return
        await self._process_closed_candles(candles, trade=True)
        self.store.save(self.state)

    async def _warmup(self) -> None:
        try:
            candles = await self.candle_source.fetch_closed_candles(self.symbol, self.candle_resolution, 2000)
        except Exception as e:
            self._halt(f"Warmup candle fetch failed: {e}")
            return
        persisted_position = self.state.position
        persisted_entry = self.state.entry_price
        persisted_oid = self.state.entry_order_id
        persisted_halt = self.state.orders_halted
        persisted_reason = self.state.halt_reason
        persisted_inflight = (
            self.state.in_flight_client_order_id,
            self.state.in_flight_action,
            self.state.in_flight_brick_index,
        )
        self.logger.info(f"Warmup: {len(candles)} closed candles. Rebuilding Renko/Ichimoku without placing orders.")
        await self._process_closed_candles(candles, trade=False)
        self.state.position = persisted_position
        self.state.entry_price = persisted_entry
        self.state.entry_order_id = persisted_oid
        self.state.orders_halted = persisted_halt
        self.state.halt_reason = persisted_reason
        self.state.in_flight_client_order_id = persisted_inflight[0]
        self.state.in_flight_action = persisted_inflight[1]
        self.state.in_flight_brick_index = persisted_inflight[2]
        if candles:
            self.state.last_processed_candle_time = candles[-1].time
            self.logger.info(
                f"last_processed_candle_time={self.state.last_processed_candle_time}. "
                "Historical bricks will not generate new entries after restart."
            )
        self.state.warmup_complete = True
        if self.renko.bricks:
            self.state.last_traded_brick_index = self.renko.bricks[-1].index
        self.logger.info(
            f"Warmup complete. bricks={len(self.renko.bricks)} persisted_position={self.state.position} "
            f"(will not recreate a position that is not in state)."
        )

    async def _process_closed_candles(self, candles: List[ClosedCandle], trade: bool) -> None:
        for candle in candles:
            if self.state.orders_halted and trade:
                return
            if trade and self.state.last_processed_candle_time is not None and candle.time <= self.state.last_processed_candle_time:
                continue
            new_bricks = self.renko.apply_close(candle.close, candle.time)
            for brick in new_bricks:
                snap = self.ichimoku.update(brick)
                if trade and self._trading_unlocked and not self.state.orders_halted:
                    await self._on_confirmed_brick(brick, snap)
                    if self.state.orders_halted:
                        return
            if trade or not self.state.warmup_complete:
                self.state.last_processed_candle_time = candle.time

    async def _on_confirmed_brick(self, brick: ConfirmedBrick, snap) -> None:
        if self.state.last_traded_brick_index == brick.index:
            self.logger.info(f"Skipping duplicate evaluation of brick {brick.index}")
            return
        actions = evaluate_confirmed_brick(self.state.position, brick, snap)
        if not actions:
            return
        self.logger.info(
            f"Signal brick_idx={brick.index} dir={brick.direction} close={brick.close} "
            f"kijun={snap.kijun} span_a={snap.span_a} span_b={snap.span_b} pos={self.state.position} "
            f"actions={[a.kind for a in actions]} account={self.account_name} symbol={self.symbol}"
        )
        for action in actions:
            ok = await self._execute_action(action, brick)
            if not ok:
                return
        self.state.last_traded_brick_index = brick.index
        self.state.last_brick_close = brick.close
        self.state.last_brick_direction = brick.direction
        self.store.save(self.state)

    async def _execute_action(self, action, brick: ConfirmedBrick) -> bool:
        """Return True if the logical action completed (or was intentionally skipped). False = halt/retry later."""
        if self.kill_switch and not str(action.kind).startswith("exit"):
            self.logger.warning("Kill switch set. Skipping new entry.")
            return True
        if self.position_size <= 0:
            self.logger.warning("RENKO_ICHIMOKU_POSITION_SIZE is 0. Signal logged, no order sent.")
            return True
        if not self.instrument_id:
            self._halt("No instrument_id; cannot place order.")
            return False

        if action.kind == "exit_long":
            side = OrderSide.SELL
            reduce_only = True
        elif action.kind == "exit_short":
            side = OrderSide.BUY
            reduce_only = True
        elif action.kind == "enter_long":
            side = OrderSide.BUY
            reduce_only = False
        elif action.kind == "enter_short":
            side = OrderSide.SELL
            reduce_only = False
        else:
            return True

        if self.kill_switch and reduce_only:
            self.logger.warning("Kill switch set. Reduce-only exit still allowed.")

        cid = deterministic_client_order_id(brick.index, action.kind)
        existing = self.order_manager.get_order_by_client_id(cid)
        if existing:
            self.logger.warning(f"Reusing existing local order for cid={cid} state={existing.state.value}")
            if existing.is_filled:
                self._apply_fill(action.kind, existing, brick)
                self._clear_in_flight()
                return True
            self._halt(f"Duplicate client_order_id {cid} without a local fill. Manual check required.")
            return False

        req = OrderRequest(
            instrument_id=self.instrument_id,
            symbol=self.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=self.position_size,
            client_order_id=cid,
            strategy_id="renko_ichimoku",
            leg_id=action.kind,
            reduce_only=reduce_only,
        )
        self.state.in_flight_client_order_id = cid
        self.state.in_flight_action = action.kind
        self.state.in_flight_brick_index = brick.index
        self.store.save(self.state)

        self.logger.info(
            f"Order submit action={action.kind} reason={action.reason} account={self.account_name} "
            f"symbol={self.symbol} instrument_id={self.instrument_id} qty={self.position_size} "
            f"side={side.value} reduce_only={reduce_only} cid={cid} brick={brick.index}"
        )
        if self.dry_run:
            self.logger.info("DRY_RUN: not sending order to exchange.")
            order = Order(
                order_id=f"dry-{cid}",
                client_order_id=cid,
                instrument_id=self.instrument_id,
                symbol=self.symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=self.position_size,
                filled_quantity=self.position_size,
                state=OrderState.FILLED,
                strategy_id="renko_ichimoku",
                average_fill_price=brick.close,
            )
            self.order_manager.record_order(order)
        else:
            try:
                order = await self.execution_engine.execute_order(req)
            except Exception as e:
                self.logger.error(
                    f"Order submit failed action={action.kind} cid={cid} error={type(e).__name__}: {e}"
                )
                self._halt(
                    f"Order {action.kind} cid={cid} raised {type(e).__name__}. "
                    "Not retrying a new order. Check exchange; in-flight cid is persisted."
                )
                return False

        self.orders_placed.append(order)
        self.logger.info(
            f"Order response action={action.kind} cid={cid} order_id={order.order_id} "
            f"state={order.state.value} filled_qty={order.filled_quantity} "
            f"avg_fill={order.average_fill_price} account={self.account_name} symbol={self.symbol}"
        )

        if order.state in (OrderState.REJECTED, OrderState.CANCELLED, OrderState.EXPIRED):
            self._clear_in_flight()
            self._halt(
                f"Order {action.kind} cid={cid} order_id={order.order_id} ended {order.state.value}. "
                "Position not updated."
            )
            return False

        filled = float(order.filled_quantity or 0.0)
        if order.state == OrderState.PARTIALLY_FILLED or (filled > 0 and filled + 1e-9 < self.position_size and not order.is_filled):
            self._halt(
                f"Partial fill on {action.kind} cid={cid} order_id={order.order_id} "
                f"filled={filled} requested={self.position_size}. Trading halted."
            )
            return False

        if not order.is_filled and filled <= 0:
            # Market order still open/pending: do not assume a fill.
            self._halt(
                f"Order {action.kind} cid={cid} order_id={order.order_id} state={order.state.value} "
                "is not filled. Trading halted."
            )
            return False

        self._apply_fill(action.kind, order, brick)
        self._clear_in_flight()
        self.store.save(self.state)
        return True

    def _apply_fill(self, action_kind: str, order: Order, brick: ConfirmedBrick) -> None:
        fill_px = order.average_fill_price or brick.close
        if action_kind in ("exit_long", "exit_short"):
            self.state.position = 0
            self.state.entry_price = None
            self.state.entry_order_id = order.order_id
        elif action_kind == "enter_long":
            self.state.position = 1
            self.state.entry_price = fill_px
            self.state.entry_order_id = order.order_id
        elif action_kind == "enter_short":
            self.state.position = -1
            self.state.entry_price = fill_px
            self.state.entry_order_id = order.order_id
        self.logger.info(
            f"Fill applied action={action_kind} new_pos={self.state.position} "
            f"fill_px={fill_px} order_id={order.order_id} cid={order.client_order_id}"
        )

    def _clear_in_flight(self) -> None:
        self.state.in_flight_client_order_id = None
        self.state.in_flight_action = None
        self.state.in_flight_brick_index = None

    async def _recover_in_flight_order(self) -> None:
        cid = self.state.in_flight_client_order_id
        action = self.state.in_flight_action
        if not cid or not action:
            return
        self.logger.warning(f"Recovering in-flight order cid={cid} action={action}")
        if not self.exchange_ops:
            self._halt(f"In-flight order cid={cid} on restart with no exchange lookup. Halted.")
            return
        try:
            order = await self.exchange_ops.get_order_by_client_id(cid)
        except Exception as e:
            self._halt(f"In-flight lookup failed for cid={cid}: {e}")
            return
        if order is None:
            self._halt(
                f"In-flight cid={cid} not found on exchange after restart. "
                "Not resubmitting. Confirm fills manually."
            )
            return
        self.logger.info(
            f"In-flight recovery cid={cid} order_id={order.order_id} state={order.state.value} "
            f"filled_qty={order.filled_quantity}"
        )
        if order.is_filled:
            brick = ConfirmedBrick(
                index=int(self.state.in_flight_brick_index or 0),
                timestamp=0.0,
                open=0.0,
                high=0.0,
                low=0.0,
                close=float(order.average_fill_price or 0.0),
                direction=0,
                source_bar_index=0,
            )
            self._apply_fill(action, order, brick)
            self._clear_in_flight()
            return
        if order.state in (OrderState.REJECTED, OrderState.CANCELLED, OrderState.EXPIRED):
            self._clear_in_flight()
            self._halt(f"In-flight cid={cid} recovered as {order.state.value}. No position update.")
            return
        self._halt(
            f"In-flight cid={cid} still {order.state.value} after restart. Trading halted."
        )

    async def _exchange_signed_size(self) -> Optional[float]:
        if not self.exchange_ops or not self.instrument_id:
            return None
        try:
            positions = await self.exchange_ops.get_positions()
        except Exception as e:
            self.logger.error(f"get_positions failed: {e}")
            return None
        total = 0.0
        for pos in positions:
            if str(pos.instrument_id) == str(self.instrument_id) or str(pos.symbol).upper() == self.symbol.upper():
                total += signed_position_size(pos)
        return total

    async def _reconcile_exchange_position(self) -> None:
        if self.dry_run or not self.exchange_ops:
            self.logger.info("Skipping exchange position reconcile (dry_run or no exchange_ops).")
            return
        signed = await self._exchange_signed_size()
        if signed is None:
            self._halt(TRANSIENT_RECONCILE_HALT_REASON)
            return
        ex_side = local_side_from_exchange(signed)
        local = self.state.position
        self.logger.info(
            f"Reconcile local_pos={local} exchange_signed_size={signed} "
            f"symbol={self.symbol} instrument_id={self.instrument_id} account={self.account_name}"
        )
        if local == 0 and ex_side == 0:
            self._clear_transient_reconcile_halt()
            return
        if local != 0 and ex_side == local:
            if self.position_size > 0 and abs(abs(signed) - self.position_size) > 1e-6:
                self._halt(
                    f"Exchange size {signed} does not match RENKO_ICHIMOKU_POSITION_SIZE={self.position_size}."
                )
                return
            self._clear_transient_reconcile_halt()
            return
        self._halt(
            f"Position mismatch local={local} exchange_signed={signed} ({self.symbol}). "
            "No orders until this is resolved. Same Delta account nets one position per contract; "
            "do not assume strategy-level isolation on the exchange."
        )

    async def flatten_position(self) -> bool:
        """Reduce-only close of the *exchange* Renko instrument. Does not use historical signals."""
        if self.dry_run:
            self.logger.warning("DRY_RUN flatten: not sending orders. Local state left unchanged.")
            return False
        if not self.instrument_id:
            self.logger.error("Cannot flatten: no instrument_id.")
            return False
        if self.exchange_ops:
            signed = await self._exchange_signed_size()
            if signed is None:
                self._halt("Flatten aborted: could not read exchange position.")
                return False
        else:
            signed = float(self.state.position) * self.position_size
        if abs(signed) <= 1e-9:
            self.logger.info("Flatten: exchange position already flat.")
            self.state.position = 0
            self.state.entry_price = None
            self._clear_in_flight()
            self.store.save(self.state)
            return True
        qty = abs(round(signed))
        if qty <= 0:
            self._halt("Flatten aborted: non-whole exchange size.")
            return False
        side = OrderSide.SELL if signed > 0 else OrderSide.BUY
        cid = f"RIFLAT{int(self.now_fn())}"[:32]
        req = OrderRequest(
            instrument_id=self.instrument_id,
            symbol=self.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=float(qty),
            client_order_id=cid,
            strategy_id="renko_ichimoku",
            leg_id="flatten",
            reduce_only=True,
        )
        self.logger.info(
            f"Flatten submit account={self.account_name} symbol={self.symbol} "
            f"instrument_id={self.instrument_id} qty={qty} side={side.value} cid={cid}"
        )
        try:
            order = await self.execution_engine.execute_order(req)
        except Exception as e:
            self._halt(f"Flatten order failed: {e}")
            return False
        self.logger.info(
            f"Flatten response order_id={order.order_id} state={order.state.value} "
            f"filled_qty={order.filled_quantity} cid={cid}"
        )
        if not order.is_filled:
            self._halt(f"Flatten did not fully fill (state={order.state.value}).")
            return False
        self.state.position = 0
        self.state.entry_price = None
        self.state.entry_order_id = order.order_id
        self._clear_in_flight()
        self.store.save(self.state)
        return True

    def snapshot(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "account": self.account_name,
            "symbol": self.symbol,
            "configured_symbol": self.configured_symbol,
            "position": self.state.position,
            "entry_price": self.state.entry_price,
            "entry_order_id": self.state.entry_order_id,
            "bricks": len(self.renko.bricks),
            "last_processed_candle_time": self.state.last_processed_candle_time,
            "instrument_id": self.instrument_id,
            "position_size": self.position_size,
            "orders_halted": self.state.orders_halted,
            "halt_reason": self.state.halt_reason,
            "in_flight_client_order_id": self.state.in_flight_client_order_id,
        }
