"""Live runtime for ETHUSDT Renko + Ichimoku. Isolated account, orders, and state."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

from src.core.models.order import Order, OrderRequest, OrderSide, OrderState, OrderType
from src.core.models.position import Position
from src.execution.execution_engine import ExecutionEngine
from src.execution.order_manager import OrderManager
from src.strategies.renko_ichimoku.ichimoku import IncrementalIchimoku
from src.strategies.renko_ichimoku.params import RENKO_ICHIMOKU_FIXED_PARAMS
from src.strategies.renko_ichimoku.position_sizing import (
    apply_exit_to_sizing_equity,
    compute_realized_pnl_usd,
    contracts_from_sizing_equity,
    effective_equity_for_entry,
    is_valid_sizing_mode,
    margin_usd_from_equity,
)
from src.strategies.renko_ichimoku.prefix_logger import PrefixLogger
from src.strategies.renko_ichimoku.renko import TraditionalRenko, ConfirmedBrick
from src.strategies.renko_ichimoku.signals import evaluate_confirmed_brick, SignalAction
from src.strategies.renko_ichimoku.state import RenkoIchimokuState, RenkoIchimokuStateStore
from src.persistence.renko_trade_repository import make_renko_trade_id


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

    async def get_recent_fills_for_product(
        self,
        instrument_id: str,
        side: Optional[str] = None,
        page_size: int = 10,
        start_time_us: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        ...

    async def get_account_balances(self) -> Any:
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


def normalized_local_side(position: int) -> int:
    """Map persisted position to direction (-1/0/1). Legacy bad values like 10 -> 1."""
    if position in (-1, 0, 1):
        return position
    if position > 0:
        return 1
    if position < 0:
        return -1
    return 0


MANUAL_CLOSE_REASON = "Position manually closed (exchange flat, local state was open)."


def deterministic_client_order_id(brick_index: int, action_kind: str, instance_prefix: str = "") -> str:
    code = ACTION_CODES.get(action_kind, action_kind[:2].upper())
    prefix = (instance_prefix or "").upper()[:4]
    return f"RI{prefix}{int(brick_index)}{code}"[:32]


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
        fill_persister: Optional[Callable[..., Awaitable[None]]] = None,
        manual_close_persister: Optional[Callable[..., Awaitable[None]]] = None,
        contract_value: float = 0.01,
        box_size: float = RENKO_ICHIMOKU_FIXED_PARAMS.box_size,
        instance_id: str = "eth",
        strategy_code: str = "renko_ichimoku_eth",
        position_sizing_mode: str = "fixed",
        sizing_base_usd: float = 100.0,
        margin_pct: float = 0.25,
        leverage: float = 10.0,
        profit_retain_pct: float = 0.5,
    ):
        self.account_name = account_name
        self.instance_id = instance_id
        self.strategy_code = strategy_code
        self.box_size = float(box_size)
        self.configured_symbol = symbol
        self.symbol = symbol
        self.position_size = float(position_size)
        self.candle_resolution = candle_resolution
        self.order_id_prefix = instance_id.upper()[:4]
        self.execution_engine = execution_engine
        self.order_manager = order_manager
        self.candle_source = candle_source
        self.product_source = product_source
        self.exchange_ops = exchange_ops
        self.logger = PrefixLogger(logger, f"RENKO_{self.instance_id.upper()}")
        self.dry_run = dry_run
        self.kill_switch = kill_switch
        self.now_fn = now_fn
        self.allow_trade_on_warmup = allow_trade_on_warmup
        self.flatten = flatten
        self.fill_persister = fill_persister
        self.manual_close_persister = manual_close_persister
        self.contract_value = float(contract_value)
        self.position_sizing_mode = (position_sizing_mode or "fixed").strip().lower()
        self.sizing_base_usd = float(sizing_base_usd)
        self.margin_pct = float(margin_pct)
        self.leverage = float(leverage)
        self.profit_retain_pct = float(profit_retain_pct)
        self._last_position_reconcile_ts = 0.0
        self._pending_order_quantity: float = 0.0

        self.store = RenkoIchimokuStateStore(state_file, self.logger)
        self.state = self.store.load()
        self.state.account = account_name
        self.state.symbol = symbol

        self.renko = TraditionalRenko(box_size=self.box_size)
        self.ichimoku = IncrementalIchimoku()
        self.instrument_id: Optional[str] = self.state.instrument_id
        self._started = False
        self._trading_unlocked = False
        self.orders_placed: List[Order] = []

    @property
    def position(self) -> int:
        return self.state.position

    @property
    def is_dynamic_sizing(self) -> bool:
        return self.position_sizing_mode == "dynamic"

    def _expected_open_quantity(self) -> float:
        if self.is_dynamic_sizing and self.state.open_quantity is not None:
            return float(self.state.open_quantity)
        return float(self.position_size)

    async def _fetch_available_balance_usd(self) -> float:
        """Live USD available balance from the Renko exchange account."""
        if not self.exchange_ops:
            return 0.0
        getter = getattr(self.exchange_ops, "get_account_balances", None)
        if not callable(getter):
            return 0.0
        try:
            balances = await getter()
            usd = (balances.balances or {}).get("USD")
            if usd is not None:
                return max(0.0, float(usd.available_balance or 0.0))
        except Exception as e:
            self.logger.warning(f"Could not fetch account balance for sizing: {e}")
        return 0.0

    async def _sync_sizing_equity_from_account(self) -> None:
        """Initialize virtual sizing equity from SIZING_BASE_USD when not already in state."""
        if not self.is_dynamic_sizing:
            return
        if self.state.sizing_equity is None or self.state.sizing_equity <= 0:
            self.state.sizing_equity = self.sizing_base_usd
            self.logger.info(
                f"Dynamic sizing equity initialized to ${self.state.sizing_equity:.2f} "
                f"(RENKO_ICHIMOKU_SIZING_BASE_USD)."
            )

    async def _quantity_for_action(self, action_kind: str, brick: ConfirmedBrick) -> float:
        if action_kind in ("exit_long", "exit_short"):
            qty = self._expected_open_quantity()
            if qty <= 0:
                qty = float(self.position_size)
            return qty
        if not self.is_dynamic_sizing:
            return float(self.position_size)

        account_balance = await self._fetch_available_balance_usd()
        if self.state.sizing_equity is None or self.state.sizing_equity <= 0:
            self.state.sizing_equity = self.sizing_base_usd

        equity = effective_equity_for_entry(account_balance, self.state.sizing_equity)
        mark = float(brick.close)
        contracts = contracts_from_sizing_equity(
            equity,
            self.margin_pct,
            self.leverage,
            mark,
            self.contract_value,
        )
        margin, notional = margin_usd_from_equity(equity, self.margin_pct, self.leverage)
        self.logger.info(
            f"Dynamic sizing entry: account=${account_balance:.2f} virtual=${float(self.state.sizing_equity or 0):.2f} "
            f"effective=${equity:.2f} margin=${margin:.2f} ({self.margin_pct:.0%}) "
            f"notional=${notional:.2f} ({self.leverage:.0f}x) "
            f"price=${mark:.2f} contract_value={self.contract_value} -> {contracts} contracts"
        )
        return float(contracts)

    def _update_sizing_after_exit(
        self,
        entry_price: float,
        exit_price: float,
        quantity: float,
        position_side: int,
    ) -> None:
        if not self.is_dynamic_sizing:
            return
        pnl = compute_realized_pnl_usd(
            entry_price,
            exit_price,
            quantity,
            self.contract_value,
            position_side,
        )
        prev = float(self.state.sizing_equity or self.sizing_base_usd)
        new_eq = apply_exit_to_sizing_equity(prev, pnl, self.profit_retain_pct)
        self.state.last_realized_pnl = pnl
        self.state.sizing_equity = max(0.0, new_eq)
        retained = pnl * self.profit_retain_pct if pnl > 0 else pnl
        self.logger.info(
            f"Dynamic sizing exit pnl=${pnl:.4f} sizing_delta=${retained:.4f} "
            f"sizing_equity ${prev:.2f} -> ${self.state.sizing_equity:.2f} "
            f"(profit_retain_pct={self.profit_retain_pct})"
        )
        if self.state.sizing_equity <= 0:
            self._halt("Dynamic sizing equity <= 0 after exit. No further entries until funded.")

    def _halt(self, reason: str) -> None:
        self.state.orders_halted = True
        self.state.halt_reason = reason
        self._trading_unlocked = False
        self.logger.critical(f"ORDERS HALTED: {reason}")
        self.store.save(self.state)

    def _clear_reconcile_halt(self) -> None:
        """Resume after reconcile confirms local and exchange positions agree."""
        if not self.state.orders_halted:
            self._trading_unlocked = True
            return
        prev = self.state.halt_reason
        self.state.orders_halted = False
        self.state.halt_reason = None
        self._trading_unlocked = True
        self.logger.info(f"Exchange position reconcile OK. Trading resumed (was halted: {prev}).")
        self.store.save(self.state)

    async def start(self) -> None:
        if not is_valid_sizing_mode(self.position_sizing_mode):
            self._halt(
                f"Invalid position_sizing_mode={self.position_sizing_mode!r}. Use 'fixed' or 'dynamic'."
            )
            return
        if self.is_dynamic_sizing:
            if self.sizing_base_usd <= 0:
                self._halt("RENKO_ICHIMOKU_SIZING_BASE_USD must be > 0 for dynamic sizing.")
                return
            if not (0 < self.margin_pct <= 1):
                self._halt(f"RENKO_ICHIMOKU_MARGIN_PCT must be in (0, 1], got {self.margin_pct}.")
                return
            if self.leverage <= 0:
                self._halt(f"RENKO_ICHIMOKU_LEVERAGE must be > 0, got {self.leverage}.")
                return
            await self._sync_sizing_equity_from_account()
        else:
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
        raw = product.get("raw") or {}
        cv = raw.get("contract_value")
        if cv is not None:
            try:
                parsed_cv = float(cv)
                if parsed_cv > 0:
                    self.contract_value = parsed_cv
            except (TypeError, ValueError):
                pass
        self.state.instrument_id = self.instrument_id
        self.state.resolved_symbol = resolved_symbol
        sizing_note = (
            f"dynamic account-based equity=${float(self.state.sizing_equity or 0):.2f} "
            f"margin_pct={self.margin_pct} leverage={self.leverage}x retain={self.profit_retain_pct} "
            f"contract_value={self.contract_value}"
            if self.is_dynamic_sizing
            else f"fixed_size={self.position_size}"
        )
        self.logger.info(
            f"Started on account={self.account_name} configured_symbol={self.configured_symbol} "
            f"order_symbol={self.symbol} instrument_id={self.instrument_id} sizing={sizing_note} "
            f"resolution={self.candle_resolution} box={self.box_size} "
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
        if not self._started:
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
        order_qty = await self._quantity_for_action(action.kind, brick)
        if order_qty <= 0:
            if self.is_dynamic_sizing:
                self.logger.warning(
                    f"Dynamic sizing computed 0 contracts "
                    f"(virtual_equity={self.state.sizing_equity}, contract_value={self.contract_value}). "
                    "Signal logged, no order sent."
                )
            else:
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

        cid = deterministic_client_order_id(brick.index, action.kind, self.order_id_prefix)
        existing = self.order_manager.get_order_by_client_id(cid)
        if existing:
            self.logger.warning(f"Reusing existing local order for cid={cid} state={existing.state.value}")
            if existing.is_filled:
                self._apply_fill(action.kind, existing, brick)
                self._clear_in_flight()
                return True
            self._halt(f"Duplicate client_order_id {cid} without a local fill. Manual check required.")
            return False

        self._pending_order_quantity = float(order_qty)
        req = OrderRequest(
            instrument_id=self.instrument_id,
            symbol=self.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=self._pending_order_quantity,
            client_order_id=cid,
            strategy_id=self.strategy_code,
            leg_id=action.kind,
            reduce_only=reduce_only,
        )
        self.state.in_flight_client_order_id = cid
        self.state.in_flight_action = action.kind
        self.state.in_flight_brick_index = brick.index
        self.store.save(self.state)

        self.logger.info(
            f"Order submit action={action.kind} reason={action.reason} account={self.account_name} "
            f"symbol={self.symbol} instrument_id={self.instrument_id} qty={self._pending_order_quantity} "
            f"sizing_equity={self.state.sizing_equity} side={side.value} reduce_only={reduce_only} "
            f"cid={cid} brick={brick.index}"
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
                quantity=self._pending_order_quantity,
                filled_quantity=self._pending_order_quantity,
                state=OrderState.FILLED,
                strategy_id=self.strategy_code,
                average_fill_price=brick.close,
            )
            self.order_manager.record_order(order)
            await self._persist_fill(action, order, brick)
            self._apply_fill(action.kind, order, brick)
            self._clear_in_flight()
            self.store.save(self.state)
            return True
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
        requested = self._pending_order_quantity
        if order.state == OrderState.PARTIALLY_FILLED or (filled > 0 and filled + 1e-9 < requested and not order.is_filled):
            self._halt(
                f"Partial fill on {action.kind} cid={cid} order_id={order.order_id} "
                f"filled={filled} requested={requested}. Trading halted."
            )
            return False

        if not order.is_filled and filled <= 0:
            # Market order still open/pending: do not assume a fill.
            self._halt(
                f"Order {action.kind} cid={cid} order_id={order.order_id} state={order.state.value} "
                "is not filled. Trading halted."
            )
            return False

        await self._persist_fill(action, order, brick)
        self._apply_fill(action.kind, order, brick)
        self._clear_in_flight()
        self.store.save(self.state)
        return True

    async def _persist_fill(self, action: SignalAction, order: Order, brick: ConfirmedBrick) -> None:
        if not self.fill_persister:
            return
        try:
            await self.fill_persister(
                action_kind=action.kind,
                action_reason=action.reason,
                order=order,
                brick=brick,
                runtime=self,
            )
        except Exception as e:
            self.logger.warning(
                f"DATABASE: Renko fill persist failed (trading continues): {type(e).__name__}: {e}"
            )

    def _apply_fill(self, action_kind: str, order: Order, brick: ConfirmedBrick) -> None:
        fill_px = order.average_fill_price or brick.close
        filled_qty = float(order.filled_quantity or self._pending_order_quantity or 0.0)
        if action_kind in ("exit_long", "exit_short"):
            prev_side = 1 if action_kind == "exit_long" else -1
            entry_px = float(self.state.entry_price or fill_px)
            exit_qty = float(self.state.open_quantity or filled_qty or self._expected_open_quantity())
            self._update_sizing_after_exit(entry_px, float(fill_px), exit_qty, prev_side)
            self.state.position = 0
            self.state.entry_price = None
            self.state.entry_order_id = order.order_id
            self.state.active_trade_id = None
            self.state.entry_time = None
            self.state.open_quantity = None
        elif action_kind == "enter_long":
            self.state.position = 1
            self.state.entry_price = fill_px
            self.state.entry_order_id = order.order_id
            self.state.active_trade_id = make_renko_trade_id(brick.index, instance_id=self.instance_id)
            self.state.entry_time = self.now_fn()
            self.state.open_quantity = filled_qty
        elif action_kind == "enter_short":
            self.state.position = -1
            self.state.entry_price = fill_px
            self.state.entry_order_id = order.order_id
            self.state.active_trade_id = make_renko_trade_id(brick.index, instance_id=self.instance_id)
            self.state.entry_time = self.now_fn()
            self.state.open_quantity = filled_qty
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
        local_side = normalized_local_side(local)
        if local_side != local:
            self.logger.warning(
                f"Normalized invalid persisted position={local} to side={local_side}. "
                "position in state must be -1, 0, or 1 (direction only)."
            )
        self.logger.info(
            f"Reconcile local_pos={local} local_side={local_side} exchange_signed_size={signed} "
            f"symbol={self.symbol} instrument_id={self.instrument_id} account={self.account_name} "
            f"entry_order_id={self.state.entry_order_id}"
        )
        if local_side == 0 and ex_side == 0:
            self._clear_reconcile_halt()
            return
        if local_side != 0 and ex_side == 0:
            await self._sync_manual_close(local_side)
            return
        if local_side != 0 and ex_side != 0 and local_side != ex_side:
            self._halt(
                f"Position side mismatch local={local_side} exchange_signed={signed} ({self.symbol}). "
                "Opposite-side exposure on exchange. Manual intervention required."
            )
            return
        if local_side != 0 and ex_side == local_side:
            expected_qty = self._expected_open_quantity()
            if expected_qty > 0 and abs(abs(signed) - expected_qty) > 1e-6:
                self._halt(
                    f"Exchange size {signed} does not match expected open quantity={expected_qty} "
                    f"(mode={self.position_sizing_mode})."
                )
                return
            if local_side != local:
                self.state.position = local_side
                self.store.save(self.state)
            self._clear_reconcile_halt()
            return
        self._halt(
            f"Position mismatch local={local} exchange_signed={signed} ({self.symbol}). "
            "No orders until this is resolved. Same Delta account nets one position per contract; "
            "do not assume strategy-level isolation on the exchange."
        )

    async def _lookup_manual_close_fill(self, local_side: int) -> Optional[Dict[str, Any]]:
        if not self.exchange_ops or not self.instrument_id:
            return None
        getter = getattr(self.exchange_ops, "get_recent_fills_for_product", None)
        if not callable(getter):
            return None
        close_side = "sell" if local_side > 0 else "buy"
        start_time_us = None
        if self.state.entry_time:
            start_time_us = int(max(0.0, self.state.entry_time - 300.0) * 1_000_000)
        try:
            fills = await getter(
                instrument_id=self.instrument_id,
                side=close_side,
                page_size=20,
                start_time_us=start_time_us,
            )
        except Exception as e:
            self.logger.warning(f"Manual close fill lookup failed: {e}")
            return None
        if not fills:
            return None
        return self._pick_latest_fill(fills)

    @staticmethod
    def _pick_latest_fill(fills: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        best: Optional[Dict[str, Any]] = None
        best_ts = -1.0
        for fill in fills:
            ts_raw = fill.get("created_at") or fill.get("timestamp") or fill.get("time")
            ts = 0.0
            if ts_raw is not None:
                try:
                    ts = float(ts_raw)
                    if ts > 1e12:
                        ts /= 1_000_000.0
                except (TypeError, ValueError):
                    ts = 0.0
            if best is None or ts >= best_ts:
                best = fill
                best_ts = ts
        return best

    @staticmethod
    def _fill_price(fill: Dict[str, Any]) -> Optional[float]:
        for key in ("price", "fill_price", "avg_fill_price", "average_fill_price"):
            val = fill.get(key)
            if val is not None:
                try:
                    px = float(val)
                    if px > 0:
                        return px
                except (TypeError, ValueError):
                    continue
        return None

    async def _sync_manual_close(self, local_side: int) -> None:
        """Exchange is flat but local state still shows an open position (manual close)."""
        entry_order_id = self.state.entry_order_id
        close_fill = await self._lookup_manual_close_fill(local_side)
        exit_order_id = None
        exit_price = None
        if close_fill:
            exit_order_id = close_fill.get("order_id") or close_fill.get("id")
            exit_price = self._fill_price(close_fill)
            self.logger.info(
                f"Manual close fill found entry_order_id={entry_order_id} "
                f"exit_order_id={exit_order_id} exit_price={exit_price} fill={close_fill}"
            )
        else:
            self.logger.warning(
                f"No closing fill found on exchange for {self.symbol} since entry. "
                f"entry_order_id={entry_order_id}. Syncing local state to flat anyway."
            )

        prev_trade_id = self.state.active_trade_id
        prev_entry = self.state.entry_price
        prev_entry_time = self.state.entry_time
        prev_side = local_side
        prev_qty = float(self.state.open_quantity or self._expected_open_quantity())
        if prev_entry and exit_price and prev_qty > 0:
            self._update_sizing_after_exit(float(prev_entry), float(exit_price), prev_qty, prev_side)
        self.state.position = 0
        self.state.entry_price = None
        self.state.active_trade_id = None
        self.state.entry_time = None
        self.state.open_quantity = None
        if exit_order_id:
            self.state.entry_order_id = str(exit_order_id)
        self._clear_in_flight()
        self._clear_reconcile_halt()
        self.logger.warning(
            f"{MANUAL_CLOSE_REASON} entry_order_id={entry_order_id} "
            f"exit_order_id={exit_order_id} trade_id={prev_trade_id} symbol={self.symbol}"
        )
        self.store.save(self.state)

        if self.manual_close_persister:
            try:
                await self.manual_close_persister(
                    local_side=local_side,
                    entry_order_id=entry_order_id,
                    exit_order_id=str(exit_order_id) if exit_order_id else None,
                    exit_price=exit_price,
                    entry_price=prev_entry,
                    entry_time=prev_entry_time,
                    trade_id=prev_trade_id,
                    runtime=self,
                )
            except Exception as e:
                self.logger.warning(
                    f"DATABASE: manual close persist failed (local state already flat): "
                    f"{type(e).__name__}: {e}"
                )

    async def _clear_transient_reconcile_halt(self) -> None:
        """Backward-compatible alias for tests."""
        self._clear_reconcile_halt()

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
            strategy_id=self.strategy_code,
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
            "instance_id": self.instance_id,
            "strategy_code": self.strategy_code,
            "box_size": self.box_size,
            "account": self.account_name,
            "symbol": self.symbol,
            "configured_symbol": self.configured_symbol,
            "position": self.state.position,
            "entry_price": self.state.entry_price,
            "entry_order_id": self.state.entry_order_id,
            "active_trade_id": self.state.active_trade_id,
            "bricks": len(self.renko.bricks),
            "last_processed_candle_time": self.state.last_processed_candle_time,
            "instrument_id": self.instrument_id,
            "position_size": self.position_size,
            "position_sizing_mode": self.position_sizing_mode,
            "sizing_equity": self.state.sizing_equity,
            "open_quantity": self.state.open_quantity,
            "last_realized_pnl": self.state.last_realized_pnl,
            "margin_pct": self.margin_pct,
            "leverage": self.leverage,
            "profit_retain_pct": self.profit_retain_pct,
            "orders_halted": self.state.orders_halted,
            "halt_reason": self.state.halt_reason,
            "in_flight_client_order_id": self.state.in_flight_client_order_id,
        }
