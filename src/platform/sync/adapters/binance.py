"""Binance read-only account sync (spot wallet + USDT-M futures positions)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from src.platform.sync.adapter_base import AccountSyncAdapter
from src.platform.sync.http_utils import ExchangeHttpError, binance_sign_query, http_get_json
from src.platform.sync.models import (
    AccountSyncSnapshot,
    ConnectionTestResult,
    NormalizedBalance,
    NormalizedOrder,
    NormalizedPosition,
)


class BinanceAccountSyncAdapter(AccountSyncAdapter):
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        is_testnet: bool = False,
        logger: logging.Logger | None = None,
    ):
        self._api_key = api_key
        self._api_secret = api_secret
        self._is_testnet = is_testnet
        self._logger = logger or logging.getLogger("binance_account_sync")
        if is_testnet:
            self._spot_base = "https://testnet.binance.vision"
            self._futures_base = "https://testnet.binancefuture.com"
        else:
            self._spot_base = "https://api.binance.com"
            self._futures_base = "https://fapi.binance.com"

    @property
    def exchange_code(self) -> str:
        return "binance"

    async def _signed_get(self, base: str, path: str, params: Dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        params["timestamp"] = int(datetime.now(timezone.utc).timestamp() * 1000)
        query = binance_sign_query(self._api_secret, params)
        url = f"{base}{path}?{query}"
        headers = {"X-MBX-APIKEY": self._api_key}
        return await http_get_json(url, headers=headers)

    async def test_connection(self) -> ConnectionTestResult:
        try:
            await self._signed_get(self._spot_base, "/api/v3/account")
            return ConnectionTestResult(success=True, message="Binance credentials verified")
        except ExchangeHttpError as exc:
            if exc.status_code in (401, 403):
                return ConnectionTestResult(success=False, message="Invalid Binance credentials", error_code="invalid_credentials")
            if exc.status_code == 429:
                return ConnectionTestResult(success=False, message="Binance rate limited", error_code="rate_limited")
            return ConnectionTestResult(success=False, message="Binance connection failed", error_code=exc.error_code)
        except Exception:
            return ConnectionTestResult(success=False, message="Binance exchange unavailable", error_code="unavailable")

    async def fetch_snapshot(self) -> AccountSyncSnapshot:
        spot = await self._signed_get(self._spot_base, "/api/v3/account")
        balances: List[NormalizedBalance] = []
        equity = 0.0
        available = 0.0
        for item in spot.get("balances", []):
            free = float(item.get("free") or 0)
            locked = float(item.get("locked") or 0)
            total = free + locked
            if total <= 0:
                continue
            asset = str(item.get("asset") or "")
            balances.append(
                NormalizedBalance(
                    asset=asset,
                    total_balance=total,
                    available_balance=free,
                    equity=total,
                    currency=asset,
                )
            )
            if asset in ("USDT", "USD", "BUSD"):
                equity += total
                available += free

        positions: List[NormalizedPosition] = []
        unrealized_total = 0.0
        try:
            fpos = await self._signed_get(self._futures_base, "/fapi/v2/positionRisk")
            for item in fpos:
                amt = float(item.get("positionAmt") or 0)
                if abs(amt) < 1e-12:
                    continue
                upnl = float(item.get("unRealizedProfit") or 0)
                unrealized_total += upnl
                positions.append(
                    NormalizedPosition(
                        symbol=str(item.get("symbol") or ""),
                        side="long" if amt > 0 else "short",
                        quantity=abs(amt),
                        entry_price=float(item.get("entryPrice") or 0) or None,
                        mark_price=float(item.get("markPrice") or 0) or None,
                        unrealized_pnl=upnl,
                        leverage=float(item.get("leverage") or 0) or None,
                        liquidation_price=float(item.get("liquidationPrice") or 0) or None,
                    )
                )
            fbalances = await self._signed_get(self._futures_base, "/fapi/v2/balance")
            for item in fbalances:
                if str(item.get("asset")) == "USDT":
                    equity += float(item.get("balance") or 0)
                    available += float(item.get("availableBalance") or 0)
        except ExchangeHttpError:
            self._logger.info("Binance futures endpoints unavailable for this key — spot only")

        orders: List[NormalizedOrder] = []
        try:
            open_orders = await self._signed_get(self._futures_base, "/fapi/v1/openOrders")
            for item in open_orders:
                orders.append(
                    NormalizedOrder(
                        exchange_order_id=str(item.get("orderId") or ""),
                        symbol=str(item.get("symbol") or ""),
                        side=str(item.get("side") or "").lower(),
                        order_type=str(item.get("type") or ""),
                        quantity=float(item.get("origQty") or 0),
                        price=float(item.get("price") or 0) or None,
                        status=str(item.get("status") or "NEW"),
                    )
                )
        except ExchangeHttpError:
            pass

        return AccountSyncSnapshot(
            equity=equity,
            available_balance=available,
            unrealized_pnl=unrealized_total,
            realized_pnl=0.0,
            currency="USDT",
            balances=balances,
            positions=positions,
            orders=orders,
            synced_at=datetime.now(timezone.utc),
        )

    async def close(self) -> None:
        return None
