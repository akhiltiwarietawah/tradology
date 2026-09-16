"""Exchange-neutral execution adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.platform.execution.models import ExecutionResult, OrderIntent


class ExecutionAdapter(ABC):
    """Normalized execution interface — only Delta implements live submission in Phase 4."""

    supports_live_submission: bool = False

    @abstractmethod
    async def initialize(self) -> bool:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...

    @abstractmethod
    async def place_order(self, intent: OrderIntent) -> ExecutionResult:
        ...

    @abstractmethod
    async def cancel_order(self, exchange_order_id: str, instrument_id: Optional[str] = None) -> bool:
        ...

    @abstractmethod
    async def get_order(self, client_order_id: str, exchange_order_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    async def get_open_orders(self) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    async def get_positions(self) -> List[Dict[str, Any]]:
        ...
