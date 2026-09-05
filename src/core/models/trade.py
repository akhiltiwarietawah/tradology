"""Generic and Strangle strategy trade lifecycle models."""

from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from datetime import datetime
import pytz

from src.config.constants import IST_TIMEZONE
from src.core.models.instrument import OptionType


class LegStatus(str, Enum):
    PENDING_ENTRY = "PENDING_ENTRY"
    OPEN = "OPEN"
    STOPPED_OUT = "STOPPED_OUT"
    EXPIRED = "EXPIRED"
    FORCE_CLOSED = "FORCE_CLOSED"
    MANUALLY_CLOSED = "MANUALLY_CLOSED"
    UNWOUND_ON_FAILURE = "UNWOUND_ON_FAILURE"
    CANCELLED = "CANCELLED"


class StrategyState(str, Enum):
    IDLE = "IDLE"
    PENDING_ENTRY = "PENDING_ENTRY"
    ACTIVE = "ACTIVE"
    PENDING_EXIT = "PENDING_EXIT"
    COMPLETED = "COMPLETED"
    FAILED_ENTRY = "FAILED_ENTRY"
    SAFE_HALT = "SAFE_HALT"


@dataclass
class StrategyLeg:
    """Represents one leg (e.g. CE or PE) of a strategy position."""
    leg_id: str
    option_type: OptionType
    instrument_id: str
    symbol: str
    strike: float
    expiry_date: str
    quantity: float
    intended_premium: float
    contract_value: float = 0.001

    # Entry details
    entry_timestamp: Optional[str] = None
    entry_order_id: Optional[str] = None
    entry_client_order_id: Optional[str] = None
    entry_fill_price: Optional[float] = None

    # Stop Loss & Take Profit details
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    sl_triggered: bool = False
    sl_timestamp: Optional[str] = None
    sl_order_id: Optional[str] = None
    sl_client_order_id: Optional[str] = None
    sl_fill_price: Optional[float] = None
    bracket_order_id: Optional[str] = None
    exchange_sl_active: bool = False

    # Exit details
    exit_timestamp: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "STOP_LOSS", "EOD_EXIT", "MANUAL_CLOSE", "EMERGENCY_UNWIND", "MAX_LOSS"
    fees: float = 0.0
    realized_pnl: float = 0.0
    status: LegStatus = LegStatus.PENDING_ENTRY

    @property
    def is_open(self) -> bool:
        return self.status == LegStatus.OPEN

    def calculate_sl_price(self, sl_pct: float = 1.0) -> float:
        """Calculate Stop Loss price: for short position, SL is entry + (entry * sl_pct)."""
        if self.entry_fill_price is not None and self.entry_fill_price > 0:
            self.sl_price = round(self.entry_fill_price * (1.0 + sl_pct), 2)
            return self.sl_price
        return 0.0

    def compute_unrealized_pnl(self, current_mark_price: float) -> float:
        """Compute unrealized P&L in USD for short position: (entry - current) * quantity * contract_value."""
        if not self.is_open or self.entry_fill_price is None:
            return 0.0
        return (self.entry_fill_price - current_mark_price) * self.quantity * self.contract_value

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["option_type"] = self.option_type.value if isinstance(self.option_type, OptionType) else self.option_type
        d["status"] = self.status.value if isinstance(self.status, LegStatus) else self.status
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyLeg":
        option_type = OptionType(data["option_type"]) if isinstance(data.get("option_type"), str) else data.get("option_type")
        status = LegStatus(data["status"]) if isinstance(data.get("status"), str) else data.get("status", LegStatus.PENDING_ENTRY)

        return cls(
            leg_id=data["leg_id"],
            option_type=option_type,
            instrument_id=str(data["instrument_id"]),
            symbol=data["symbol"],
            strike=float(data["strike"]),
            expiry_date=data["expiry_date"],
            quantity=float(data["quantity"]),
            intended_premium=float(data["intended_premium"]),
            contract_value=float(data.get("contract_value", 0.001) or 0.001),
            entry_timestamp=data.get("entry_timestamp"),
            entry_order_id=str(data["entry_order_id"]) if data.get("entry_order_id") is not None else None,
            entry_client_order_id=data.get("entry_client_order_id"),
            entry_fill_price=float(data["entry_fill_price"]) if data.get("entry_fill_price") is not None else None,
            sl_price=float(data["sl_price"]) if data.get("sl_price") is not None else None,
            tp_price=float(data["tp_price"]) if data.get("tp_price") is not None else None,
            sl_triggered=bool(data.get("sl_triggered", False)),
            sl_timestamp=data.get("sl_timestamp"),
            sl_order_id=str(data["sl_order_id"]) if data.get("sl_order_id") is not None else None,
            sl_client_order_id=data.get("sl_client_order_id"),
            sl_fill_price=float(data["sl_fill_price"]) if data.get("sl_fill_price") is not None else None,
            bracket_order_id=str(data["bracket_order_id"]) if data.get("bracket_order_id") is not None else None,
            exchange_sl_active=bool(data.get("exchange_sl_active", False)),
            exit_timestamp=data.get("exit_timestamp"),
            exit_price=float(data["exit_price"]) if data.get("exit_price") is not None else None,
            exit_reason=data.get("exit_reason"),
            fees=float(data.get("fees", 0.0)),
            realized_pnl=float(data.get("realized_pnl", 0.0)),
            status=status,
        )


@dataclass
class StrategyTrade:
    """Represents a strategy trade lifecycle for a trading day."""
    strategy_trade_id: str
    strategy_name: str
    trade_date: str  # YYYY-MM-DD
    underlying_spot_at_entry: float = 0.0
    ce_leg: Optional[StrategyLeg] = None
    pe_leg: Optional[StrategyLeg] = None
    state: StrategyState = StrategyState.IDLE
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(IST_TIMEZONE).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(IST_TIMEZONE).isoformat())

    @property
    def is_active(self) -> bool:
        return self.state == StrategyState.ACTIVE

    @property
    def has_any_open_leg(self) -> bool:
        ce_open = self.ce_leg is not None and self.ce_leg.is_open
        pe_open = self.pe_leg is not None and self.pe_leg.is_open
        return ce_open or pe_open

    @property
    def has_any_fill_or_order(self) -> bool:
        """Returns True if any leg had an order accepted, fill recorded, position opened, or emergency unwind executed."""
        if self.ce_leg is not None:
            if (
                self.ce_leg.entry_order_id is not None
                or self.ce_leg.entry_fill_price is not None
                or self.ce_leg.status in (LegStatus.OPEN, LegStatus.UNWOUND_ON_FAILURE, LegStatus.STOPPED_OUT, LegStatus.FORCE_CLOSED, LegStatus.MANUALLY_CLOSED)
            ):
                return True
        if self.pe_leg is not None:
            if (
                self.pe_leg.entry_order_id is not None
                or self.pe_leg.entry_fill_price is not None
                or self.pe_leg.status in (LegStatus.OPEN, LegStatus.UNWOUND_ON_FAILURE, LegStatus.STOPPED_OUT, LegStatus.FORCE_CLOSED, LegStatus.MANUALLY_CLOSED)
            ):
                return True
        return False

    @property
    def total_entry_premium(self) -> float:
        """Total initial premium collected in USD across all legs."""
        total = 0.0
        if self.ce_leg and self.ce_leg.entry_fill_price is not None and self.ce_leg.entry_fill_price > 0:
            total += self.ce_leg.entry_fill_price * self.ce_leg.quantity * self.ce_leg.contract_value
        if self.pe_leg and self.pe_leg.entry_fill_price is not None and self.pe_leg.entry_fill_price > 0:
            total += self.pe_leg.entry_fill_price * self.pe_leg.quantity * self.pe_leg.contract_value
        return round(total, 4)

    def get_open_legs(self) -> List[StrategyLeg]:
        legs = []
        if self.ce_leg and self.ce_leg.is_open:
            legs.append(self.ce_leg)
        if self.pe_leg and self.pe_leg.is_open:
            legs.append(self.pe_leg)
        return legs

    def update_pnl(self, ce_price: Optional[float] = None, pe_price: Optional[float] = None):
        """Update total realized and unrealized P&L."""
        realized = 0.0
        unrealized = 0.0

        if self.ce_leg:
            realized += self.ce_leg.realized_pnl - self.ce_leg.fees
            if self.ce_leg.is_open and ce_price is not None:
                unrealized += self.ce_leg.compute_unrealized_pnl(ce_price)

        if self.pe_leg:
            realized += self.pe_leg.realized_pnl - self.pe_leg.fees
            if self.pe_leg.is_open and pe_price is not None:
                unrealized += self.pe_leg.compute_unrealized_pnl(pe_price)

        self.total_realized_pnl = round(realized, 4)
        self.total_unrealized_pnl = round(unrealized, 4)
        self.updated_at = datetime.now(IST_TIMEZONE).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_trade_id": self.strategy_trade_id,
            "strategy_name": self.strategy_name,
            "trade_date": self.trade_date,
            "underlying_spot_at_entry": self.underlying_spot_at_entry,
            "ce_leg": self.ce_leg.to_dict() if self.ce_leg else None,
            "pe_leg": self.pe_leg.to_dict() if self.pe_leg else None,
            "state": self.state.value if isinstance(self.state, StrategyState) else self.state,
            "total_realized_pnl": self.total_realized_pnl,
            "total_unrealized_pnl": self.total_unrealized_pnl,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyTrade":
        state = StrategyState(data["state"]) if isinstance(data.get("state"), str) else data.get("state", StrategyState.IDLE)
        ce_leg = StrategyLeg.from_dict(data["ce_leg"]) if data.get("ce_leg") else None
        pe_leg = StrategyLeg.from_dict(data["pe_leg"]) if data.get("pe_leg") else None

        return cls(
            strategy_trade_id=data["strategy_trade_id"],
            strategy_name=data.get("strategy_name", "short_strangle"),
            trade_date=data["trade_date"],
            underlying_spot_at_entry=float(data.get("underlying_spot_at_entry", 0.0)),
            ce_leg=ce_leg,
            pe_leg=pe_leg,
            state=state,
            total_realized_pnl=float(data.get("total_realized_pnl", 0.0)),
            total_unrealized_pnl=float(data.get("total_unrealized_pnl", 0.0)),
            created_at=data.get("created_at", datetime.now(IST_TIMEZONE).isoformat()),
            updated_at=data.get("updated_at", datetime.now(IST_TIMEZONE).isoformat()),
        )
