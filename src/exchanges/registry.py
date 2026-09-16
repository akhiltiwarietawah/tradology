"""Exchange registry and adapter factory for multi-exchange platform support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Type

from src.core.interfaces.exchange import BaseExchangeAdapter
from src.exchanges.stubs.unsupported_adapter import UnsupportedExchangeAdapter


@dataclass(frozen=True)
class ExchangeDefinition:
    code: str
    name: str
    status: str  # live | coming_soon | beta
    supports_spot: bool = True
    supports_perpetual: bool = True
    supports_options: bool = False
    supports_execution: bool = False
    supports_account_sync: bool = False
    requires_passphrase: bool = False
    credential_fields: tuple[str, ...] = ("api_key", "api_secret")


EXCHANGE_REGISTRY: Dict[str, ExchangeDefinition] = {
    "delta_india": ExchangeDefinition(
        code="delta_india",
        name="Delta Exchange India",
        status="live",
        supports_options=True,
        supports_perpetual=True,
        supports_execution=True,
        supports_account_sync=True,
    ),
    "binance": ExchangeDefinition(
        code="binance",
        name="Binance",
        status="beta",
        supports_spot=True,
        supports_perpetual=True,
        supports_account_sync=True,
    ),
    "bybit": ExchangeDefinition(
        code="bybit",
        name="Bybit",
        status="beta",
        supports_spot=True,
        supports_perpetual=True,
        supports_account_sync=True,
    ),
    "okx": ExchangeDefinition(
        code="okx",
        name="OKX",
        status="beta",
        supports_spot=True,
        supports_perpetual=True,
        supports_account_sync=True,
        requires_passphrase=True,
        credential_fields=("api_key", "api_secret", "passphrase"),
    ),
}


def list_supported_exchanges() -> List[ExchangeDefinition]:
    return list(EXCHANGE_REGISTRY.values())


def get_exchange_definition(code: str) -> Optional[ExchangeDefinition]:
    return EXCHANGE_REGISTRY.get(code.lower())


def create_exchange_adapter(exchange_code: str, **kwargs) -> BaseExchangeAdapter:
    """Factory for exchange adapters. Delta uses the live engine adapter elsewhere."""
    definition = get_exchange_definition(exchange_code)
    if not definition:
        raise ValueError(f"Unknown exchange: {exchange_code}")

    if exchange_code == "delta_india":
        from src.exchanges.delta.adapter import DeltaExchangeAdapter

        return DeltaExchangeAdapter(**kwargs)

    return UnsupportedExchangeAdapter(exchange_code=exchange_code, display_name=definition.name)
