"""Read-only exchange account sync adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.platform.sync.models import AccountSyncSnapshot, ConnectionTestResult


class AccountSyncAdapter(ABC):
    """Fetch account state from an exchange without placing orders."""

    @property
    @abstractmethod
    def exchange_code(self) -> str:
        pass

    @abstractmethod
    async def test_connection(self) -> ConnectionTestResult:
        pass

    @abstractmethod
    async def fetch_snapshot(self) -> AccountSyncSnapshot:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass
