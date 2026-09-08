import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from src.config.constants import IST_TIMEZONE
from src.config.settings import Settings, get_settings
from src.core.events.event_bus import EventBus, EventType, Event
from src.core.scheduler.strategy_scheduler import StrategyScheduler
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.models.order import OrderRequest, OrderSide, OrderType
from src.core.models.instrument import Instrument
from src.core.models.market_data import Ticker
from src.exchanges.service import ExchangeService
from src.exchanges.delta.adapter import DeltaExchangeAdapter
from src.strategies.short_strangle.selector import OptionSelector
from src.strategies.short_strangle.strategy import BTCShortStrangleStrategy
from src.strategies.short_strangle.models import ShortStrangleConfig
from src.execution.execution_engine import ExecutionEngine
from src.execution.order_manager import OrderManager
from src.risk.risk_manager import RiskManager
from src.reconciliation.reconciler import StateReconciler, ReconciliationResult
from src.state.persistence import StatePersistence
from src.state.state_store import StateStore
from src.persistence.db import DatabaseManager
from src.persistence.trade_repository import TradeRepository
from src.monitoring.alerts import AlertService, AlertSeverity
from src.logging_utils.logger import setup_logger, TradeLogger



class TradingEngine:
    """Production Trading Engine orchestrating multi-exchange and multi-strategy workflows."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.settings = settings or get_settings()
        self.logger = logger or setup_logger(
            name="trading_engine",
            logs_dir=self.settings.logs_dir,
            log_level=self.settings.log_level,
        )

        # Log active environment at startup without secrets
        is_live = (self.settings.delta_env.value == "live")
        self.logger.info("=" * 60)
        self.logger.info(f"🚀 INITIALIZING TRADING ENGINE")
        self.logger.info(f"   ENVIRONMENT: {'LIVE' if is_live else 'TESTNET'}")
        self.logger.info(f"   REST ENDPOINT: {self.settings.active_rest_url}")
        self.logger.info(f"   WS ENDPOINT: {self.settings.active_ws_url}")
        self.logger.info(f"   STRATEGY: {self.settings.strategy} ({self.settings.underlying})")
        self.logger.info(f"   ENTRY TIME: {self.settings.entry_time_ist} IST | EXIT TIME: {self.settings.exit_time_ist} IST")
        self.logger.info(f"   TARGET PREMIUM: ${self.settings.target_premium:.2f} (±${self.settings.premium_tolerance_usd:.2f})")
        self.logger.info(f"   LOT SIZE: {self.settings.order_quantity} | STOP LOSS: {self.settings.sl_percentage * 100:.0f}%")
        self.logger.info(f"   MAX DAILY LOSS: ${self.settings.max_daily_loss_usd:.2f}")
        self.logger.info("=" * 60)

        # Core Components
        self.event_bus = EventBus(logger=self.logger)
        self.trade_logger = TradeLogger(logs_dir=self.settings.logs_dir)
        self.state_persistence = StatePersistence(file_path=self.settings.state_file, logger=self.logger)
        self.state_store = StateStore(logger=self.logger)

        # Historical Database Persistence Layer (Optional / Non-blocking)
        self.db_manager = DatabaseManager(settings=self.settings, logger=self.logger)
        self.trade_repo = TradeRepository(db_manager=self.db_manager, logger=self.logger)


        # Exchange Layer
        self.exchange_service = ExchangeService(logger=self.logger)
        self.delta_adapter = DeltaExchangeAdapter(
            rest_url=self.settings.active_rest_url,
            ws_url=self.settings.active_ws_url,
            api_key=self.settings.active_api_key,
            api_secret=self.settings.active_api_secret,
            is_testnet=not is_live,
            logger=self.logger,
        )
        self.exchange_service.register_adapter(self.delta_adapter)

        # Execution & Risk Layer
        self.order_manager = OrderManager(logger=self.logger)
        self.execution_engine = ExecutionEngine(
            exchange_adapter=self.delta_adapter,
            order_manager=self.order_manager,
            trade_logger=self.trade_logger,
            entry_timeout_seconds=self.settings.two_leg_entry_timeout_seconds,
            logger=self.logger,
        )
        self.risk_manager = RiskManager(
            max_daily_loss_pct=self.settings.max_daily_loss_pct,
            max_daily_loss_usd=self.settings.max_daily_loss_usd,
            kill_switch=self.settings.kill_switch,
            logger=self.logger,
        )
        self.reconciler = StateReconciler(
            exchange_adapter=self.delta_adapter,
            trade_logger=self.trade_logger,
            logger=self.logger,
        )

        # Strategy Layer (BTC 0DTE Strangle)
        strangle_cfg = ShortStrangleConfig(
            underlying=self.settings.underlying,
            target_premium=self.settings.target_premium,
            premium_tolerance_usd=self.settings.premium_tolerance_usd,
            quantity=self.settings.order_quantity,
            sl_percentage=self.settings.sl_percentage,
            entry_time=self.settings.get_parsed_entry_time(),
            entry_window_minutes=self.settings.entry_window_minutes,
            exit_time=self.settings.get_parsed_exit_time(),
            max_daily_loss_usd=self.settings.max_daily_loss_usd,
        )
        self.strategy = BTCShortStrangleStrategy(
            exchange_adapter=self.delta_adapter,
            config=strangle_cfg,
            logger=self.logger,
        )
        self.strategy.set_execution_callbacks(
            on_entry=self._handle_strategy_entry_trigger,
            on_sl=self._handle_strategy_sl_trigger,
            on_exit=self._handle_strategy_exit_trigger,
        )

        # Scheduler
        self.scheduler = StrategyScheduler(
            event_bus=self.event_bus,
            tick_interval_seconds=1.0,
            logger=self.logger,
        )
        self.scheduler.add_timer_callback(self._on_timer_tick)

        # Alert & Monitoring Layer
        self.alert_service = AlertService(settings=self.settings, logger=self.logger)

        # Watchdog & Health Timestamps
        self.start_time: datetime = datetime.now(timezone.utc)
        self.last_heartbeat_time: datetime = datetime.now(timezone.utc)
        self.last_loop_time: Optional[datetime] = None
        self.last_reconciliation_time: Optional[datetime] = None
        self.last_rest_request_time: Optional[datetime] = None
        self.last_ws_tick_time: Optional[datetime] = None
        self.last_db_operation_time: Optional[datetime] = None

        self._running = False
        self._last_reconcile_time = 0.0
        self._last_reconciliation_result: Optional[ReconciliationResult] = None

    async def start(self):
        """Start the entire trading engine."""
        self._running = True
        self.start_time = datetime.now(timezone.utc)
        self.last_heartbeat_time = datetime.now(timezone.utc)
        self.logger.info("Starting Trading Engine components...")

        # 1. Recover persisted state (Atomic JSON is primary recovery source)
        recovered_trade, history = self.state_persistence.load_state()
        if history:
            self.state_store._historical_trades = list(history)

        if recovered_trade:
            if recovered_trade.state == StrategyState.FAILED_ENTRY and not recovered_trade.has_any_fill_or_order:
                # Clean zero-fill failed attempt: archive it to history so engine starts in clean idle
                self.state_store.archive_trade(recovered_trade)
                self.strategy.current_trade = None
                self._save_state()
                self.logger.info(
                    f"Archived clean zero-fill failed trade {recovered_trade.strategy_trade_id} to history on startup."
                )
            else:
                self.strategy.current_trade = recovered_trade
                self.state_store.set_active_trade(recovered_trade)
                self.logger.info(f"Restored active trade {recovered_trade.strategy_trade_id} (State: {recovered_trade.state.value})")

        # 2. Connect Database Persistence (if enabled) with non-blocking error isolation
        if self.settings.db_enabled:
            try:
                db_ok = await self.db_manager.connect()
                if db_ok:
                    await self.db_manager.run_migrations()
                    self.last_db_operation_time = datetime.now(timezone.utc)
            except Exception as e:
                self.logger.warning(
                    f"⚠️ DATABASE: UNAVAILABLE — trading continues using file persistence + exchange reconciliation (Error: {e})"
                )

        # 3. Initialize exchange adapters
        await self.exchange_service.initialize_all()
        self.last_rest_request_time = datetime.now(timezone.utc)

        # 4. Log authenticated account wallet balances at startup
        try:
            acc_bal = await self.delta_adapter.get_account_balances()
            bal_parts = []
            for sym in ("USD", "INR", "BTC"):
                if sym in acc_bal.balances:
                    b = acc_bal.balances[sym]
                    inr_info = f" (₹{b.balance_inr:,.2f} INR)" if b.balance_inr is not None and sym != "INR" else ""
                    bal_parts.append(f"{sym}: Bal={b.balance:,.4f}, Avail={b.available_balance:,.4f}{inr_info}")
            if bal_parts:
                self.logger.info(f"💰 Authenticated Account Balance: {' | '.join(bal_parts)}")
        except Exception as e:
            self.logger.warning(f"Could not retrieve account balance on startup: {e}")

        # 5. Perform Startup Reconciliation against exchange
        reconcile_res = await self.reconcile_state()

        # 6. Strategy Activation & Startup Alert
        if not reconcile_res.is_synchronized:
            self.logger.warning(
                f"⚠️ Startup exchange reconciliation failed (Status: {reconcile_res.status}). Strategy will remain INACTIVE and trading blocked until reconciliation succeeds."
            )
            if reconcile_res.status == "SAFE_HALT":
                await self.alert_service.send(
                    severity=AlertSeverity.CRITICAL,
                    event="SAFE_HALT",
                    message=f"🚨 Bot startup SAFE_HALT: Reconciliation discrepancy ({reconcile_res.details.get('reason', 'Discrepancy')}). Manual intervention required.",
                )
            else:
                await self.alert_service.send(
                    severity=AlertSeverity.WARNING,
                    event="STARTUP_UNSYNCHRONIZED",
                    message=f"⚠️ Startup reconciliation pending (Status: {reconcile_res.status}). Trading paused.",
                )
        else:
            # Subscribe to market data for active legs (if recovering active trade)
            if self.strategy.current_trade and self.strategy.current_trade.is_active:
                active_symbols = [leg.symbol for leg in self.strategy.current_trade.get_open_legs()]
                if active_symbols:
                    await self.delta_adapter.subscribe_market_data(active_symbols, self._on_market_tick_wrapper)

            # Start Strategy
            await self.strategy.start()

            # Startup / Recovery notification
            if self.strategy.current_trade and self.strategy.current_trade.is_active:
                ce_brk = self.strategy.current_trade.ce_leg.bracket_order_id if self.strategy.current_trade.ce_leg else None
                pe_brk = self.strategy.current_trade.pe_leg.bracket_order_id if self.strategy.current_trade.pe_leg else None
                brk_active = "ACTIVE" if (ce_brk or pe_brk) else "NONE"
                await self.alert_service.send(
                    severity=AlertSeverity.INFO,
                    event="STARTUP_RECOVERY",
                    message=f"🔄 Bot restarted. Recovered active {self.strategy.current_trade.strategy_name} trade {self.strategy.current_trade.strategy_trade_id}. CE/PE positions reconciled. Native brackets: {brk_active}.",
                    trade_id=self.strategy.current_trade.strategy_trade_id,
                )
            else:
                await self.alert_service.send(
                    severity=AlertSeverity.SUCCESS,
                    event="STARTUP",
                    message="✅ Bot started. No active trade. Exchange synchronized.",
                )

        # 7. Start Scheduler (runs background reconciliation, monitoring, and timer loops)
        await self.scheduler.start()
        if not reconcile_res.is_synchronized:
            self.logger.warning("⚠️ Trading Engine running in MONITORING-ONLY mode (Trading Blocked due to reconciliation failure).")
        elif self.settings.dry_run or self.risk_manager.is_kill_switch_active:
            self.logger.warning("⚠️ Trading Engine operational in MONITORING/DRY-RUN mode (LIVE ORDERS BLOCKED).")
        else:
            self.logger.info("✅ Trading Engine fully operational (LIVE Trading Enabled).")

    async def _on_market_tick_wrapper(self, ticker: Ticker):
        """Wrapper for market data ticks to update watchdog timestamps."""
        self.last_ws_tick_time = datetime.now(timezone.utc)
        await self.strategy.on_tick(ticker)

    def _save_state(self, trade: Optional[StrategyTrade] = None):
        """Atomically persist trade state and historical trades to disk."""
        t = trade if trade is not None else self.strategy.current_trade
        self.state_persistence.save_state(t, history=self.state_store._historical_trades)

    def _mark_price_from_ticker(self, ticker: Ticker) -> float:
        return ticker.mark_price or ticker.last_price or ticker.mid_price or 0.0

    def _refresh_unrealized_from_mark_cache(self, trade: StrategyTrade) -> None:
        """Apply last WS marks onto open legs so /status snapshots have live unrealized PnL."""
        getter = getattr(self.delta_adapter, "get_latest_ticker", None)
        ce_px = None
        pe_px = None
        if callable(getter):
            if trade.ce_leg and trade.ce_leg.is_open:
                cached = getter(trade.ce_leg.symbol) or getter(trade.ce_leg.instrument_id)
                if cached is not None:
                    ce_px = self._mark_price_from_ticker(cached)
                    if ce_px <= 0:
                        ce_px = None
            if trade.pe_leg and trade.pe_leg.is_open:
                cached = getter(trade.pe_leg.symbol) or getter(trade.pe_leg.instrument_id)
                if cached is not None:
                    pe_px = self._mark_price_from_ticker(cached)
                    if pe_px <= 0:
                        pe_px = None
        trade.update_pnl(ce_price=ce_px, pe_price=pe_px)

    async def stop(self):
        """Gracefully stop engine and flush state."""
        self._running = False
        self.logger.info("Stopping Trading Engine...")
        await self.scheduler.stop()
        if self.strategy.is_active:
            await self.strategy.stop()

        # Flush state
        self._save_state()

        # Disconnect Database
        if self.db_manager.is_connected:
            await self.db_manager.disconnect()

        await self.exchange_service.close_all()
        self.logger.info("Trading Engine stopped cleanly.")

    async def reconcile_state(self, trade: Optional[StrategyTrade] = None) -> ReconciliationResult:
        """Run reconciliation against exchange."""
        self.last_rest_request_time = datetime.now(timezone.utc)
        target_trade = trade if trade is not None else self.strategy.current_trade
        res = await self.reconciler.reconcile(target_trade)
        self._last_reconciliation_result = res
        self.last_reconciliation_time = datetime.now(timezone.utc)

        if not res.is_synchronized and res.status == "SAFE_HALT":
            self.risk_manager.activate_kill_switch()
            await self.alert_service.send(
                severity=AlertSeverity.CRITICAL,
                event="SAFE_HALT",
                message=f"🚨 SAFE_HALT: Reconciliation discrepancy detected ({res.details.get('reason', 'Discrepancy')}). Trading halted.",
            )

        # Check for open strategy positions without native SL
        if self.strategy.current_trade:
            for leg in (self.strategy.current_trade.ce_leg, self.strategy.current_trade.pe_leg):
                if leg and leg.status == LegStatus.OPEN and not leg.bracket_order_id and not leg.exchange_sl_active:
                    await self.alert_service.send(
                        severity=AlertSeverity.CRITICAL,
                        event="MISSING_BRACKET_SL",
                        message=f"🚨 CRITICAL: Strategy leg {leg.symbol} exists without native exchange SL.",
                        trade_id=self.strategy.current_trade.strategy_trade_id,
                    )

        self._save_state()

        if self.strategy.current_trade:
            await self._safe_db_persist_reconciliation_update(self.strategy.current_trade)

        return res

    async def _on_timer_tick(self, now_ist: datetime):
        """Periodic timer loop."""
        if not self._running:
            return

        self.last_heartbeat_time = datetime.now(timezone.utc)
        self.last_loop_time = datetime.now(timezone.utc)

        # WebSocket stale watchdog alert
        if hasattr(self.delta_adapter, "is_ws_stale") and self.delta_adapter.is_ws_stale():
            await self.alert_service.send(
                severity=AlertSeverity.WARNING,
                event="WS_STALE",
                message="⚠️ WARNING: Delta WebSocket stale. REST polling fallback active.",
            )

        # Strategy timer (only fires entry/SL if strategy is active)
        if self.strategy.is_active:
            await self.strategy.on_timer(now_ist, history=self.state_store._historical_trades)

        # Risk check
        if self.strategy.current_trade and self.strategy.current_trade.is_active:
            breached, loss = self.risk_manager.check_daily_loss_limit(self.strategy.current_trade)
            if breached:
                self.logger.critical(f"Max daily loss breached (${loss:.2f}). Triggering emergency square-off!")
                await self.execution_engine.execute_trade_square_off(self.strategy.current_trade, reason="MAX_LOSS")
                self.risk_manager.activate_kill_switch()

        # Periodic background reconciliation
        now_ts = asyncio.get_event_loop().time()
        if now_ts - self._last_reconcile_time >= self.settings.reconciliation_interval_seconds:
            self._last_reconcile_time = now_ts
            reconcile_res = await self.reconcile_state()
            if reconcile_res.is_synchronized:
                if not self.strategy.is_active and not self.risk_manager.is_kill_switch_active:
                    self.logger.info("🎉 Background exchange reconciliation succeeded! Activating strategy for trading...")
                    await self.strategy.start()
            else:
                if self.strategy.is_active:
                    self.logger.warning(
                        f"⚠️ Background exchange reconciliation failed (Status: {reconcile_res.status}). Pausing strategy trading."
                    )
                    await self.strategy.stop()

        # Save state
        self._save_state()

    async def _handle_strategy_entry_trigger(
        self,
        trade: StrategyTrade,
        ce_inst: Instrument,
        pe_inst: Instrument,
        ce_est_prem: float,
        pe_est_prem: float,
    ):
        """Handle entry signal emitted from strategy."""
        if not self.strategy.is_active:
            self.logger.warning("Strategy is inactive (reconciliation pending or failed). Aborting entry.")
            return

        # Pre-trade risk check
        safe, msg = self.risk_manager.check_pre_trade_safety(trade)
        if not safe:
            self.logger.warning(f"Pre-trade safety check failed: {msg}. Aborting entry.")
            return

        # Prepare OrderRequests
        ce_client_id = self.order_manager.generate_client_order_id(
            strategy_name="btc_short_strangle",
            trade_id=trade.strategy_trade_id,
            leg_name="CE",
            side=OrderSide.SELL,
            action="entry",
        )
        pe_client_id = self.order_manager.generate_client_order_id(
            strategy_name="btc_short_strangle",
            trade_id=trade.strategy_trade_id,
            leg_name="PE",
            side=OrderSide.SELL,
            action="entry",
        )

        ce_req = OrderRequest(
            instrument_id=ce_inst.instrument_id,
            symbol=ce_inst.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=trade.ce_leg.quantity if trade.ce_leg else self.settings.order_quantity,
            client_order_id=ce_client_id,
            strategy_id=trade.strategy_trade_id,
            leg_id=trade.ce_leg.leg_id if trade.ce_leg else None,
        )

        pe_req = OrderRequest(
            instrument_id=pe_inst.instrument_id,
            symbol=pe_inst.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=trade.pe_leg.quantity if trade.pe_leg else self.settings.order_quantity,
            client_order_id=pe_client_id,
            strategy_id=trade.strategy_trade_id,
            leg_id=trade.pe_leg.leg_id if trade.pe_leg else None,
        )

        # Set current trade on strategy
        self.strategy.current_trade = trade

        # Record entry attempt on strategy (tracks retry count and cooldown)
        self.strategy.record_entry_attempt(now_ist=datetime.now(IST_TIMEZONE))

        success, ce_order, pe_order = await self.execution_engine.execute_strangle_entry(trade, ce_req, pe_req)

        if success and ce_order and pe_order:
            ce_fill_px = ce_order.average_fill_price or ce_est_prem
            pe_fill_px = pe_order.average_fill_price or pe_est_prem

            lo, hi = OptionSelector.premium_band(
                self.settings.target_premium, self.settings.premium_tolerance_usd
            )
            for name, fill_px in (("CE", ce_fill_px), ("PE", pe_fill_px)):
                if not OptionSelector.is_premium_in_band(
                    fill_px, self.settings.target_premium, self.settings.premium_tolerance_usd
                ):
                    self.logger.error(
                        f"{name} fill ${fill_px:.2f} is outside premium band ${lo:.2f}-${hi:.2f} "
                        f"(target ${self.settings.target_premium:.2f} ± "
                        f"${self.settings.premium_tolerance_usd:.2f}). "
                        f"Position is live — not auto-unwound. Selection now uses bid, not mark."
                    )

            self.strategy.on_entry_filled(
                trade=trade,
                ce_fill_price=ce_fill_px,
                pe_fill_price=pe_fill_px,
                ce_order_id=ce_order.order_id or "0",
                pe_order_id=pe_order.order_id or "0",
                ce_client_order_id=ce_client_id,
                pe_client_order_id=pe_client_id,
            )

            # Attach native exchange-side Bracket Stop Loss & Target (Primary Protection & Profit Layer)
            ce_sl_ok = True
            pe_sl_ok = True
            tp_px = self.settings.target_price if (self.settings.target_price and self.settings.target_price > 0) else None
            if trade.ce_leg and trade.ce_leg.sl_price:
                ce_sl_ok = await self.execution_engine.attach_exchange_bracket_sl(
                    leg=trade.ce_leg,
                    stop_loss_price=trade.ce_leg.sl_price,
                    take_profit_price=tp_px,
                    stop_trigger_method="mark_price",
                )
            if trade.pe_leg and trade.pe_leg.sl_price:
                pe_sl_ok = await self.execution_engine.attach_exchange_bracket_sl(
                    leg=trade.pe_leg,
                    stop_loss_price=trade.pe_leg.sl_price,
                    take_profit_price=tp_px,
                    stop_trigger_method="mark_price",
                )

            # Failure Safety: Never leave an unprotected naked short
            if not ce_sl_ok or not pe_sl_ok:
                self.logger.critical(
                    "🚨 NATIVE BRACKET CREATION FAILED on one or more legs! Initiating emergency square-off to protect account."
                )
                await self.execution_engine.execute_trade_square_off(trade, reason="BRACKET_CREATION_FAILED")
                trade.state = StrategyState.SAFE_HALT
                self.risk_manager.activate_kill_switch()
                self._save_state(trade)
                return

            # Subscribe to real-time ticker stream for secondary monitoring
            await self.delta_adapter.subscribe_market_data(
                [ce_inst.symbol, pe_inst.symbol],
                self._on_market_tick_wrapper,
            )

            # Log fills to trade audit journal
            if trade.ce_leg:
                self.trade_logger.log_leg_fill(trade.strategy_trade_id, trade.ce_leg.to_dict())
            if trade.pe_leg:
                self.trade_logger.log_leg_fill(trade.strategy_trade_id, trade.pe_leg.to_dict())

            self._save_state(trade)

            # Historical Database Persistence (Non-blocking / Isolated)
            await self._safe_db_persist_entry(trade, ce_order, pe_order)

            # Alert Notification
            await self.alert_service.send(
                severity=AlertSeverity.SUCCESS,
                event="ENTRY_FILLED",
                message=f"📈 Strangle entered. CE: {trade.ce_leg.symbol} @ ${trade.ce_leg.entry_fill_price:.2f} | PE: {trade.pe_leg.symbol} @ ${trade.pe_leg.entry_fill_price:.2f} | Native SL: ACTIVE",
                trade_id=trade.strategy_trade_id,
            )
        else:
            # Entry Failed! Reconcile immediately to check exchange truth
            self.logger.warning(
                f"Entry submission failed for {trade.strategy_trade_id} (State: {trade.state.value}). Checking post-failure exchange state..."
            )
            reconcile_res = await self.reconcile_state(trade)

            # Retry is allowed ONLY IF:
            # 1. Trade had zero fills, zero order IDs, and no emergency unwind (not trade.has_any_fill_or_order)
            # 2. Exchange reconciliation confirms CLEAN_IDLE with is_synchronized=True
            # 3. Kill switch is not active
            if (
                not trade.has_any_fill_or_order
                and reconcile_res.is_synchronized
                and reconcile_res.status == "CLEAN_IDLE"
                and not self.risk_manager.is_kill_switch_active
            ):
                self.logger.info(
                    f"Clean entry failure verified on exchange (0 fills, 0 positions, 0 orders). Archiving {trade.strategy_trade_id} to history. Retry eligible after cooldown."
                )
                self.state_store.archive_trade(trade)
                self.strategy.current_trade = None
                self._save_state()
            else:
                self.logger.warning(
                    f"Entry failure is NOT eligible for retry (has_fill/unwind={trade.has_any_fill_or_order}, reconcile_status={reconcile_res.status}). State preserved as terminal."
                )
                self.strategy.current_trade = trade
                self._save_state(trade)

    async def _handle_strategy_sl_trigger(self, leg: StrategyLeg, current_price: float):
        """Handle SL breach for an individual leg."""
        self.trade_logger.log_sl_trigger(
            trade_id=self.strategy.current_trade.strategy_trade_id if self.strategy.current_trade else "UNKNOWN",
            leg_symbol=leg.symbol,
            current_price=current_price,
            sl_price=leg.sl_price or 0.0,
        )

        order = await self.execution_engine.execute_leg_exit(leg, reason="STOP_LOSS")
        fill_px = order.average_fill_price if (order and order.average_fill_price) else None
        fill_fees = 0.0
        if fill_px is None:
            # Native bracket already closed the short — do not use mark/trigger price.
            actual_px, fill_fees, _ = await self.reconciler.capture_leg_exit_fill(leg)
            fill_px = actual_px or current_price
        if fill_fees:
            leg.fees = fill_fees

        self.strategy.on_leg_closed(
            leg=leg,
            exit_price=fill_px,
            exit_reason="STOP_LOSS",
            exit_order_id=order.order_id if order else None,
            exit_client_order_id=order.client_order_id if order else None,
        )

        self.trade_logger.log_leg_exit(
            trade_id=self.strategy.current_trade.strategy_trade_id if self.strategy.current_trade else "UNKNOWN",
            leg_data=leg.to_dict(),
        )

        self._save_state(self.strategy.current_trade)

        # Historical Database Persistence (Non-blocking / Isolated)
        await self._safe_db_persist_leg_exit(leg, order)

        # Alert Notification
        await self.alert_service.send(
            severity=AlertSeverity.WARNING,
            event="SL_TRIGGERED",
            message=f"⚠️ STOP LOSS triggered on {leg.option_type.value} leg ({leg.symbol}). Filled @ ${fill_px:.2f}. Realized P&L: ${leg.realized_pnl:.2f}",
            trade_id=self.strategy.current_trade.strategy_trade_id if self.strategy.current_trade else None,
        )

    async def _handle_strategy_exit_trigger(self, trade: StrategyTrade):
        """Handle 17:15 EOD square-off trigger."""
        await self.execution_engine.execute_trade_square_off(trade, reason="EOD_EXIT")
        self.trade_logger.log_trade_completion(trade.to_dict())
        self._save_state(trade)

        # Historical Database Persistence (Non-blocking / Isolated)
        await self._safe_db_persist_trade_completion(trade)

        # Alert Notification
        await self.alert_service.send(
            severity=AlertSeverity.SUCCESS,
            event="TRADE_COMPLETED",
            message=f"✅ Strategy trade completed (EOD 17:15). Net P&L: ${trade.net_pnl:.2f}",
            trade_id=trade.strategy_trade_id,
        )

    async def _safe_db_persist_entry(
        self,
        trade: StrategyTrade,
        ce_order: Optional[Any] = None,
        pe_order: Optional[Any] = None,
    ):
        """Safely persist trade entry to database without blocking trading if DB fails."""
        if not self.db_manager.is_connected:
            return
        try:
            async with asyncio.timeout(self.settings.db_timeout_seconds):
                config_snapshot = {
                    "quantity": self.settings.order_quantity,
                    "target_premium": self.settings.target_premium,
                    "premium_tolerance_usd": self.settings.premium_tolerance_usd,
                    "sl_percentage": self.settings.sl_percentage,
                    "max_daily_loss_usd": self.settings.max_daily_loss_usd,
                    "entry_time_ist": self.settings.entry_time_ist,
                    "exit_time_ist": self.settings.exit_time_ist,
                }
                await self.trade_repo.record_entry(
                    trade=trade,
                    ce_order=ce_order,
                    pe_order=pe_order,
                    config_snapshot=config_snapshot,
                )
                self.last_db_operation_time = datetime.now(timezone.utc)
        except Exception as e:
            self.logger.warning(
                f"⚠️ DATABASE: UNAVAILABLE — trading continues using file persistence + exchange reconciliation (Entry persist error: {e})"
            )

    async def _safe_db_persist_leg_exit(
        self,
        leg: StrategyLeg,
        exit_order: Optional[Any] = None,
    ):
        """Safely persist leg exit to database without blocking trading if DB fails."""
        if not self.db_manager.is_connected:
            return
        try:
            async with asyncio.timeout(self.settings.db_timeout_seconds):
                trade_id = self.strategy.current_trade.strategy_trade_id if self.strategy.current_trade else "UNKNOWN"
                await self.trade_repo.record_leg_exit(
                    leg=leg,
                    trade_id=trade_id,
                    exit_order=exit_order,
                    parent_trade=self.strategy.current_trade,
                )
                self.last_db_operation_time = datetime.now(timezone.utc)
        except Exception as e:
            self.logger.warning(
                f"⚠️ DATABASE: UNAVAILABLE — trading continues using file persistence + exchange reconciliation (Leg exit persist error: {e})"
            )

    async def _safe_db_persist_trade_completion(
        self,
        trade: StrategyTrade,
        exit_orders: Optional[List[Any]] = None,
    ):
        """Safely persist trade completion to database without blocking trading if DB fails."""
        if not self.db_manager.is_connected:
            return
        try:
            async with asyncio.timeout(self.settings.db_timeout_seconds):
                await self.trade_repo.record_trade_completion(
                    trade=trade,
                    exit_orders=exit_orders,
                )
                self.last_db_operation_time = datetime.now(timezone.utc)
        except Exception as e:
            self.logger.warning(
                f"⚠️ DATABASE: UNAVAILABLE — trading continues using file persistence + exchange reconciliation (Trade completion persist error: {e})"
            )

    async def _safe_db_persist_reconciliation_update(
        self,
        trade: StrategyTrade,
    ):
        """Safely sync reconciled trade & legs to database without blocking trading if DB fails."""
        if not self.db_manager.is_connected:
            return
        try:
            async with asyncio.timeout(self.settings.db_timeout_seconds):
                await self.trade_repo.upsert_trade(trade)
                if trade.ce_leg:
                    await self.trade_repo.upsert_leg(trade.ce_leg, trade_id=trade.strategy_trade_id)
                if trade.pe_leg:
                    await self.trade_repo.upsert_leg(trade.pe_leg, trade_id=trade.strategy_trade_id)
                self.last_db_operation_time = datetime.now(timezone.utc)
        except Exception as e:
            self.logger.warning(
                f"⚠️ DATABASE: UNAVAILABLE — trading continues using file persistence + exchange reconciliation (Reconciliation sync error: {e})"
            )

    def get_readiness(self) -> Dict[str, Any]:
        """Return readiness status indicating whether the trading engine is ready for trading."""
        is_safe_halt = self.risk_manager.is_kill_switch_active or (
            self._last_reconciliation_result is not None and self._last_reconciliation_result.status == "SAFE_HALT"
        )
        engine_status = "SAFE_HALT" if is_safe_halt else ("RUNNING" if self._running else "STOPPED")
        exchange_avail = "AVAILABLE" if self.delta_adapter.is_connected else "UNAVAILABLE"
        reconcile_status = "SYNCHRONIZED" if (self._last_reconciliation_result and self._last_reconciliation_result.is_synchronized) else "UNSYNCHRONIZED"

        ready = bool(
            self._running
            and not is_safe_halt
            and self.delta_adapter.is_connected
            and (self._last_reconciliation_result is not None and self._last_reconciliation_result.is_synchronized)
        )
        return {
            "ready": ready,
            "engine": engine_status,
            "exchange": exchange_avail,
            "reconciliation": reconcile_status,
        }

    def get_status(self) -> Dict[str, Any]:
        """Return engine health and trade snapshot for API / CLI inspection."""
        now = datetime.now(timezone.utc)
        uptime = (now - self.start_time).total_seconds() if self._running else 0.0
        is_safe_halt = self.risk_manager.is_kill_switch_active or (
            self._last_reconciliation_result is not None and self._last_reconciliation_result.status == "SAFE_HALT"
        )
        engine_status = "SAFE_HALT" if is_safe_halt else ("RUNNING" if self._running else "STOPPED")

        trade = self.strategy.current_trade
        trade_data = None
        if trade:
            self._refresh_unrealized_from_mark_cache(trade)
            ce_bracket = trade.ce_leg.bracket_order_id if trade.ce_leg else None
            pe_bracket = trade.pe_leg.bracket_order_id if trade.pe_leg else None
            ce_unrealized = round(trade.ce_leg.compute_unrealized_pnl(), 4) if (trade.ce_leg and trade.ce_leg.is_open) else 0.0
            pe_unrealized = round(trade.pe_leg.compute_unrealized_pnl(), 4) if (trade.pe_leg and trade.pe_leg.is_open) else 0.0
            total_unrealized = round(ce_unrealized + pe_unrealized, 4)
            trade.total_unrealized_pnl = total_unrealized
            trade_data = {
                "trade_id": trade.strategy_trade_id,
                "strategy_name": trade.strategy_name,
                "trade_state": trade.state.value,
                "entry_timestamp": trade.ce_leg.entry_timestamp if trade.ce_leg else (trade.pe_leg.entry_timestamp if trade.pe_leg else None),
                "ce_symbol": trade.ce_leg.symbol if trade.ce_leg else None,
                "pe_symbol": trade.pe_leg.symbol if trade.pe_leg else None,
                "ce_status": trade.ce_leg.status.value if trade.ce_leg else None,
                "pe_status": trade.pe_leg.status.value if trade.pe_leg else None,
                "ce_strike": trade.ce_leg.strike if trade.ce_leg else None,
                "pe_strike": trade.pe_leg.strike if trade.pe_leg else None,
                "ce_quantity": trade.ce_leg.quantity if trade.ce_leg else None,
                "pe_quantity": trade.pe_leg.quantity if trade.pe_leg else None,
                "ce_entry_price": trade.ce_leg.entry_fill_price if trade.ce_leg else None,
                "pe_entry_price": trade.pe_leg.entry_fill_price if trade.pe_leg else None,
                "ce_current_price": getattr(trade.ce_leg, "current_price", None) if trade.ce_leg else None,
                "pe_current_price": getattr(trade.pe_leg, "current_price", None) if trade.pe_leg else None,
                "ce_unrealized_pnl": ce_unrealized,
                "pe_unrealized_pnl": pe_unrealized,
                "ce_sl_price": trade.ce_leg.sl_price if trade.ce_leg else None,
                "pe_sl_price": trade.pe_leg.sl_price if trade.pe_leg else None,
                "ce_native_bracket_active": bool(ce_bracket),
                "pe_native_bracket_active": bool(pe_bracket),
                "ce_bracket_order_id": ce_bracket,
                "pe_bracket_order_id": pe_bracket,
                "total_realized_pnl": trade.total_realized_pnl,
                "total_unrealized_pnl": total_unrealized,
            }


        ws_stale = False
        if hasattr(self.delta_adapter, "is_ws_stale"):
            ws_stale = self.delta_adapter.is_ws_stale()

        return {
            "engine": {
                "status": engine_status,
                "uptime_seconds": round(uptime, 2),
                "start_time": self.start_time.isoformat(),
                "environment": self.settings.delta_env.value.upper(),
                "dry_run": self.settings.dry_run,
                "kill_switch": self.risk_manager.is_kill_switch_active,
                "strategy_name": self.settings.strategy,
                "strategy_active": self.strategy.is_active,
            },
            "exchange": {
                "rest_connected": self.delta_adapter.is_connected,
                "ws_connected": getattr(getattr(self.delta_adapter, "ws_client", None), "is_connected", self.delta_adapter.is_connected),
                "last_rest_request_time": self.last_rest_request_time.isoformat() if self.last_rest_request_time else None,
                "last_ws_tick_time": self.last_ws_tick_time.isoformat() if self.last_ws_tick_time else None,
                "ws_stale": ws_stale,
            },
            "reconciliation": {
                "is_synchronized": self._last_reconciliation_result.is_synchronized if self._last_reconciliation_result else False,
                "status": self._last_reconciliation_result.status if self._last_reconciliation_result else "PENDING",
                "last_reconciliation_time": self.last_reconciliation_time.isoformat() if self.last_reconciliation_time else None,
                "latest_discrepancy": self._last_reconciliation_result.details if (self._last_reconciliation_result and not self._last_reconciliation_result.is_synchronized) else None,
            },
            "database": {
                "connected": self.db_manager.is_connected,
                "status": "AVAILABLE" if self.db_manager.is_connected else "UNAVAILABLE",
                "last_db_operation": self.last_db_operation_time.isoformat() if self.last_db_operation_time else None,
            },
            "watchdog": {
                "last_heartbeat": self.last_heartbeat_time.isoformat() if self.last_heartbeat_time else None,
                "last_loop": self.last_loop_time.isoformat() if self.last_loop_time else None,
            },
            "current_trade": trade_data,
            "alerts": {
                "recent_count": len(self.alert_service.get_recent_alerts()),
                "recent_alerts": self.alert_service.get_recent_alerts()[-10:],
            },
            # Top-level legacy keys for backward compatibility
            "status": engine_status,
            "environment": self.settings.delta_env.value.upper(),
            "kill_switch": self.risk_manager.is_kill_switch_active,
            "connected_exchange": self.delta_adapter.is_connected,
            "strategy": self.settings.strategy,
            "strategy_active": self.strategy.is_active,
            "trading_enabled": self.strategy.is_active and not self.risk_manager.is_kill_switch_active,
            "underlying": self.settings.underlying,
        }

    async def get_account_balances(self) -> Any:
        """Fetch account balances from connected exchange adapter."""
        return await self.delta_adapter.get_account_balances()


