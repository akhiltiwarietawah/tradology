"""Order Manager providing deterministic client order ID generation and idempotency."""

import time
import logging
from typing import Dict, Optional, Set
from src.core.models.order import Order, OrderRequest, OrderSide, OrderType, OrderState


class OrderManager:
    """Manages order idempotency, client order IDs, and order tracking."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("order_manager")
        self._orders_by_client_id: Dict[str, Order] = {}
        self._orders_by_id: Dict[str, Order] = {}
        self._in_flight_client_ids: Set[str] = set()

    def generate_client_order_id(
        self,
        strategy_name: str,
        trade_id: str,
        leg_name: str,
        side: OrderSide,
        action: str = "entry",
    ) -> str:
        """Generate unique deterministic client order ID (Delta max length <= 32 chars)."""
        ts = int(time.time() * 1000)
        # Format: S_{YYMMDD_HHMMSS}_{leg}_{act}_{side}_{ts5} (strictly <= 32 chars)
        clean_trade_id = trade_id.replace("STRANGLE_", "")
        if len(clean_trade_id) >= 15 and clean_trade_id.startswith("20"):
            clean_trade_id = clean_trade_id[2:]
        cid = f"S_{clean_trade_id}_{leg_name[:2]}_{action[:3]}_{side.value[:1]}_{ts % 100000}"
        return cid[:32]

    def register_order_attempt(self, client_order_id: str) -> bool:
        """Register submission attempt. Returns False if duplicate."""
        if client_order_id in self._in_flight_client_ids or client_order_id in self._orders_by_client_id:
            self.logger.warning(f"Duplicate client_order_id detected: {client_order_id}")
            return False
        self._in_flight_client_ids.add(client_order_id)
        return True

    def record_order(self, order: Order):
        """Record order state after placement."""
        if order.client_order_id:
            self._orders_by_client_id[order.client_order_id] = order
            self._in_flight_client_ids.discard(order.client_order_id)
        if order.order_id:
            self._orders_by_id[order.order_id] = order

    def get_order_by_client_id(self, client_order_id: str) -> Optional[Order]:
        return self._orders_by_client_id.get(client_order_id)

    def get_order_by_id(self, order_id: str) -> Optional[Order]:
        return self._orders_by_id.get(order_id)
