"""Generic instrument and option chain data models."""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime, date


class InstrumentType(str, Enum):
    SPOT = "spot"
    OPTION = "option"
    PERPETUAL = "perpetual"
    FUTURES = "futures"


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


@dataclass
class Instrument:
    """Generic representation of a tradable instrument/contract across exchanges."""
    exchange: str
    instrument_id: str  # e.g., '12345' (Delta product_id)
    symbol: str         # e.g., 'C-BTC-95000-010926' or 'BTC-01SEP26-95000-C'
    underlying: str     # e.g., 'BTC'
    instrument_type: InstrumentType
    option_type: Optional[OptionType] = None
    strike_price: Optional[float] = None
    expiry: Optional[datetime] = None
    contract_value: float = 0.001  # Value of 1 contract in underlying asset units (e.g., 0.001 BTC)
    tick_size: float = 0.1
    min_order_size: float = 1.0    # In contracts or lots
    quoting_asset: str = "USD"
    settling_asset: str = "USDT"
    is_active: bool = True
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_option(self) -> bool:
        return self.instrument_type == InstrumentType.OPTION

    @property
    def is_call(self) -> bool:
        return self.option_type == OptionType.CALL

    @property
    def is_put(self) -> bool:
        return self.option_type == OptionType.PUT


@dataclass
class OptionChain:
    """Option chain containing calls and puts for a given underlying and expiry."""
    exchange: str
    underlying: str
    expiry_date: date
    calls: List[Instrument] = field(default_factory=list)
    puts: List[Instrument] = field(default_factory=list)

    def get_all_instruments(self) -> List[Instrument]:
        return self.calls + self.puts
