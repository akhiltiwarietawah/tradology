"""Abstract base exchange adapter interface for algorithmic order execution."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Callable, Awaitable
from datetime import date

from src.core.models.instrument import Instrument, OptionChain, InstrumentType
from src.core.models.order import Order, OrderRequest
from src.core.models.position import Position
from src.core.models.market_data import Ticker


class BaseExchangeAdapter(ABC):
    """Abstract interface for all exchange adapters in the trading engine."""

    @property
    @abstractmethod
    def exchange_name(self) -> str:
        """Name of the exchange (e.g. 'delta', 'deribit', 'binance')."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Status of exchange connection."""
        pass

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize connection, validate auth, and prepare resources."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close connections and release resources."""
        pass

    @abstractmethod
    async def get_spot_price(self, underlying: str) -> float:
        """Fetch current spot/index price for the underlying asset."""
        pass

    @abstractmethod
    async def get_instruments(
        self,
        underlying: Optional[str] = None,
        instrument_type: Optional[InstrumentType] = None,
    ) -> List[Instrument]:
        """Fetch list of tradable instruments matching filters."""
        pass

    @abstractmethod
    async def get_option_chain(self, underlying: str, expiry_date: date) -> OptionChain:
        """Fetch option chain for specified underlying and expiry date."""
        pass

    @abstractmethod
    async def get_tickers(self, symbols_or_ids: Optional[List[str]] = None) -> Dict[str, Ticker]:
        """Fetch market tickers for specified symbols or IDs."""
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """Fetch open positions from the exchange."""
        pass

    @abstractmethod
    async def get_open_orders(self, instrument_id: Optional[str] = None) -> List[Order]:
        """Fetch active open orders."""
        pass

    @abstractmethod
    async def get_order_by_client_id(self, client_order_id: str) -> Optional[Order]:
        """Query order state by client_order_id for idempotency & timeout recovery."""
        pass

    @abstractmethod
    async def get_recent_fills_for_product(
        self,
        instrument_id: str,
        side: Optional[str] = None,
        page_size: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent fills for a specific instrument, filtered by instrument_id only.
        Unrelated manual fills on other instruments are never returned.
        Used by reconciliation to capture actual exit fill price and fees on manual close.
        """
        pass

    @abstractmethod
    async def place_order(self, order_request: OrderRequest) -> Order:
        """Place an order with timeout safety."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str, instrument_id: str) -> bool:
        """Cancel an open order."""
        pass

    @abstractmethod
    async def cancel_all_orders(self, instrument_id: Optional[str] = None) -> bool:
        """Cancel all open orders."""
        pass

    @abstractmethod
    async def subscribe_market_data(self, symbols: List[str], callback: Callable[[Ticker], Awaitable[None]]) -> None:
        """Subscribe to real-time market data ticks."""
        pass

    @abstractmethod
    async def subscribe_private_events(
        self,
        order_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        position_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> None:
        """Subscribe to private account events."""
        pass

    @abstractmethod
    async def get_account_balances(self) -> Any:
        """Fetch real-time account wallet balances."""
        pass

    @abstractmethod
    async def create_bracket_order(
        self,
        instrument_id: str,
        stop_loss_price: float,
        take_profit_price: Optional[float] = None,
        stop_trigger_method: str = "mark_price",
        order_type: str = "market_order",
    ) -> Dict[str, Any]:
        """Create native exchange-side bracket Stop Loss and optional Take Profit order attached to open position."""
        pass

    @abstractmethod
    async def get_bracket_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Fetch bracket order details from exchange."""
        pass
