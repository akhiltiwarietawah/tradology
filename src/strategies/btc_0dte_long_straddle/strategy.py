"""BTC 0DTE Long Straddle Strategy Implementation on Delta Exchange."""

import logging
from typing import Optional, Callable, Awaitable
from datetime import datetime, time, timedelta

from src.config.constants import IST_TIMEZONE
from src.core.interfaces.exchange import BaseExchangeAdapter
from src.core.models.instrument import Instrument, OptionChain
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.models.order import OrderSide
from src.strategies.base.strategy import BaseStrategy
from src.strategies.btc_0dte_long_straddle.models import LongStraddleConfig
from src.strategies.btc_0dte_long_straddle.selector import ATMStraddleSelector
from src.strategies.btc_0dte_long_straddle.sizing import (
    calculate_straddle_contracts,
    effective_equity_for_entry,
    apply_exit_to_virtual_equity,
)


class BTC0DTELongStraddleStrategy(BaseStrategy):
    """
    1:00 PM IST BTC 0DTE ATM Long Straddle Strategy on Delta Exchange India.
    - Sizing: Fixed Lots (e.g. 10 lots) OR Dynamic (% Equity with profit retention).
    - Timing: Monday to Friday at 13:00 IST (Weekends excluded).
    - Settlement: Holds till 5:30 PM IST auto cash-settlement to save exit fees on worthless legs.
    """

    def __init__(
        self,
        exchange_adapter: BaseExchangeAdapter,
        config: Optional[LongStraddleConfig] = None,
        selector: Optional[ATMStraddleSelector] = None,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(strategy_name="btc_0dte_long_straddle", exchange_adapter=exchange_adapter, logger=logger)
        self.config = config or LongStraddleConfig.from_env()
        self.selector = selector or ATMStraddleSelector(logger=self.logger)
        self._last_tick_time: float = 0.0
        self._entry_done_today: Optional[str] = None
        self._virtual_equity: float = self.config.sizing_base_usd

        # Execution callback
        self._on_entry_trigger: Optional[Callable[[StrategyTrade, Instrument, Instrument, float, float], Awaitable[None]]] = None

    def set_execution_callbacks(
        self,
        on_entry: Callable[[StrategyTrade, Instrument, Instrument, float, float], Awaitable[None]],
    ):
        self._on_entry_trigger = on_entry

    def is_trading_day(self, now_ist: Optional[datetime] = None) -> bool:
        """Check if today is an allowed trading day (Monday to Friday)."""
        dt = now_ist or datetime.now(IST_TIMEZONE)
        return dt.weekday() in self.config.allowed_weekdays

    def is_entry_window(self, now_ist: Optional[datetime] = None) -> bool:
        """Entry window: 1:00 PM to 1:15 PM IST."""
        if not self.is_trading_day(now_ist):
            return False
        dt = now_ist or datetime.now(IST_TIMEZONE)
        current_time = dt.time()
        start_time = self.config.entry_time
        start_dt = datetime.combine(dt.date(), start_time)
        end_dt = start_dt + timedelta(minutes=self.config.entry_window_minutes)
        return start_time <= current_time <= end_dt.time()

    async def resolve_order_quantity(self, ce_price: float, pe_price: float) -> int:
        """Determine quantity in lots according to Fixed or Dynamic sizing mode."""
        if self.config.position_sizing_mode == "fixed":
            return self.config.fixed_lots

        # Dynamic mode: Fetch live wallet balance
        wallet_balance = 0.0
        try:
            bal_obj = await self.exchange_adapter.get_account_balances()
            if bal_obj and bal_obj.balances:
                for asset in bal_obj.balances:
                    if asset.asset.upper() in ("USD", "USDT", "USDC"):
                        wallet_balance += float(asset.available_balance)
        except Exception as exc:
            self.logger.warning(f"Could not fetch wallet balance, falling back to virtual equity: {exc}")

        effective_eq = effective_equity_for_entry(wallet_balance, self._virtual_equity)

        qty = calculate_straddle_contracts(
            mode="dynamic",
            fixed_lots=self.config.fixed_lots,
            effective_equity=effective_eq,
            call_premium=ce_price,
            put_premium=pe_price,
            contract_value=self.config.contract_value,
            margin_pct=self.config.dynamic_margin_pct,
            min_lots=self.config.min_lots,
            max_lots=self.config.max_lots,
        )
        self.logger.info(
            f"Dynamic sizing resolved: Wallet=${wallet_balance:.2f}, Virtual=${self._virtual_equity:.2f}, "
            f"Effective=${effective_eq:.2f}, Lots={qty}"
        )
        return qty

    async def on_tick(self, timestamp: float):
        """Called every tick/minute by the engine."""
        now_ist = datetime.now(IST_TIMEZONE)
        today_str = now_ist.strftime("%Y-%m-%d")

        # Skip if already entered today
        if self._entry_done_today == today_str:
            return

        # Check if inside entry window
        if not self.is_entry_window(now_ist):
            return

        try:
            ticker = await self.exchange_adapter.get_ticker(f"{self.config.underlying_symbol}USDT")
            spot_price = ticker.last_price if ticker else None
            if not spot_price or spot_price <= 0:
                self.logger.warning("Could not obtain valid BTC spot price.")
                return

            today_date = now_ist.date()
            option_chain = await self.exchange_adapter.get_option_chain(
                underlying=self.config.underlying_symbol,
                expiry_date=today_date,
            )

            call_inst, put_inst = self.selector.select_atm_straddle(
                option_chain=option_chain,
                spot_price=spot_price,
                expiry_date=today_date,
            )

            ce_mark = call_inst.mark_price or (spot_price * 0.005)
            pe_mark = put_inst.mark_price or (spot_price * 0.005)

            # Resolve lots (Fixed or Dynamic)
            order_lots = await self.resolve_order_quantity(ce_mark, pe_mark)

            trade = StrategyTrade(
                strategy_name=self.strategy_name,
                underlying=self.config.underlying_symbol,
                state=StrategyState.PENDING_ENTRY,
                created_at=now_ist,
                legs=[
                    StrategyLeg(
                        instrument=call_inst,
                        side=OrderSide.BUY,
                        quantity=order_lots,
                        status=LegStatus.PENDING,
                    ),
                    StrategyLeg(
                        instrument=put_inst,
                        side=OrderSide.BUY,
                        quantity=order_lots,
                        status=LegStatus.PENDING,
                    )
                ]
            )

            self.logger.info(
                f"🚀 Triggering 0DTE Long Straddle at {now_ist.strftime('%H:%M:%S')} IST! "
                f"Mode: {self.config.position_sizing_mode.upper()} | Quantity: {order_lots} Lots | "
                f"CE: {call_inst.symbol} (Strike: {call_inst.strike_price}) | "
                f"PE: {put_inst.symbol} (Strike: {put_inst.strike_price})"
            )

            if self._on_entry_trigger:
                await self._on_entry_trigger(trade, call_inst, put_inst, spot_price, spot_price)

            self._entry_done_today = today_str
            self.trades.append(trade)

        except Exception as e:
            self.logger.error(f"Error executing 1:00 PM Long Straddle entry: {e}", exc_info=True)
