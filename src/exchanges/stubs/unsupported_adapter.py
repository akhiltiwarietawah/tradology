"""Placeholder adapter for exchanges pending full integration."""

from __future__ import annotations

from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.core.interfaces.exchange import BaseExchangeAdapter
from src.core.models.instrument import Instrument, InstrumentType, OptionChain
from src.core.models.market_data import Ticker
from src.core.models.order import Order, OrderRequest
from src.core.models.position import Position


class UnsupportedExchangeAdapter(BaseExchangeAdapter):
    """Returns structured not-implemented errors until exchange integration ships."""

    def __init__(self, exchange_code: str, display_name: str):
        self._exchange_code = exchange_code
        self._display_name = display_name
        self._connected = False

    @property
    def exchange_name(self) -> str:
        return self._exchange_code

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def initialize(self) -> bool:
        self._connected = False
        return False

    async def close(self) -> None:
        self._connected = False

    def _not_ready(self) -> RuntimeError:
        return RuntimeError(
            f"{self._display_name} integration is not yet available. Account saved securely; trading sync coming soon."
        )

    async def get_spot_price(self, underlying: str) -> float:
        raise self._not_ready()

    async def get_instruments(
        self,
        underlying: Optional[str] = None,
        instrument_type: Optional[InstrumentType] = None,
    ) -> List[Instrument]:
        raise self._not_ready()

    async def get_option_chain(self, underlying: str, expiry_date: date) -> OptionChain:
        raise self._not_ready()

    async def get_tickers(self, symbols_or_ids: Optional[List[str]] = None) -> Dict[str, Ticker]:
        raise self._not_ready()

    async def get_positions(self) -> List[Position]:
        return []

    async def get_open_orders(self, instrument_id: Optional[str] = None) -> List[Order]:
        return []

    async def get_order_by_client_id(self, client_order_id: str) -> Optional[Order]:
        return None

    async def get_recent_fills_for_product(
        self,
        instrument_id: str,
        side: Optional[str] = None,
        page_size: int = 10,
        start_time_us: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return []

    async def place_order(self, order_request: OrderRequest) -> Order:
        raise self._not_ready()

    async def cancel_order(self, order_id: str, instrument_id: str) -> bool:
        raise self._not_ready()

    async def cancel_all_orders(self, instrument_id: Optional[str] = None) -> bool:
        raise self._not_ready()

    async def subscribe_market_data(
        self, symbols: List[str], callback: Callable[[Ticker], Awaitable[None]]
    ) -> None:
        raise self._not_ready()

    async def subscribe_private_events(
        self,
        order_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        position_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> None:
        raise self._not_ready()

    async def get_account_balances(self) -> Any:
        raise self._not_ready()

    async def create_bracket_order(
        self,
        instrument_id: str,
        stop_loss_price: float,
        take_profit_price: Optional[float] = None,
        stop_trigger_method: str = "mark_price",
        order_type: str = "market_order",
    ) -> Dict[str, Any]:
        raise self._not_ready()

    async def get_bracket_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        return None

    async def test_connection(self) -> Dict[str, Any]:
        return {
            "connected": False,
            "exchange": self._exchange_code,
            "message": f"{self._display_name} adapter pending implementation",
        }
