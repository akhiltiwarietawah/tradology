"""In-memory unified state store for fast strategy and order queries."""

import logging
from typing import Dict, Optional, List
from src.core.models.trade import StrategyTrade
from src.core.models.position import Position
from src.core.models.order import Order


class StateStore:
    """In-memory cache of active strategy trades, orders, and positions."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("state_store")
        self._active_trades: Dict[str, StrategyTrade] = {}  # trade_id -> StrategyTrade
        self._historical_trades: List[StrategyTrade] = []
        self._positions: Dict[str, Position] = {}           # symbol -> Position
        self._orders: Dict[str, Order] = {}                 # order_id -> Order

    def set_active_trade(self, trade: StrategyTrade):
        self._active_trades[trade.strategy_trade_id] = trade

    def get_active_trade(self, trade_id: str) -> Optional[StrategyTrade]:
        return self._active_trades.get(trade_id)

    def get_latest_trade(self) -> Optional[StrategyTrade]:
        if self._active_trades:
            return list(self._active_trades.values())[-1]
        if self._historical_trades:
            return self._historical_trades[-1]
        return None

    def archive_trade(self, trade: StrategyTrade):
        if trade.strategy_trade_id in self._active_trades:
            del self._active_trades[trade.strategy_trade_id]
        self._historical_trades.append(trade)

    def update_position(self, position: Position):
        self._positions[position.symbol] = position

    def get_position(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    def get_all_positions(self) -> List[Position]:
        return list(self._positions.values())

    def update_order(self, order: Order):
        if order.order_id:
            self._orders[order.order_id] = order

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)
