"""Execution engine interface."""

from abc import ABC, abstractmethod
from typing import Optional, List, Tuple
from src.core.models.order import OrderRequest, Order
from src.core.models.trade import StrategyTrade, StrategyLeg


class IExecutionEngine(ABC):
    """Abstract interface for order execution orchestrators."""

    @abstractmethod
    async def execute_order(self, request: OrderRequest) -> Order:
        """Place single order with timeout recovery."""
        pass

    @abstractmethod
    async def execute_strangle_entry(
        self,
        trade: StrategyTrade,
        ce_request: OrderRequest,
        pe_request: OrderRequest,
    ) -> Tuple[bool, Optional[Order], Optional[Order]]:
        """
        Execute two-leg short strangle entry.
        Implements deterministic emergency unwinding if one leg fails.
        """
        pass

    @abstractmethod
    async def execute_leg_exit(
        self,
        leg: StrategyLeg,
        reason: str,
    ) -> Optional[Order]:
        """Execute market/aggressive exit for a single leg (e.g. SL or square-off)."""
        pass

    @abstractmethod
    async def execute_trade_square_off(self, trade: StrategyTrade, reason: str = "EOD_EXIT") -> bool:
        """Close all remaining open legs in a strategy trade and verify 0 position."""
        pass
