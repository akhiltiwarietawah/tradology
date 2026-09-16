"""Normalized execution models and order lifecycle states."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class OrderLifecycleStatus(str, Enum):
    SIGNAL = "SIGNAL"
    ORDER_INTENT = "ORDER_INTENT"
    RISK_CHECK = "RISK_CHECK"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    WOULD_EXECUTE = "WOULD_EXECUTE"  # LIVE_DRY_RUN


class ExecutionLayerMode(str, Enum):
    PAPER = "PAPER"
    LIVE_DRY_RUN = "LIVE_DRY_RUN"
    LIVE = "LIVE"


class StrangleGroupStatus(str, Enum):
    PENDING = "PENDING"
    PRECHECKED = "PRECHECKED"
    LEG_1_SUBMITTED = "LEG_1_SUBMITTED"
    LEG_1_FILLED = "LEG_1_FILLED"
    LEG_2_SUBMITTED = "LEG_2_SUBMITTED"
    LEG_2_FILLED = "LEG_2_FILLED"
    COMPLETE = "COMPLETE"
    LEG_1_FAILED = "LEG_1_FAILED"
    LEG_2_FAILED = "LEG_2_FAILED"
    PARTIAL = "PARTIAL"
    UNWINDING = "UNWINDING"
    UNWOUND = "UNWOUND"
    UNWIND_FAILED = "UNWIND_FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass
class StrangleExecutionResult:
    success: bool
    status: StrangleGroupStatus
    message: str = ""
    ce_result: Optional["ExecutionResult"] = None
    pe_result: Optional["ExecutionResult"] = None
    group_id: Optional[str] = None


@dataclass
class OrderIntent:
    signal_key: str
    client_order_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str = "market"
    price: Optional[float] = None
    instrument_id: Optional[str] = None
    reduce_only: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    success: bool
    status: OrderLifecycleStatus
    client_order_id: str
    exchange_order_id: Optional[str] = None
    filled_quantity: float = 0.0
    average_price: Optional[float] = None
    message: str = ""
    mode: ExecutionLayerMode = ExecutionLayerMode.PAPER
    order_intent_id: Optional[Any] = None
    fee: float = 0.0
    exchange_fill_id: Optional[str] = None


@dataclass
class NormalizedMarketEvent:
    symbol: str
    mark_price: float
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "unknown"
    stale: bool = False


@dataclass
class ReconciliationReport:
    matched: bool
    status: str  # MATCH, MISMATCH, UNKNOWN
    message: str = ""
    local_count: int = 0
    exchange_count: int = 0
    details: Dict[str, Any] = field(default_factory=dict)
