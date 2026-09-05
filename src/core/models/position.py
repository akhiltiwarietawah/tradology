"""Generic position tracking models."""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class Position:
    """Generic representation of an open or closed position."""
    instrument_id: str
    symbol: str
    size: float  # Positive for long, negative for short, 0 for flat
    entry_price: float = 0.0
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    liquidation_price: Optional[float] = None
    strategy_id: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def side(self) -> PositionSide:
        if self.size > 1e-6:
            return PositionSide.LONG
        elif self.size < -1e-6:
            return PositionSide.SHORT
        return PositionSide.FLAT

    @property
    def is_open(self) -> bool:
        return self.side != PositionSide.FLAT

    @property
    def is_short(self) -> bool:
        return self.side == PositionSide.SHORT

    @property
    def is_long(self) -> bool:
        return self.side == PositionSide.LONG
