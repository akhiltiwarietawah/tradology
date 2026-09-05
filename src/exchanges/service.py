"""Exchange Service managing multi-exchange adapters and live streams."""

import logging
from typing import Dict, Optional, List
from src.core.interfaces.exchange import BaseExchangeAdapter


class ExchangeService:
    """Central registry and coordinator for exchange adapters."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("exchange_service")
        self.exchanges: Dict[str, BaseExchangeAdapter] = {}

    def register_adapter(self, adapter: BaseExchangeAdapter):
        """Register an exchange adapter instance."""
        name = adapter.exchange_name.lower()
        self.exchanges[name] = adapter
        self.logger.info(f"Registered exchange adapter: {name}")

    def get_adapter(self, exchange_name: str = "delta_india") -> BaseExchangeAdapter:
        """Get an active exchange adapter by name."""
        name = exchange_name.lower()
        if name not in self.exchanges:
            raise KeyError(f"Exchange adapter '{name}' not found. Registered: {list(self.exchanges.keys())}")
        return self.exchanges[name]

    def has_adapter(self, exchange_name: str) -> bool:
        return exchange_name.lower() in self.exchanges

    async def initialize_all(self):
        """Initialize all registered exchange adapters."""
        for name, adapter in self.exchanges.items():
            self.logger.info(f"Initializing adapter: {name}")
            await adapter.initialize()

    async def close_all(self):
        """Close all registered exchange adapters."""
        for name, adapter in self.exchanges.items():
            self.logger.info(f"Closing adapter: {name}")
            await adapter.close()
