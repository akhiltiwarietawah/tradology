"""Runtime adapter for BTC 0DTE Long Straddle Strategy."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from src.core.interfaces.exchange import BaseExchangeAdapter
from src.core.models.instrument import Instrument
from src.core.models.order import OrderRequest, OrderSide, OrderType
from src.core.models.trade import StrategyTrade, StrategyState, LegStatus
from src.platform.execution.activity_logger import ExecutionActivityLogger
from src.platform.persistence.fill_bridge import PlatformFillBridge
from src.platform.execution.group_repository import StrangleGroupRepository
from src.platform.ledger.repository import PlatformLedgerRepository
from src.platform.execution.pipeline import OrderExecutionPipeline
from src.platform.execution.preflight import StranglePreflightChecker
from src.platform.execution.multi_leg_coordinator import StrangleExecutionCoordinator
from src.platform.persistence.exit_ledger import PlatformExitLedger
from src.platform.runtime.models import RuntimeContext, RuntimeStatus
from src.platform.runtime.safety import ExecutionSafetyChecker
from src.platform.runtime.strategy_adapter_base import StrategyRuntimeAdapter
from src.reconciliation.reconciler import StateReconciler
from src.strategies.btc_0dte_long_straddle.models import LongStraddleConfig
from src.strategies.btc_0dte_long_straddle.strategy import BTC0DTELongStraddleStrategy


class Btc0DteLongStraddleRuntimeAdapter(StrategyRuntimeAdapter):
    """Integrated runtime bridge for BTC 0DTE Long Straddle on Delta Exchange."""

    def __init__(
        self,
        *,
        context: RuntimeContext,
        pipeline: OrderExecutionPipeline,
        group_repository: StrangleGroupRepository,
        safety_checker: ExecutionSafetyChecker,
        activity_logger: ExecutionActivityLogger,
        trade_repository: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.context = context
        self.pipeline = pipeline
        self.group_repository = group_repository
        self.safety_checker = safety_checker
        self.activity_logger = activity_logger
        self.logger = logger or logging.getLogger("btc_0dte_long_straddle_runtime_adapter")
        self._delta_adapter: Optional[BaseExchangeAdapter] = None
        self._market_fresh = True
        self._strategy: Optional[BTC0DTELongStraddleStrategy] = None
        self._reconciler: Optional[StateReconciler] = None
        self._runtime_status = "STOPPED"
        self._trade_repository = trade_repository
        self._fill_bridge = (
            PlatformFillBridge(trade_repository, PlatformLedgerRepository(trade_repository.db), logger)
            if trade_repository
            else None
        )
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

    def bind_exchange(self, adapter: BaseExchangeAdapter) -> None:
        self._delta_adapter = adapter

    async def initialize(self) -> None:
        if not self._delta_adapter:
            raise RuntimeError("Exchange adapter must be bound before initializing Btc0DteLongStraddleRuntimeAdapter")

        cfg = LongStraddleConfig.from_env()
        # Override config from database context if provided
        overrides = self.context.risk_overrides or {}
        if "position_sizing_mode" in overrides:
            cfg.position_sizing_mode = overrides["position_sizing_mode"]
        if "fixed_lots" in overrides:
            cfg.fixed_lots = int(overrides["fixed_lots"])
        if "dynamic_margin_pct" in overrides:
            cfg.dynamic_margin_pct = float(overrides["dynamic_margin_pct"])

        self._strategy = BTC0DTELongStraddleStrategy(
            exchange_adapter=self._delta_adapter,
            config=cfg,
            logger=self.logger,
        )
        self._strategy.set_execution_callbacks(
            on_entry=self._handle_entry,
        )
        self._reconciler = StateReconciler(
            exchange_adapter=self._delta_adapter,
            logger=self.logger,
        )
        self._runtime_status = "INITIALIZED"

    async def _handle_entry(
        self,
        trade: StrategyTrade,
        ce: Instrument,
        pe: Instrument,
        ce_price: float,
        pe_price: float,
    ) -> None:
        """Execute simultaneous 10 lots Long Straddle BUY orders."""
        self.logger.info(
            f"Btc0DteLongStraddleRuntimeAdapter: executing LONG STRADDLE entry for "
            f"CE={ce.symbol} and PE={pe.symbol}"
        )

        for leg in trade.legs:
            order_req = OrderRequest(
                symbol=leg.instrument.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET if self._strategy.config.entry_order_type == "market" else OrderType.LIMIT,
                quantity=leg.quantity,
                price=leg.instrument.mark_price or ce_price,
            )
            try:
                order = await self._delta_adapter.create_order(order_req)
                leg.order_id = getattr(order, "id", None) or getattr(order, "order_id", "simulated")
                leg.status = LegStatus.OPEN
                self.logger.info(f"Bought {leg.quantity} lots of {leg.symbol} (Order ID: {leg.order_id})")
            except Exception as e:
                self.logger.error(f"Failed to execute buy order for {leg.symbol}: {e}", exc_info=True)
                leg.status = LegStatus.FAILED

        trade.state = StrategyState.IN_PROGRESS

    async def start(self) -> None:
        if not self._strategy:
            await self.initialize()
        self._runtime_status = "RUNNING"
        self.logger.info("Btc0DteLongStraddleRuntimeAdapter started.")

    async def stop(self) -> None:
        self._runtime_status = "STOPPED"
        self.logger.info("Btc0DteLongStraddleRuntimeAdapter stopped.")

    async def on_tick(self, timestamp: float) -> None:
        if self._strategy and self._runtime_status == "RUNNING":
            await self._strategy.on_tick(timestamp)

    def get_runtime_status(self) -> Dict[str, Any]:
        return {
            "status": self._runtime_status,
            "strategy_code": "btc_0dte_long_straddle",
            "is_market_data_fresh": self.is_market_data_fresh,
            "sizing_mode": self._strategy.config.position_sizing_mode if self._strategy else "unknown",
            "fixed_lots": self._strategy.config.fixed_lots if self._strategy else 10,
        }
