"""Strategy base interface providing lifecycle execution hooks."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime

from src.core.models.market_data import Ticker
from src.core.models.order import Order
from src.core.models.trade import StrategyTrade


class IStrategy(ABC):
    """Abstract interface for algorithmic trading strategies."""

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Unique identifier for this strategy (e.g. 'short_strangle')."""
        pass

    @property
    @abstractmethod
    def current_trade(self) -> Optional[StrategyTrade]:
        """Get the current active or last completed StrategyTrade object."""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize strategy state and load persisted records."""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start strategy execution."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop strategy execution gracefully."""
        pass

    @abstractmethod
    async def on_tick(self, ticker: Ticker) -> None:
        """Handle incoming market data tick."""
        pass

    @abstractmethod
    async def on_order_update(self, order: Order) -> None:
        """Handle order status and fill updates."""
        pass

    @abstractmethod
    async def on_timer(self, now_ist: datetime) -> None:
        """Periodic timer event (e.g. evaluating 09:00 entry or 17:15 exit)."""
        pass
