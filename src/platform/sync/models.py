"""Normalized models for read-only account synchronization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class NormalizedBalance:
    asset: str
    total_balance: float
    available_balance: float
    equity: float
    used_margin: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    currency: str = "USD"


@dataclass
class NormalizedPosition:
    symbol: str
    side: str
    quantity: float
    entry_price: Optional[float] = None
    mark_price: Optional[float] = None
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    leverage: Optional[float] = None
    liquidation_price: Optional[float] = None


@dataclass
class NormalizedOrder:
    exchange_order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: Optional[float] = None
    status: str = "open"


@dataclass
class AccountSyncSnapshot:
    equity: float
    available_balance: float
    unrealized_pnl: float
    realized_pnl: float
    currency: str
    balances: List[NormalizedBalance] = field(default_factory=list)
    positions: List[NormalizedPosition] = field(default_factory=list)
    orders: List[NormalizedOrder] = field(default_factory=list)
    synced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ConnectionTestResult:
    success: bool
    message: str
    error_code: Optional[str] = None
