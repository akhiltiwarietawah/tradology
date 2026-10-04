"""Runtime adapter for BTC 1-DTE short strangle (parso 17:25 exit + exchange bracket SL)."""

from __future__ import annotations

import asyncio
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
from src.strategies.btc_1dte_strangle.models import Btc1DteStrangleConfig
from src.strategies.btc_1dte_strangle.sizing import contracts_for_strangle, effective_equity
from src.strategies.btc_1dte_strangle.strategy import BTC1DteShortStrangleStrategy


def _extract_bracket_id(res: Any) -> str:
    if isinstance(res, (int, str)) and str(res).strip() and str(res).strip() not in ("0", "None"):
        return str(res).strip()
    if isinstance(res, dict):
        for key in ("id", "order_id", "bracket_id", "bracket_order_id"):
            val = res.get(key)
            if val is not None and str(val).strip() and str(val).strip() not in ("0", "None"):
                return str(val).strip()
        inner = res.get("result") or res.get("data")
        if isinstance(inner, dict):
            for key in ("id", "order_id", "bracket_id", "bracket_order_id"):
                val = inner.get(key)
                if val is not None and str(val).strip() and str(val).strip() not in ("0", "None"):
                    return str(val).strip()
        elif isinstance(inner, (int, str)) and str(inner).strip():
            return str(inner).strip()
    return ""


class Btc1DteStrangleRuntimeAdapter(StrategyRuntimeAdapter):
    """Integrated runtime bridge for 1-DTE strangle."""

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
        self.logger = logger or logging.getLogger("btc_1dte_strangle_runtime_adapter")
        self._market_fresh = True
        self._delta_adapter: Optional[DeltaExchangeAdapter] = None
        self._strategy: Optional[BTC1DteShortStrangleStrategy] = None
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

    async def _wallet_equity_usd(self) -> float:
        overrides = self.context.risk_overrides or {}
        if overrides.get("effective_equity_usd") is not None:
            return float(overrides["effective_equity_usd"])
        virtual = float(overrides.get("virtual_equity_usd") or overrides.get("starting_equity_usd") or 0.0)
        wallet = 0.0
        if self._delta_adapter:
            try:
                bal = await self._delta_adapter.get_account_balances()
                for asset in bal.balances:
                    if asset.asset.upper() in ("USD", "USDT", "USDC"):
                        wallet += float(asset.available_balance)
            except Exception as exc:
                self.logger.warning("Could not fetch wallet balance for sizing: %s", exc)
        if wallet > 0 and virtual > 0:
            return effective_equity(wallet, virtual)
        if wallet > 0:
            return wallet
        if virtual > 0:
            return virtual
        return 1000.0

    async def _resolve_quantity(self, ce_est: float, pe_est: float) -> int:
        overrides = self.context.risk_overrides or {}
        margin_pct = float(overrides.get("margin_pct", 0.25))
        eq = await self._wallet_equity_usd()
        cv = 0.001
        return contracts_for_strangle(
            eq,
            ce_est,
            pe_est,
            contract_value=cv,
            margin_pct=margin_pct,
        )

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
        cfg = Btc1DteStrangleConfig(
            underlying=overrides.get("underlying", self.settings.underlying),
            sl_percentage=float(overrides.get("sl_percentage", self.settings.sl_percentage)),
            margin_pct=float(overrides.get("margin_pct", 0.25)),
            entry_window_minutes=int(overrides.get("entry_window_minutes", 15)),
            enable_combined_take_profit=bool(overrides.get("enable_combined_take_profit", False)),
            take_profit_base_usd=float(overrides.get("take_profit_base_usd", 3.0)),
        )
        self._strategy = BTC1DteShortStrangleStrategy(self._delta_adapter, cfg, logger=self.logger)
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
            on_tp=self._handle_tp if cfg.enable_combined_take_profit else None,
            resolve_quantity=self._resolve_quantity,
        )

    async def _attach_brackets(self, trade: StrategyTrade) -> bool:
        """Native Delta bracket SL only (100% leg stop @ 2× fill), same pattern as 0-DTE engine."""
        if not self._delta_adapter:
            return False
        ok = True
        for leg in (trade.ce_leg, trade.pe_leg):
            if not leg or not leg.sl_price or leg.sl_price <= 0:
                continue
            attached = False
            for attempt in range(1, 3):
                try:
                    self.logger.info(
                        "Attaching native bracket SL for %s product=%s SL=$%.2f (attempt %s/2)",
                        leg.symbol,
                        leg.instrument_id,
                        leg.sl_price,
                        attempt,
                    )
                    res = await self._delta_adapter.create_bracket_order(
                        instrument_id=leg.instrument_id,
                        stop_loss_price=float(leg.sl_price),
                        take_profit_price=None,
                        stop_trigger_method="mark_price",
                        order_type="market_order",
                    )
                    bracket_id = _extract_bracket_id(res)
                    leg.bracket_order_id = bracket_id or None
                    leg.sl_order_id = bracket_id or None
                    leg.exchange_sl_active = True
                    attached = True
                    self.logger.info(
                        "Native bracket SL active on exchange for %s (id=%s, trigger=mark_price)",
                        leg.symbol,
                        bracket_id or "unknown",
                    )
                    break
                except Exception as exc:
                    self.logger.warning(
                        "Bracket SL attempt %s/2 failed for %s: %s",
                        attempt,
                        leg.symbol,
                        exc,
                    )
                    if attempt < 2:
                        await asyncio.sleep(1.0)
            if not attached:
                self.logger.critical("Native bracket SL failed for %s after 2 attempts", leg.symbol)
                ok = False
        return ok

    async def start(self) -> None:
        if not self._strategy:
            await self.initialize()
        assert self._strategy is not None and self._reconciler is not None
        if self._strategy.current_trade:
            result = await self._reconciler.reconcile(self._strategy.current_trade)
            if not result.is_synchronized:
                self.pipeline.halt_new_entries("Reconciliation failed at start")
                return
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
            "strategy_code": "btc_1dte_strangle",
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

    async def _on_option_ticker(self, ticker) -> None:
        if self._strategy:
            await self._strategy.on_tick(ticker)

    async def _handle_entry(
        self,
        trade: StrategyTrade,
        ce_inst: Instrument,
        pe_inst: Instrument,
        ce_est: float,
        pe_est: float,
    ) -> None:
        self._strategy.record_entry_attempt()
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
            brackets_ok = await self._attach_brackets(trade)
            if brackets_ok:
                symbols = [leg.symbol for leg in (trade.ce_leg, trade.pe_leg) if leg and leg.symbol]
                if symbols and self._delta_adapter:
                    try:
                        await self._delta_adapter.subscribe_market_data(symbols, self._on_option_ticker)
                    except Exception as exc:
                        self.logger.warning("Option ticker subscribe after entry: %s", exc)
            if not brackets_ok:
                self.pipeline.halt_new_entries("Native bracket SL failed after 1-DTE entry")
                await self._handle_exit(trade)
        elif result.status in {StrangleGroupStatus.RECOVERY_REQUIRED, StrangleGroupStatus.UNWIND_FAILED}:
            self.pipeline.halt_new_entries(result.message or result.status.value)

    async def _handle_sl(self, leg: StrategyLeg, current_price: float) -> None:
        await self._submit_leg_exit(leg, exit_reason="STOP_LOSS", leg_role="SL")

    async def _handle_tp(self, trade: StrategyTrade) -> None:
        for leg in trade.get_open_legs():
            await self._submit_leg_exit(leg, exit_reason="TAKE_PROFIT", leg_role="TP", trade=trade)

    async def _handle_exit(self, trade: StrategyTrade) -> None:
        for leg in trade.get_open_legs():
            await self._submit_leg_exit(leg, exit_reason="EOD_EXIT", leg_role="EXIT", trade=trade)

    async def _submit_leg_exit(
        self,
        leg: StrategyLeg,
        *,
        exit_reason: str,
        leg_role: str,
        trade: Optional[StrategyTrade] = None,
    ) -> None:
        from src.platform.execution.client_order_ids import build_client_order_id
        from src.platform.execution.models import OrderIntent

        trade = trade or (self._strategy.current_trade if self._strategy else None)
        if not trade:
            return
        signal_key = f"{exit_reason.lower()}_{trade.strategy_trade_id}_{leg.leg_id}"
        intent = OrderIntent(
            signal_key=signal_key,
            client_order_id=build_client_order_id(
                strategy_account_id=self.context.strategy_account_id,
                signal_key=signal_key,
                leg_role=leg_role,
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
            leg_role=leg_role,
        )
        if self._exit_ledger:
            await self._exit_ledger.persist_exit(
                trade=trade,
                leg=leg,
                result=result,
                exit_reason=exit_reason,
                fee=float(result.fee or 0),
            )
