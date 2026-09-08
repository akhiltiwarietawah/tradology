"""BTC 0DTE Short Strangle Strategy Implementation."""

import logging
from typing import Optional, Tuple, List, Dict, Any, Callable, Awaitable
from datetime import datetime, time, timedelta
import pytz

from src.config.constants import IST_TIMEZONE
from src.core.interfaces.exchange import BaseExchangeAdapter
from src.core.models.instrument import Instrument, OptionChain, OptionType
from src.core.models.market_data import Ticker
from src.core.models.order import Order
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.strategies.base.strategy import BaseStrategy
from src.strategies.short_strangle.models import ShortStrangleConfig
from src.strategies.short_strangle.selector import OptionSelector, OptionSelectionError


class BTCShortStrangleStrategy(BaseStrategy):
    """Production-grade 0DTE Short Strangle Strategy on BTC."""

    def __init__(
        self,
        exchange_adapter: BaseExchangeAdapter,
        config: Optional[ShortStrangleConfig] = None,
        selector: Optional[OptionSelector] = None,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(strategy_name="btc_short_strangle", exchange_adapter=exchange_adapter, logger=logger)
        self.config = config or ShortStrangleConfig()
        self.selector = selector or OptionSelector(logger=self.logger)
        self._last_tick_time: float = 0.0
        self._last_entry_attempt_time: float = 0.0
        self._entry_retry_count: int = 0
        self._entry_retry_date: Optional[str] = None

        # Callbacks for execution triggers
        self._on_entry_trigger: Optional[Callable[[StrategyTrade, Instrument, Instrument, float, float], Awaitable[None]]] = None
        self._on_sl_trigger: Optional[Callable[[StrategyLeg, float], Awaitable[None]]] = None
        self._on_exit_trigger: Optional[Callable[[StrategyTrade], Awaitable[None]]] = None

    def record_entry_attempt(self, now_ist: Optional[datetime] = None, timestamp: Optional[float] = None):
        """Record an entry attempt timestamp and increment daily retry counter."""
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
    ):
        self._on_entry_trigger = on_entry
        self._on_sl_trigger = on_sl
        self._on_exit_trigger = on_exit

    def is_entry_window(self, now_ist: Optional[datetime] = None) -> bool:
        dt = now_ist or datetime.now(IST_TIMEZONE)
        current_time = dt.time()
        start_time = self.config.entry_time
        start_dt = datetime.combine(dt.date(), start_time)
        end_dt = start_dt + timedelta(minutes=self.config.entry_window_minutes)
        end_time = end_dt.time()
        return start_time <= current_time <= end_time

    def is_exit_window(self, now_ist: Optional[datetime] = None) -> bool:
        dt = now_ist or datetime.now(IST_TIMEZONE)
        return dt.time() >= self.config.exit_time

    def can_enter_today(
        self,
        now_ist: Optional[datetime] = None,
        history: Optional[List[StrategyTrade]] = None,
        current_timestamp: Optional[float] = None,
    ) -> bool:
        import time as _time
        dt = now_ist or datetime.now(IST_TIMEZONE)
        today_str = dt.strftime("%Y-%m-%d")

        # 1. Must be within the configured entry window
        if not self.is_entry_window(dt):
            return False

        # 2. Reset daily retry counter if on a new date
        if self._entry_retry_date != today_str:
            self._entry_retry_date = today_str
            self._entry_retry_count = 0

        # 3. Check retry limit (max clean submission retries per day)
        if self._entry_retry_count >= self.config.max_entry_retries:
            return False

        # 4. Check cooldown between retries
        now_ts = current_timestamp if current_timestamp is not None else _time.time()
        if self._last_entry_attempt_time > 0 and (now_ts - self._last_entry_attempt_time) < self.config.entry_retry_cooldown_seconds:
            return False

        # 5. Check active / current trade
        if self._current_trade is not None and self._current_trade.trade_date == today_str:
            # Active, Completed, In-Flight or Safe-Halt states strictly block
            if self._current_trade.state in (
                StrategyState.ACTIVE,
                StrategyState.COMPLETED,
                StrategyState.PENDING_ENTRY,
                StrategyState.PENDING_EXIT,
                StrategyState.SAFE_HALT,
            ):
                return False

            # FAILED_ENTRY blocks if any order was accepted, fill recorded, or emergency unwind occurred
            if self._current_trade.state == StrategyState.FAILED_ENTRY:
                if self._current_trade.has_any_fill_or_order:
                    return False

        # 6. Check historical trades for today (if provided)
        if history:
            for trade in history:
                if trade.trade_date == today_str:
                    # If today already had an active or completed trade or one with fills/unwinds, block permanently
                    if trade.state in (
                        StrategyState.ACTIVE,
                        StrategyState.COMPLETED,
                        StrategyState.PENDING_EXIT,
                        StrategyState.SAFE_HALT,
                    ) or trade.has_any_fill_or_order:
                        return False

        return True

    def create_trade(
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
        trade_id = f"STRANGLE_{timestamp_str}"
        expiry_str = dt.strftime("%d%m%y")

        ce_leg = StrategyLeg(
            leg_id=f"CE_{timestamp_str}",
            option_type=OptionType.CALL,
            instrument_id=ce_inst.instrument_id,
            symbol=ce_inst.symbol,
            strike=ce_inst.strike_price or 0.0,
            expiry_date=expiry_str,
            quantity=self.config.quantity,
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
            quantity=self.config.quantity,
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
            self.logger.info(
                f"CE Leg Active: {trade.ce_leg.symbol} @ ${ce_fill_price:.2f} | 100% SL trigger at ${trade.ce_leg.sl_price:.2f}"
            )

        if trade.pe_leg:
            trade.pe_leg.entry_fill_price = pe_fill_price
            trade.pe_leg.current_price = pe_fill_price
            trade.pe_leg.entry_order_id = pe_order_id
            trade.pe_leg.entry_client_order_id = pe_client_order_id
            trade.pe_leg.entry_timestamp = dt
            trade.pe_leg.status = LegStatus.OPEN
            trade.pe_leg.calculate_sl_price(self.config.sl_percentage)
            self.logger.info(
                f"PE Leg Active: {trade.pe_leg.symbol} @ ${pe_fill_price:.2f} | 100% SL trigger at ${trade.pe_leg.sl_price:.2f}"
            )

        trade.update_pnl()
        trade.state = StrategyState.ACTIVE
        trade.updated_at = dt

    async def on_tick(self, ticker: Ticker) -> None:
        """Evaluate independent Stop Loss breaches on incoming market ticks."""
        if not self._current_trade or not self._current_trade.is_active:
            return

        trade = self._current_trade
        current_price = ticker.mark_price or ticker.last_price or ticker.mid_price
        if current_price <= 0:
            return

        import asyncio
        self._last_tick_time = asyncio.get_event_loop().time()
        now_ist = datetime.now(IST_TIMEZONE)

        # 1. Check CE Leg SL
        if trade.ce_leg and trade.ce_leg.is_open and not trade.ce_leg.sl_triggered:
            if ticker.symbol == trade.ce_leg.symbol or ticker.instrument_id == trade.ce_leg.instrument_id:
                trade.update_pnl(ce_price=current_price)
                if trade.ce_leg.sl_price is not None and current_price >= trade.ce_leg.sl_price:
                    trade.ce_leg.sl_triggered = True
                    trade.ce_leg.sl_timestamp = now_ist.isoformat()
                    self.logger.warning(
                        f"🛑 CE SL Triggered! {trade.ce_leg.symbol}: tick ${current_price:.2f} >= SL ${trade.ce_leg.sl_price:.2f}"
                    )
                    if self._on_sl_trigger:
                        await self._on_sl_trigger(trade.ce_leg, current_price)

        # 2. Check PE Leg SL
        if trade.pe_leg and trade.pe_leg.is_open and not trade.pe_leg.sl_triggered:
            if ticker.symbol == trade.pe_leg.symbol or ticker.instrument_id == trade.pe_leg.instrument_id:
                trade.update_pnl(pe_price=current_price)
                if trade.pe_leg.sl_price is not None and current_price >= trade.pe_leg.sl_price:
                    trade.pe_leg.sl_triggered = True
                    trade.pe_leg.sl_timestamp = now_ist.isoformat()
                    self.logger.warning(
                        f"🛑 PE SL Triggered! {trade.pe_leg.symbol}: tick ${current_price:.2f} >= SL ${trade.pe_leg.sl_price:.2f}"
                    )
                    if self._on_sl_trigger:
                        await self._on_sl_trigger(trade.pe_leg, current_price)

    async def on_timer(self, now_ist: datetime, history: Optional[List[StrategyTrade]] = None) -> None:
        """Handle periodic timer ticks for entry window and 17:15 square-off."""
        if not self._active:
            return

        import asyncio

        # 1. Check Entry Window (09:00 IST)
        if self.can_enter_today(now_ist, history=history):
            self.logger.info(f"Entry window active at {now_ist.strftime('%H:%M:%S')} IST. Initiating strike discovery...")
            try:
                spot_price = await self.exchange.get_spot_price(self.config.underlying)
                chain = await self.exchange.get_option_chain(self.config.underlying, now_ist.date())
                tickers_map = await self.exchange.get_tickers()

                ce_inst, ce_tick, pe_inst, pe_tick = self.selector.select_strangle_legs(
                    option_chain=chain,
                    tickers_map=tickers_map,
                    spot_price=spot_price,
                    target_premium=self.config.target_premium,
                    tolerance_usd=self.config.premium_tolerance_usd,
                )

                trade = self.create_trade(
                    spot_price=spot_price,
                    ce_inst=ce_inst,
                    pe_inst=pe_inst,
                    ce_est_prem=ce_tick.mid_price,
                    pe_est_prem=pe_tick.mid_price,
                    now_ist=now_ist,
                )

                if self._on_entry_trigger:
                    await self._on_entry_trigger(trade, ce_inst, pe_inst, ce_tick.mid_price, pe_tick.mid_price)

            except OptionSelectionError as e:
                self.logger.warning(f"Strike discovery skipped: {e}")
            except Exception as e:
                self.logger.error(f"Error during strategy entry initiation: {e}", exc_info=True)

        # 2. REST Polling Fallback for active open legs if WebSocket is disconnected or stale
        if self._current_trade and self._current_trade.is_active:
            open_legs = self._current_trade.get_open_legs()
            if open_legs:
                is_ws_stale = getattr(self.exchange, "is_stale", False) or not getattr(self.exchange, "is_connected", True)
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
                    except Exception as e:
                        self.logger.warning(f"REST ticker polling fallback error: {e}")

        # 3. Check Exit Window (17:15 IST forced square-off)
        if self._current_trade and self._current_trade.is_active:
            if self.is_exit_window(now_ist):
                self.logger.info(f"⏰ Reached 17:15 IST exit time. Triggering square-off for open legs...")
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
        elif exit_reason == "EOD_EXIT":
            leg.status = LegStatus.FORCE_CLOSED
        elif exit_reason == "MANUAL_CLOSE":
            leg.status = LegStatus.MANUALLY_CLOSED
        elif exit_reason == "EMERGENCY_UNWIND":
            leg.status = LegStatus.UNWOUND_ON_FAILURE
        else:
            leg.status = LegStatus.FORCE_CLOSED

        if leg.entry_fill_price is not None:
            leg.realized_pnl = round((leg.entry_fill_price - exit_price) * leg.quantity * leg.contract_value, 4)

        self.logger.info(
            f"Leg Closed: {leg.symbol} | Reason: {exit_reason} | Exit Price: ${exit_price:.2f} | Realized PnL: ${leg.realized_pnl:.2f}"
        )

        if self._current_trade:
            self._current_trade.update_pnl()
            self.check_completion(self._current_trade)

    def check_completion(self, trade: StrategyTrade):
        if trade.state == StrategyState.ACTIVE:
            if not trade.has_any_open_leg:
                trade.state = StrategyState.COMPLETED
                trade.update_pnl()
                self.logger.info(
                    f"🎉 Trade {trade.strategy_trade_id} marked COMPLETED. Total Realized PnL: ${trade.total_realized_pnl:.2f}"
                )
