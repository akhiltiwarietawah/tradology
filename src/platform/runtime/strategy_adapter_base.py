"""Strategy runtime adapter interface — bridges existing strategy logic to platform runtime."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.platform.execution.models import NormalizedMarketEvent, OrderIntent


class StrategyRuntimeAdapter(ABC):
    """Integrates an existing strategy with isolated platform runtime state."""

    @abstractmethod
    async def initialize(self) -> None:
        """Load config, restore state, prepare exchange connections."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Begin strategy loop after reconciliation passes."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop safely without orphan orders."""
        ...

    @abstractmethod
    async def on_timer(self, now: datetime) -> None:
        """Periodic strategy tick (entry/exit windows)."""
        ...

    @abstractmethod
    async def on_market_event(self, event: NormalizedMarketEvent) -> None:
        """Handle normalized tick/candle."""
        ...

    @abstractmethod
    def get_expected_positions(self) -> List[Dict[str, Any]]:
        """Return strategy-expected positions for reconciliation."""
        ...

    @abstractmethod
    def export_state(self) -> Dict[str, Any]:
        """Serializable runtime state (no secrets)."""
        ...

    @abstractmethod
    async def restore_state(self, state: Dict[str, Any]) -> None:
        ...

    @property
    @abstractmethod
    def is_market_data_fresh(self) -> bool:
        ...
