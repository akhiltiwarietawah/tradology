"""Factory for read-only account sync adapters."""

from __future__ import annotations

import logging
from typing import Any, Dict

from src.platform.sync.adapter_base import AccountSyncAdapter
from src.platform.sync.adapters.binance import BinanceAccountSyncAdapter
from src.platform.sync.adapters.bybit import BybitAccountSyncAdapter
from src.platform.sync.adapters.delta import DeltaAccountSyncAdapter
from src.platform.sync.adapters.okx import OkxAccountSyncAdapter


def create_account_sync_adapter(
    exchange: str,
    credentials: Dict[str, Any],
    *,
    is_testnet: bool = False,
    logger: logging.Logger | None = None,
) -> AccountSyncAdapter:
    code = exchange.lower()
    api_key = credentials.get("api_key") or ""
    api_secret = credentials.get("api_secret") or ""
    passphrase = credentials.get("passphrase")

    if code == "delta_india":
        return DeltaAccountSyncAdapter(
            api_key=api_key,
            api_secret=api_secret,
            is_testnet=is_testnet,
            logger=logger,
        )
    if code == "binance":
        return BinanceAccountSyncAdapter(
            api_key=api_key,
            api_secret=api_secret,
            is_testnet=is_testnet,
            logger=logger,
        )
    if code == "bybit":
        return BybitAccountSyncAdapter(
            api_key=api_key,
            api_secret=api_secret,
            is_testnet=is_testnet,
            logger=logger,
        )
    if code == "okx":
        if not passphrase:
            raise ValueError("OKX requires API passphrase")
        return OkxAccountSyncAdapter(
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            is_testnet=is_testnet,
            logger=logger,
        )
    raise ValueError(f"Unsupported exchange for sync: {exchange}")
