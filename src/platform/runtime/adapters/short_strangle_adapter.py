"""Short strangle strategy bridge — wires BTCShortStrangleStrategy without modifying strategy.py."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz

from src.config.constants import IST_TIMEZONE
from src.config.settings import Settings, get_settings
from src.core.models.instrument import Instrument
from src.core.models.trade import LegStatus, StrategyLeg, StrategyTrade
from src.exchanges.delta.adapter import DeltaExchangeAdapter
from src.logging_utils.logger import TradeLogger
from src.persistence.trade_repository import TradeRepository
from src.platform.execution.activity_logger import ExecutionActivityLogger
from src.platform.execution.group_repository import StrangleGroupRepository
from src.platform.execution.models import StrangleGroupStatus
from src.platform.execution.multi_leg_coordinator import StrangleExecutionCoordinator
from src.platform.execution.pipeline import OrderExecutionPipeline
from src.platform.execution.preflight import StranglePreflightChecker
from src.platform.persistence.exit_ledger import PlatformExitLedger
from src.platform.persistence.fill_bridge import PlatformFillBridge
from src.platform.ledger.repository import PlatformLedgerRepository
from src.platform.runtime.models import RuntimeContext
from src.platform.runtime.safety import ExecutionSafetyChecker
from src.platform.runtime.strategy_adapter_base import StrategyRuntimeAdapter
from src.reconciliation.reconciler import StateReconciler
from src.strategies.short_strangle.models import ShortStrangleConfig
from src.strategies.short_strangle.strategy import BTCShortStrangleStrategy


class ShortStrangleRuntimeAdapter(StrategyRuntimeAdapter):
    """Per-runtime short strangle with multi-leg coordinator for safe atomic entry."""

    def __init__(
        self,
        *,
        context: RuntimeContext,
        pipeline: OrderExecutionPipeline,
        credentials: Dict[str, str],
        safety_checker: ExecutionSafetyChecker,
        group_repository: StrangleGroupRepository,
        activity_logger: Optional[ExecutionActivityLogger] = None,
        trade_repository: Optional[TradeRepository] = None,
        settings: Optional[Settings] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.context = context
        self.pipeline = pipeline
        self.credentials = credentials
        self.safety_checker = safety_checker
        self.settings = settings or get_settings()
        self.logger = logger or logging.getLogger("short_strangle_runtime_adapter")
        self._market_fresh = True
        self._delta_adapter: Optional[DeltaExchangeAdapter] = None
        self._strategy: Optional[BTCShortStrangleStrategy] = None
        self._reconciler: Optional[StateReconciler] = None
        self._runtime_status = "STOPPED"
        self._trade_repository = trade_repository
        self._fill_bridge = (
            PlatformFillBridge(trade_repository, PlatformLedgerRepository(trade_repository.db), logger)
            if trade_repository
            else None
        )
        self._exit_ledger: Optional[PlatformExitLedger] = None
        self._coordinator = StrangleExecutionCoordinator(
            context=context,
            pipeline=pipeline,
            group_repository=group_repository,
            preflight=StranglePreflightChecker(safety_checker=safety_checker, group_repository=group_repository),
            activity_logger=activity_logger,
            fill_bridge=self._fill_bridge,
            exit_ledger=None,
            logger=logger,
        )

    @property
    def is_market_data_fresh(self) -> bool:
        if self._delta_adapter and hasattr(self._delta_adapter, "is_ws_stale"):
            self._market_fresh = not self._delta_adapter.is_ws_stale()
        return self._market_fresh

    @staticmethod
    def _find_leg(trade: StrategyTrade, leg_id: str) -> Optional[StrategyLeg]:
        if trade.ce_leg and trade.ce_leg.leg_id == leg_id:
            return trade.ce_leg
        if trade.pe_leg and trade.pe_leg.leg_id == leg_id:
            return trade.pe_leg
        return None

    async def initialize(self) -> None:
        is_testnet = self.context.is_testnet
        from src.config.constants import LIVE_REST_URL, LIVE_WS_URL, TESTNET_REST_URL, TESTNET_WS_URL

        rest = TESTNET_REST_URL if is_testnet else LIVE_REST_URL
        ws = TESTNET_WS_URL if is_testnet else LIVE_WS_URL
        self._delta_adapter = DeltaExchangeAdapter(
            rest_url=rest,
            ws_url=ws,
            api_key=self.credentials.get("api_key", ""),
            api_secret=self.credentials.get("api_secret", ""),
            is_testnet=is_testnet,
            logger=self.logger,
        )
        await self._delta_adapter.initialize()

        trade_logger = TradeLogger(logs_dir=self.settings.logs_dir)
        self._reconciler = StateReconciler(
            exchange_adapter=self._delta_adapter,
            trade_logger=trade_logger,
            logger=self.logger,
        )

        overrides = self.context.risk_overrides or {}
        cfg = ShortStrangleConfig(
            underlying=overrides.get("underlying", self.settings.underlying),
            target_premium=float(overrides.get("target_premium", self.settings.target_premium)),
            premium_tolerance_usd=float(overrides.get("premium_tolerance_usd", self.settings.premium_tolerance_usd)),
            quantity=float(overrides.get("quantity", self.settings.order_quantity)),
            sl_percentage=float(overrides.get("sl_percentage", self.settings.sl_percentage)),
            entry_time=self.settings.get_parsed_entry_time(),
            entry_window_minutes=int(overrides.get("entry_window_minutes", self.settings.entry_window_minutes)),
            exit_time=self.settings.get_parsed_exit_time(),
        )
        self._strategy = BTCShortStrangleStrategy(self._delta_adapter, cfg, logger=self.logger)
        if self._fill_bridge and self._trade_repository:
            from src.platform.execution.lifecycle_repository import OrderLifecycleRepository

            self._exit_ledger = PlatformExitLedger(
                context=self.context,
                strategy=self._strategy,
                fill_bridge=self._fill_bridge,
                lifecycle_repo=OrderLifecycleRepository(self._trade_repository.db),
                trade_repository=self._trade_repository,
                logger=self.logger,
            )
            self._coordinator.exit_ledger = self._exit_ledger
        self._strategy.set_execution_callbacks(
            on_entry=self._handle_entry,
            on_sl=self._handle_sl,
            on_exit=self._handle_exit,
        )

    async def start(self) -> None:
        if not self._strategy:
            await self.initialize()
        assert self._strategy is not None and self._reconciler is not None
        if self._strategy.current_trade:
            result = await self._reconciler.reconcile(self._strategy.current_trade)
            if not result.is_synchronized:
                self.pipeline.halt_new_entries("Reconciliation failed at start")
                return
            if self._exit_ledger:
                trade = self._strategy.current_trade
                for leg in (trade.ce_leg, trade.pe_leg):
                    if (
                        leg
                        and leg.exit_reason == "EXCHANGE_CLOSE"
                        and leg.status == LegStatus.MANUALLY_CLOSED
                        and leg.exit_price is not None
                    ):
                        await self._exit_ledger.persist_reconciled_exit(trade, leg)
        await self._strategy.start()
        self._runtime_status = "RUNNING"

    async def stop(self) -> None:
        if self._strategy:
            await self._strategy.stop()
        if self._delta_adapter:
            await self._delta_adapter.close()
        self._runtime_status = "STOPPED"

    async def on_timer(self, now: datetime) -> None:
        if not self._strategy or self._runtime_status != "RUNNING":
            return
        ist = now.astimezone(IST_TIMEZONE) if now.tzinfo else pytz.utc.localize(now).astimezone(IST_TIMEZONE)
        await self._strategy.on_timer(ist, [])

    async def on_market_event(self, event) -> None:
        if not self._strategy:
            return
        from src.core.models.market_data import Ticker

        ticker = Ticker(
            symbol=event.symbol,
            mark_price=event.mark_price,
            best_bid=event.best_bid,
            best_ask=event.best_ask,
        )
        await self._strategy.on_tick(ticker)

    def get_expected_positions(self) -> List[Dict[str, Any]]:
        if not self._strategy or not self._strategy.current_trade:
            return []
        return [{"symbol": leg.symbol, "size": -leg.quantity} for leg in self._strategy.current_trade.get_open_legs()]

    def export_state(self) -> Dict[str, Any]:
        trade = self._strategy.current_trade if self._strategy else None
        return {
            "strategy_code": "short_strangle",
            "has_trade": trade is not None,
            "trade_state": trade.state.value if trade else None,
            "trade_id": trade.strategy_trade_id if trade else None,
            "runtime_status": self._runtime_status,
            "expected_positions": self.get_expected_positions(),
            "entries_halted": self.pipeline.entries_halted,
        }

    async def restore_state(self, state: Dict[str, Any]) -> None:
        self._runtime_status = state.get("runtime_status", "STOPPED")
        if state.get("entries_halted"):
            self.pipeline.halt_new_entries("Restored halted state")

    async def _handle_entry(
        self,
        trade: StrategyTrade,
        ce_inst: Instrument,
        pe_inst: Instrument,
        ce_est: float,
        pe_est: float,
    ) -> None:
        result = await self._coordinator.execute_strangle_entry(
            trade,
            ce_inst,
            pe_inst,
            ce_est,
            pe_est,
            runtime_status=self._runtime_status,
            market_data_fresh_fn=lambda: self.is_market_data_fresh,
            expected_positions=self.get_expected_positions(),
        )
        if result.success and self._strategy and result.ce_result and result.pe_result and trade.ce_leg and trade.pe_leg:
            ce_price = float(result.ce_result.average_price or ce_est)
            pe_price = float(result.pe_result.average_price or pe_est)
            self._strategy.on_entry_filled(
                trade,
                ce_fill_price=ce_price,
                pe_fill_price=pe_price,
                ce_order_id=result.ce_result.exchange_order_id or result.ce_result.client_order_id,
                pe_order_id=result.pe_result.exchange_order_id or result.pe_result.client_order_id,
                ce_client_order_id=result.ce_result.client_order_id,
                pe_client_order_id=result.pe_result.client_order_id,
            )
        elif result.status in {StrangleGroupStatus.RECOVERY_REQUIRED, StrangleGroupStatus.UNWIND_FAILED}:
            self.pipeline.halt_new_entries(result.message or result.status.value)

    async def _handle_sl(self, leg: StrategyLeg, current_price: float) -> None:
        from src.platform.execution.client_order_ids import build_client_order_id
        from src.platform.execution.models import OrderIntent

        trade = self._strategy.current_trade if self._strategy else None
        if not trade:
            return
        signal_key = f"sl_{trade.strategy_trade_id}_{leg.leg_id}"
        intent = OrderIntent(
            signal_key=signal_key,
            client_order_id=build_client_order_id(
                strategy_account_id=self.context.strategy_account_id,
                signal_key=signal_key,
                leg_role="SL",
                action="exit",
            ),
            symbol=leg.symbol,
            side="buy",
            quantity=leg.quantity,
            instrument_id=leg.instrument_id,
            reduce_only=True,
            metadata={"leg_id": leg.leg_id, "allow_when_halted": True},
        )
        result = await self.pipeline.process_intent(
            intent,
            runtime_status=self._runtime_status,
            market_data_fresh=self.is_market_data_fresh,
            leg_role="SL",
        )
        if self._exit_ledger:
            await self._exit_ledger.persist_exit(
                trade=trade,
                leg=leg,
                result=result,
                exit_reason="STOP_LOSS",
                fee=float(result.fee or 0),
            )

    async def _handle_exit(self, trade: StrategyTrade) -> None:
        from src.platform.execution.client_order_ids import build_client_order_id
        from src.platform.execution.models import OrderIntent

        for leg in trade.get_open_legs():
            signal_key = f"exit_{trade.strategy_trade_id}_{leg.leg_id}"
            intent = OrderIntent(
                signal_key=signal_key,
                client_order_id=build_client_order_id(
                    strategy_account_id=self.context.strategy_account_id,
                    signal_key=signal_key,
                    leg_role="EXIT",
                    action="exit",
                ),
                symbol=leg.symbol,
                side="buy",
                quantity=leg.quantity,
                instrument_id=leg.instrument_id,
                reduce_only=True,
                metadata={"leg_id": leg.leg_id, "allow_when_halted": True},
            )
            result = await self.pipeline.process_intent(
                intent,
                runtime_status=self._runtime_status,
                market_data_fresh=self.is_market_data_fresh,
                leg_role="EXIT",
            )
            if self._exit_ledger:
                await self._exit_ledger.persist_exit(
                    trade=trade,
                    leg=leg,
                    result=result,
                    exit_reason="EOD_EXIT",
                    fee=float(result.fee or 0),
                )
