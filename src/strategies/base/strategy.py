"""Base strategy class providing standard algorithmic trading lifecycle."""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from src.core.interfaces.strategy import IStrategy
from src.core.interfaces.exchange import BaseExchangeAdapter
from src.core.models.market_data import Ticker
from src.core.models.order import Order
from src.core.models.trade import StrategyTrade, StrategyState


class BaseStrategy(IStrategy):
    """Abstract base class for all trading strategies in the engine."""

    def __init__(
        self,
        strategy_name: str,
        exchange_adapter: BaseExchangeAdapter,
        logger: Optional[logging.Logger] = None,
    ):
        self._strategy_name = strategy_name
        self.exchange = exchange_adapter
        self.logger = logger or logging.getLogger(f"strategy.{strategy_name}")
        self._current_trade: Optional[StrategyTrade] = None
        self._active = False

    @property
    def strategy_name(self) -> str:
        return self._strategy_name

    @property
    def current_trade(self) -> Optional[StrategyTrade]:
        return self._current_trade

    @current_trade.setter
    def current_trade(self, value: Optional[StrategyTrade]):
        self._current_trade = value

    @property
    def is_active(self) -> bool:
        return self._active

    async def initialize(self) -> None:
        """Initialize strategy state and resources."""
        self.logger.info(f"Strategy '{self.strategy_name}' initialized.")

    async def start(self) -> None:
        """Start strategy execution."""
        self._active = True
        self.logger.info(f"Strategy '{self.strategy_name}' started.")

    async def stop(self) -> None:
        """Stop strategy execution."""
        self._active = False
        self.logger.info(f"Strategy '{self.strategy_name}' stopped.")

    async def on_tick(self, ticker: Ticker) -> None:
        """Handle market tick (override in concrete strategies)."""
        pass

    async def on_order_update(self, order: Order) -> None:
        """Handle order status change (override in concrete strategies)."""
        pass

    async def on_timer(self, now_ist: datetime) -> None:
        """Handle periodic timer event (override in concrete strategies)."""
        pass
