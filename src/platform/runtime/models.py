"""Runtime domain models and status enums."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class RuntimeStatus(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class ExecutionMode(str, Enum):
    PAPER = "PAPER"
    LIVE_DRY_RUN = "LIVE_DRY_RUN"
    LIVE = "LIVE"


@dataclass
class RuntimeContext:
    user_id: uuid.UUID
    subscription_id: uuid.UUID
    strategy_account_id: uuid.UUID
    strategy_code: str
    strategy_name: str
    exchange: str
    exchange_account_id: uuid.UUID
    exchange_account_label: str
    execution_mode: ExecutionMode
    trading_enabled: bool
    subscription_status: str
    exchange_health_status: str
    exchange_connection_status: str
    is_testnet: bool
    exchange_trading_enabled: bool = True
    risk_settings: Dict[str, Any] = field(default_factory=dict)
    risk_overrides: Dict[str, Any] = field(default_factory=dict)
    runtime_id: Optional[uuid.UUID] = None


@dataclass
class SafetyCheckResult:
    approved: bool
    reason: str = ""
    code: str = "ok"


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str = ""
    code: str = "ok"


@dataclass
class RuntimeSnapshot:
    strategy_account_id: str
    runtime_id: Optional[str]
    status: str
    execution_mode: str
    trading_enabled: bool
    strategy_code: str
    exchange: str
    exchange_account_id: str
    exchange_account_label: str
    last_heartbeat_at: Optional[str] = None
    last_error: Optional[str] = None
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
