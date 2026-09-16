"""Delta live execution adapter for platform runtimes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from src.config.constants import LIVE_REST_URL, LIVE_WS_URL, TESTNET_REST_URL, TESTNET_WS_URL
from src.core.models.order import OrderRequest, OrderSide, OrderState, OrderType
from src.exchanges.delta.adapter import DeltaExchangeAdapter
from src.platform.execution.adapter_base import ExecutionAdapter
from src.platform.execution.models import ExecutionLayerMode, ExecutionResult, OrderIntent, OrderLifecycleStatus


class DeltaExecutionAdapter(ExecutionAdapter):
    supports_live_submission = True

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        is_testnet: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        self.logger = logger or logging.getLogger("delta_execution_adapter")
        rest = TESTNET_REST_URL if is_testnet else LIVE_REST_URL
        ws = TESTNET_WS_URL if is_testnet else LIVE_WS_URL
        self._adapter = DeltaExchangeAdapter(
            rest_url=rest,
            ws_url=ws,
            api_key=api_key,
            api_secret=api_secret,
            is_testnet=is_testnet,
            logger=self.logger,
        )

    async def initialize(self) -> bool:
        return await self._adapter.initialize()

    async def close(self) -> None:
        await self._adapter.close()

    @staticmethod
    def map_order_state(state: OrderState) -> OrderLifecycleStatus:
        mapping = {
            OrderState.FILLED: OrderLifecycleStatus.FILLED,
            OrderState.PARTIALLY_FILLED: OrderLifecycleStatus.PARTIALLY_FILLED,
            OrderState.OPEN: OrderLifecycleStatus.ACKNOWLEDGED,
            OrderState.PENDING: OrderLifecycleStatus.ACKNOWLEDGED,
            OrderState.REJECTED: OrderLifecycleStatus.REJECTED,
            OrderState.CANCELLED: OrderLifecycleStatus.CANCELLED,
            OrderState.EXPIRED: OrderLifecycleStatus.EXPIRED,
        }
        return mapping.get(state, OrderLifecycleStatus.UNKNOWN)

    async def place_order(self, intent: OrderIntent) -> ExecutionResult:
        side = OrderSide.BUY if intent.side.lower() in {"buy", "long"} else OrderSide.SELL
        order_type = OrderType.MARKET if intent.order_type.lower() == "market" else OrderType.LIMIT
        request = OrderRequest(
            instrument_id=intent.instrument_id or intent.symbol,
            symbol=intent.symbol,
            side=side,
            order_type=order_type,
            quantity=intent.quantity,
            price=intent.price,
            client_order_id=intent.client_order_id,
            reduce_only=intent.reduce_only,
        )
        try:
            order = await asyncio.wait_for(self._adapter.place_order(request), timeout=15.0)
            status = self.map_order_state(order.state)
            success = status not in {OrderLifecycleStatus.REJECTED, OrderLifecycleStatus.UNKNOWN}
            if status == OrderLifecycleStatus.PARTIALLY_FILLED:
                resolved = await self.resolve_order_state(intent.client_order_id, str(order.order_id or ""))
                if resolved:
                    status = resolved["status"]
                    success = status == OrderLifecycleStatus.FILLED
            return ExecutionResult(
                success=success,
                status=status,
                client_order_id=intent.client_order_id,
                exchange_order_id=str(order.order_id) if order.order_id else None,
                filled_quantity=float(order.filled_quantity or 0),
                average_price=float(order.average_fill_price) if order.average_fill_price else None,
                mode=ExecutionLayerMode.LIVE,
            )
        except asyncio.TimeoutError:
            recovered = await self.resolve_order_state(intent.client_order_id)
            if recovered:
                return ExecutionResult(
                    success=recovered["status"] == OrderLifecycleStatus.FILLED,
                    status=recovered["status"],
                    client_order_id=intent.client_order_id,
                    exchange_order_id=recovered.get("exchange_order_id"),
                    filled_quantity=float(recovered.get("filled_quantity") or 0),
                    average_price=float(recovered["average_price"]) if recovered.get("average_price") else None,
                    message="Recovered after timeout",
                    mode=ExecutionLayerMode.LIVE,
                )
            return ExecutionResult(
                success=False,
                status=OrderLifecycleStatus.UNKNOWN,
                client_order_id=intent.client_order_id,
                message="Exchange timeout — order state unknown",
                mode=ExecutionLayerMode.LIVE,
            )
        except Exception as exc:
            self.logger.warning("Delta order failed: %s", type(exc).__name__)
            return ExecutionResult(
                success=False,
                status=OrderLifecycleStatus.REJECTED,
                client_order_id=intent.client_order_id,
                message="Order rejected by exchange",
                mode=ExecutionLayerMode.LIVE,
            )

    async def resolve_order_state(
        self,
        client_order_id: str,
        exchange_order_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        try:
            order = await self._adapter.get_order_by_client_id(client_order_id)
            if not order:
                return None
            status = self.map_order_state(order.state)
            return {
                "status": status,
                "exchange_order_id": str(order.order_id) if order.order_id else exchange_order_id,
                "filled_quantity": float(order.filled_quantity or 0),
                "average_price": float(order.average_fill_price) if order.average_fill_price else None,
                "client_order_id": client_order_id,
            }
        except Exception:
            return None

    async def cancel_order(self, exchange_order_id: str, instrument_id: Optional[str] = None) -> bool:
        try:
            return await self._adapter.cancel_order(exchange_order_id, instrument_id or "")
        except Exception:
            return False

    async def get_order(self, client_order_id: str, exchange_order_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        resolved = await self.resolve_order_state(client_order_id, exchange_order_id)
        if resolved:
            resolved["status"] = resolved["status"].value if hasattr(resolved["status"], "value") else resolved["status"]
        return resolved

    async def get_open_orders(self) -> List[Dict[str, Any]]:
        try:
            orders = await self._adapter.get_open_orders()
            return [
                {
                    "order_id": o.order_id,
                    "client_order_id": o.client_order_id,
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "quantity": o.quantity,
                    "status": o.state.value,
                }
                for o in orders
            ]
        except Exception:
            return []

    async def get_positions(self) -> List[Dict[str, Any]]:
        try:
            positions = await self._adapter.get_positions()
            return [
                {
                    "symbol": p.symbol,
                    "instrument_id": p.instrument_id,
                    "size": p.size,
                    "entry_price": p.entry_price,
                }
                for p in positions
            ]
        except Exception:
            return []
