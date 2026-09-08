"""Market data ticker and order book models."""

from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Any


@dataclass
class Ticker:
    """Market price snapshot for an instrument."""
    symbol: str
    instrument_id: str
    mark_price: float = 0.0
    spot_price: float = 0.0
    best_bid: float = 0.0
    best_ask: float = 0.0
    last_price: float = 0.0
    volume_24h: float = 0.0
    timestamp: Optional[float] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def mid_price(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2.0
        if self.mark_price > 0:
            return self.mark_price
        return self.last_price

    @property
    def sell_premium(self) -> float:
        """Price a short actually hits on a market sell — the bid. 0 if unknown."""
        return self.best_bid if self.best_bid > 0 else 0.0


@dataclass
class OrderBook:
    """Level 2 order book snapshot."""
    symbol: str
    instrument_id: str
    bids: List[Tuple[float, float]] = field(default_factory=list)  # [(price, size), ...]
    asks: List[Tuple[float, float]] = field(default_factory=list)  # [(price, size), ...]
    timestamp: Optional[float] = None
