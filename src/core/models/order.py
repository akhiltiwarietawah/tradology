"""Generic order and execution fill models."""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market_order"
    LIMIT = "limit_order"


class OrderState(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(str, Enum):
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


@dataclass
class OrderRequest:
    """Request model for submitting an order."""
    instrument_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    stop_order_type: Optional[str] = None
    client_order_id: Optional[str] = None
    reduce_only: bool = False
    time_in_force: TimeInForce = TimeInForce.GTC
    strategy_id: Optional[str] = None
    leg_id: Optional[str] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Order:
    """Generic representation of an order across exchanges."""
    order_id: Optional[str]
    client_order_id: Optional[str]
    instrument_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    state: OrderState = OrderState.OPEN
    filled_quantity: float = 0.0
    unfilled_quantity: float = 0.0
    average_fill_price: Optional[float] = None
    reduce_only: bool = False
    time_in_force: TimeInForce = TimeInForce.GTC
    strategy_id: Optional[str] = None
    leg_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.state in (OrderState.OPEN, OrderState.PARTIALLY_FILLED, OrderState.PENDING)

    @property
    def is_filled(self) -> bool:
        return self.state == OrderState.FILLED

    @property
    def is_closed(self) -> bool:
        return self.state in (OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.EXPIRED)


@dataclass
class Fill:
    """Generic execution fill model."""
    fill_id: str
    order_id: str
    client_order_id: Optional[str]
    instrument_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    fee: float = 0.0
    fee_asset: str = "USDT"
    timestamp: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
