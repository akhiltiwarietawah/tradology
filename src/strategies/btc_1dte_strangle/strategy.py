"""BTC 1-DTE short strangle — 10:45–11:00 PM IST entry, parso 17:25 IST exit, 100% leg SL."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable, List, Optional

from src.config.constants import IST_TIMEZONE
from src.core.interfaces.exchange import BaseExchangeAdapter
from src.core.models.instrument import Instrument, OptionType
from src.core.models.market_data import Ticker
from src.core.models.trade import LegStatus, StrategyLeg, StrategyState, StrategyTrade
from src.strategies.base.strategy import BaseStrategy
from src.strategies.btc_1dte_strangle.models import Btc1DteStrangleConfig
from src.strategies.btc_1dte_strangle.sizing import contracts_for_strangle, scaled_take_profit
from src.strategies.btc_1dte_strangle.strike_selection import StrikeSelectionError, select_1dte_strangle_legs


class BTC1DteShortStrangleStrategy(BaseStrategy):
    """Parso-expiry short strangle with per-leg 100% bracket SL; optional combined USD TP."""

    def __init__(
        self,
        exchange_adapter: BaseExchangeAdapter,
        config: Optional[Btc1DteStrangleConfig] = None,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(
            strategy_name="btc_1dte_strangle",
            exchange_adapter=exchange_adapter,
            logger=logger,
        )
        self.config = config or Btc1DteStrangleConfig()
        self._last_tick_time: float = 0.0
        self._last_entry_attempt_time: float = 0.0
        self._entry_retry_count: int = 0
        self._entry_retry_date: Optional[str] = None
        self._combined_tp_usd: float = self.config.take_profit_base_usd
        self._tp_triggered: bool = False

        self._on_entry_trigger: Optional[
            Callable[[StrategyTrade, Instrument, Instrument, float, float], Awaitable[None]]
        ] = None
        self._on_sl_trigger: Optional[Callable[[StrategyLeg, float], Awaitable[None]]] = None
        self._on_tp_trigger: Optional[Callable[[StrategyTrade], Awaitable[None]]] = None
        self._on_exit_trigger: Optional[Callable[[StrategyTrade], Awaitable[None]]] = None
        self._resolve_quantity: Optional[Callable[[float, float], Awaitable[int]]] = None

    def record_entry_attempt(self, now_ist: Optional[datetime] = None, timestamp: Optional[float] = None):
        import time as _time

        dt = now_ist or datetime.now(IST_TIMEZONE)
        today_str = dt.strftime("%Y-%m-%d")
        if self._entry_retry_date != today_str:
            self._entry_retry_date = today_str
            self._entry_retry_count = 0
        self._entry_retry_count += 1
        self._last_entry_attempt_time = timestamp if timestamp is not None else _time.time()

    def set_execution_callbacks(
        self,
        on_entry: Callable[[StrategyTrade, Instrument, Instrument, float, float], Awaitable[None]],
        on_sl: Callable[[StrategyLeg, float], Awaitable[None]],
        on_exit: Callable[[StrategyTrade], Awaitable[None]],
        on_tp: Optional[Callable[[StrategyTrade], Awaitable[None]]] = None,
        resolve_quantity: Optional[Callable[[float, float], Awaitable[int]]] = None,
    ):
        self._on_entry_trigger = on_entry
        self._on_sl_trigger = on_sl
        self._on_exit_trigger = on_exit
        self._on_tp_trigger = on_tp
        self._resolve_quantity = resolve_quantity

    @staticmethod
    def target_expiry_date(entry_ist: datetime, calendar_days: int) -> datetime.date:
        return entry_ist.astimezone(IST_TIMEZONE).date() + timedelta(days=calendar_days)

    def is_entry_window(self, now_ist: Optional[datetime] = None) -> bool:
        dt = now_ist or datetime.now(IST_TIMEZONE)
        current_time = dt.time()
        start_time = self.config.entry_time
        start_dt = datetime.combine(dt.date(), start_time)
        end_dt = start_dt + timedelta(minutes=self.config.entry_window_minutes)
        return start_time <= current_time <= end_dt.time()

    def should_force_exit(self, now_ist: datetime, trade: StrategyTrade) -> bool:
        """5:25 PM IST on parso expiry day (entry date + expiry_calendar_days)."""
        try:
            entry_day = datetime.strptime(trade.trade_date, "%Y-%m-%d").date()
        except ValueError:
            return False
        expiry_day = entry_day + timedelta(days=self.config.expiry_calendar_days)
        local = now_ist.astimezone(IST_TIMEZONE)
        if local.date() < expiry_day:
            return False
        if local.date() > expiry_day:
            return True
        return local.time() >= self.config.exit_time

    def can_enter_today(
        self,
        now_ist: Optional[datetime] = None,
        history: Optional[List[StrategyTrade]] = None,
        current_timestamp: Optional[float] = None,
    ) -> bool:
        import time as _time

        dt = now_ist or datetime.now(IST_TIMEZONE)
        today_str = dt.strftime("%Y-%m-%d")

        if not self.is_entry_window(dt):
            return False

        if self._entry_retry_date != today_str:
            self._entry_retry_date = today_str
            self._entry_retry_count = 0

        if self._entry_retry_count >= self.config.max_entry_retries:
            return False

        now_ts = current_timestamp if current_timestamp is not None else _time.time()
        if self._last_entry_attempt_time > 0 and (
            now_ts - self._last_entry_attempt_time
        ) < self.config.entry_retry_cooldown_seconds:
            return False

        if self._current_trade is not None and self._current_trade.trade_date == today_str:
            if self._current_trade.state in (
                StrategyState.ACTIVE,
                StrategyState.COMPLETED,
                StrategyState.PENDING_ENTRY,
                StrategyState.PENDING_EXIT,
                StrategyState.SAFE_HALT,
            ):
                return False
            if self._current_trade.state == StrategyState.FAILED_ENTRY and self._current_trade.has_any_fill_or_order:
                return False

        if history:
            for trade in history:
                if trade.trade_date == today_str:
                    if trade.state in (
                        StrategyState.ACTIVE,
                        StrategyState.COMPLETED,
                        StrategyState.PENDING_EXIT,
                        StrategyState.SAFE_HALT,
                    ) or trade.has_any_fill_or_order:
                        return False

        return True

    async def _resolve_contracts(self, ce_est: float, pe_est: float) -> float:
        if self._resolve_quantity:
            qty = await self._resolve_quantity(ce_est, pe_est)
            return max(0.0, float(qty))
        return 1.0

    async def create_trade(
        self,
        spot_price: float,
        ce_inst: Instrument,
        pe_inst: Instrument,
        ce_est_prem: float,
        pe_est_prem: float,
        now_ist: Optional[datetime] = None,
    ) -> StrategyTrade:
        dt = now_ist or datetime.now(IST_TIMEZONE)
        timestamp_str = dt.strftime("%Y%m%d_%H%M%S")
        trade_date_str = dt.strftime("%Y-%m-%d")
        trade_id = f"BTC1DTE_{timestamp_str}"
        expiry = self.target_expiry_date(dt, self.config.expiry_calendar_days)
        expiry_str = expiry.strftime("%d%m%y")

        qty = await self._resolve_contracts(ce_est_prem, pe_est_prem)
        if qty <= 0:
            raise StrikeSelectionError("Computed contract size is zero (check equity / margin settings)")

        if self.config.enable_combined_take_profit:
            self._combined_tp_usd = scaled_take_profit(
                int(qty),
                base_usd=self.config.take_profit_base_usd,
                calibration_contracts=self.config.take_profit_calibration_contracts,
            )
        else:
            self._combined_tp_usd = 0.0
        self._tp_triggered = False

        ce_leg = StrategyLeg(
            leg_id=f"CE_{timestamp_str}",
            option_type=OptionType.CALL,
            instrument_id=ce_inst.instrument_id,
            symbol=ce_inst.symbol,
            strike=ce_inst.strike_price or 0.0,
            expiry_date=expiry_str,
            quantity=qty,
            contract_value=ce_inst.contract_value,
            intended_premium=ce_est_prem,
            status=LegStatus.PENDING_ENTRY,
        )
        pe_leg = StrategyLeg(
            leg_id=f"PE_{timestamp_str}",
            option_type=OptionType.PUT,
            instrument_id=pe_inst.instrument_id,
            symbol=pe_inst.symbol,
            strike=pe_inst.strike_price or 0.0,
            expiry_date=expiry_str,
            quantity=qty,
            contract_value=pe_inst.contract_value,
            intended_premium=pe_est_prem,
            status=LegStatus.PENDING_ENTRY,
        )

        trade = StrategyTrade(
            strategy_trade_id=trade_id,
            strategy_name=self.strategy_name,
            trade_date=trade_date_str,
            underlying_spot_at_entry=spot_price,
            ce_leg=ce_leg,
            pe_leg=pe_leg,
            state=StrategyState.PENDING_ENTRY,
            created_at=dt.isoformat(),
            updated_at=dt.isoformat(),
        )
        self._current_trade = trade
        tp_msg = f" combined TP=${self._combined_tp_usd:.2f}" if self.config.enable_combined_take_profit else ""
        self.logger.info(f"1-DTE trade planned: qty={qty:.0f}{tp_msg} expiry={expiry_str}")
        return trade

    def on_entry_filled(
        self,
        trade: StrategyTrade,
        ce_fill_price: float,
        pe_fill_price: float,
        ce_order_id: str,
        pe_order_id: str,
        ce_client_order_id: str,
        pe_client_order_id: str,
        now_ist: Optional[datetime] = None,
    ):
        dt = (now_ist or datetime.now(IST_TIMEZONE)).isoformat()

        if trade.ce_leg:
            trade.ce_leg.entry_fill_price = ce_fill_price
            trade.ce_leg.current_price = ce_fill_price
            trade.ce_leg.entry_order_id = ce_order_id
            trade.ce_leg.entry_client_order_id = ce_client_order_id
            trade.ce_leg.entry_timestamp = dt
            trade.ce_leg.status = LegStatus.OPEN
            trade.ce_leg.calculate_sl_price(self.config.sl_percentage)

        if trade.pe_leg:
            trade.pe_leg.entry_fill_price = pe_fill_price
            trade.pe_leg.current_price = pe_fill_price
            trade.pe_leg.entry_order_id = pe_order_id
            trade.pe_leg.entry_client_order_id = pe_client_order_id
            trade.pe_leg.entry_timestamp = dt
            trade.pe_leg.status = LegStatus.OPEN
            trade.pe_leg.calculate_sl_price(self.config.sl_percentage)

        trade.update_pnl()
        trade.state = StrategyState.ACTIVE
        trade.updated_at = dt

    async def _maybe_trigger_combined_tp(self, trade: StrategyTrade) -> None:
        if (
            not self.config.enable_combined_take_profit
            or self._tp_triggered
            or not trade.is_active
            or not self._on_tp_trigger
        ):
            return
        trade.update_pnl()
        total = trade.total_realized_pnl + trade.total_unrealized_pnl
        if total >= self._combined_tp_usd:
            self._tp_triggered = True
            self.logger.info(
                f"Combined TP hit: ${total:.2f} >= ${self._combined_tp_usd:.2f} — closing both legs"
            )
            await self._on_tp_trigger(trade)

    async def on_tick(self, ticker: Ticker) -> None:
        if not self._current_trade or not self._current_trade.is_active:
            return

        trade = self._current_trade
        current_price = ticker.mark_price or ticker.last_price or ticker.mid_price
        if current_price <= 0:
            return

        import asyncio

        self._last_tick_time = asyncio.get_event_loop().time()
        now_ist = datetime.now(IST_TIMEZONE)

        if trade.ce_leg and trade.ce_leg.is_open and not trade.ce_leg.sl_triggered:
            if ticker.symbol == trade.ce_leg.symbol or ticker.instrument_id == trade.ce_leg.instrument_id:
                trade.update_pnl(ce_price=current_price)
                if (
                    not trade.ce_leg.exchange_sl_active
                    and trade.ce_leg.sl_price is not None
                    and current_price >= trade.ce_leg.sl_price
                ):
                    trade.ce_leg.sl_triggered = True
                    trade.ce_leg.sl_timestamp = now_ist.isoformat()
                    if self._on_sl_trigger:
                        await self._on_sl_trigger(trade.ce_leg, current_price)
                await self._maybe_trigger_combined_tp(trade)

        if trade.pe_leg and trade.pe_leg.is_open and not trade.pe_leg.sl_triggered:
            if ticker.symbol == trade.pe_leg.symbol or ticker.instrument_id == trade.pe_leg.instrument_id:
                trade.update_pnl(pe_price=current_price)
                if (
                    not trade.pe_leg.exchange_sl_active
                    and trade.pe_leg.sl_price is not None
                    and current_price >= trade.pe_leg.sl_price
                ):
                    trade.pe_leg.sl_triggered = True
                    trade.pe_leg.sl_timestamp = now_ist.isoformat()
                    if self._on_sl_trigger:
                        await self._on_sl_trigger(trade.pe_leg, current_price)
                await self._maybe_trigger_combined_tp(trade)

    async def on_timer(self, now_ist: datetime, history: Optional[List[StrategyTrade]] = None) -> None:
        if not self._active:
            return

        import asyncio

        if self.can_enter_today(now_ist, history=history):
            self.logger.info(
                f"1-DTE entry window active at {now_ist.strftime('%H:%M:%S')} IST — strike discovery..."
            )
            try:
                spot_price = await self.exchange.get_spot_price(self.config.underlying)
                expiry = self.target_expiry_date(now_ist, self.config.expiry_calendar_days)
                chain = await self.exchange.get_option_chain(self.config.underlying, expiry)
                tickers_map = await self.exchange.get_tickers()

                ce_inst, ce_tick, _straddle, pe_inst, pe_tick, _ck, _pk = select_1dte_strangle_legs(
                    option_chain=chain,
                    tickers_map=tickers_map,
                    spot_price=spot_price,
                    config=self.config,
                )
                ce_est = ce_tick.sell_premium or ce_tick.mid_price
                pe_est = pe_tick.sell_premium or pe_tick.mid_price
                trade = await self.create_trade(
                    spot_price=spot_price,
                    ce_inst=ce_inst,
                    pe_inst=pe_inst,
                    ce_est_prem=ce_est,
                    pe_est_prem=pe_est,
                    now_ist=now_ist,
                )
                if self._on_entry_trigger:
                    await self._on_entry_trigger(trade, ce_inst, pe_inst, ce_est, pe_est)
            except StrikeSelectionError as e:
                self.logger.warning(f"1-DTE strike discovery skipped: {e}")
            except Exception as e:
                self.logger.error(f"1-DTE entry initiation error: {e}", exc_info=True)

        if self._current_trade and self._current_trade.is_active:
            open_legs = self._current_trade.get_open_legs()
            if open_legs:
                is_ws_stale = getattr(self.exchange, "is_stale", False) or not getattr(
                    self.exchange, "is_connected", True
                )
                now_ts = asyncio.get_event_loop().time()
                if is_ws_stale or (now_ts - self._last_tick_time > 5.0):
                    try:
                        lookup_keys = []
                        for leg in open_legs:
                            lookup_keys.append(leg.instrument_id)
                            lookup_keys.append(leg.symbol)
                        tickers = await self.exchange.get_tickers(symbols_or_ids=lookup_keys)
                        for leg in open_legs:
                            t = tickers.get(leg.symbol) or tickers.get(leg.instrument_id)
                            if t:
                                await self.on_tick(t)
                        await self._maybe_trigger_combined_tp(self._current_trade)
                    except Exception as e:
                        self.logger.warning(f"REST ticker polling fallback error: {e}")

        if self._current_trade and self._current_trade.is_active:
            if self.should_force_exit(now_ist, self._current_trade):
                self.logger.info("Parso expiry-day exit time — square-off for open legs")
                if self._on_exit_trigger:
                    await self._on_exit_trigger(self._current_trade)

    def on_leg_closed(
        self,
        leg: StrategyLeg,
        exit_price: float,
        exit_reason: str,
        exit_order_id: Optional[str] = None,
        exit_client_order_id: Optional[str] = None,
        fees: float = 0.0,
        now_ist: Optional[datetime] = None,
    ):
        dt = (now_ist or datetime.now(IST_TIMEZONE)).isoformat()
        leg.exit_timestamp = dt
        leg.exit_price = exit_price
        leg.exit_reason = exit_reason
        leg.fees += fees

        if exit_reason == "STOP_LOSS":
            leg.status = LegStatus.STOPPED_OUT
            leg.sl_order_id = exit_order_id
            leg.sl_client_order_id = exit_client_order_id
            leg.sl_fill_price = exit_price
        elif exit_reason in ("EOD_EXIT", "TAKE_PROFIT"):
            leg.status = LegStatus.FORCE_CLOSED
        elif exit_reason == "MANUAL_CLOSE":
            leg.status = LegStatus.MANUALLY_CLOSED
        elif exit_reason == "EMERGENCY_UNWIND":
            leg.status = LegStatus.UNWOUND_ON_FAILURE
        else:
            leg.status = LegStatus.FORCE_CLOSED

        if leg.entry_fill_price is not None:
            leg.realized_pnl = round((leg.entry_fill_price - exit_price) * leg.quantity * leg.contract_value, 4)

        if self._current_trade:
            self._current_trade.update_pnl()
            self.check_completion(self._current_trade)

    def check_completion(self, trade: StrategyTrade):
        if trade.state == StrategyState.ACTIVE and not trade.has_any_open_leg:
            trade.state = StrategyState.COMPLETED
            trade.update_pnl()
            self.logger.info(
                f"Trade {trade.strategy_trade_id} COMPLETED. Realized PnL: ${trade.total_realized_pnl:.2f}"
            )
