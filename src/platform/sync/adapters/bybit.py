"""Bybit v5 read-only account sync."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from src.platform.sync.adapter_base import AccountSyncAdapter
from src.platform.sync.http_utils import ExchangeHttpError, bybit_sign, http_get_json
from src.platform.sync.models import (
    AccountSyncSnapshot,
    ConnectionTestResult,
    NormalizedBalance,
    NormalizedOrder,
    NormalizedPosition,
)


class BybitAccountSyncAdapter(AccountSyncAdapter):
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
        self._base = "https://api-testnet.bybit.com" if is_testnet else "https://api.bybit.com"
        self._logger = logger or logging.getLogger("bybit_account_sync")

    @property
    def exchange_code(self) -> str:
        return "bybit"

    async def _signed_get(self, path: str, params: Dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        recv_window = "5000"
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sign = bybit_sign(self._api_secret, timestamp, self._api_key, recv_window, query)
        headers = {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-SIGN": sign,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window,
        }
        url = f"{self._base}{path}"
        data = await http_get_json(url, headers=headers, params=params)
        if int(data.get("retCode", -1)) != 0:
            raise ExchangeHttpError(
                str(data.get("retMsg") or "Bybit API error"),
                error_code=str(data.get("retCode")),
            )
        return data.get("result") or {}

    async def test_connection(self) -> ConnectionTestResult:
        try:
            await self._signed_get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
            return ConnectionTestResult(success=True, message="Bybit credentials verified")
        except ExchangeHttpError as exc:
            if exc.error_code in ("10003", "10004", "33004"):
                return ConnectionTestResult(success=False, message="Invalid Bybit credentials", error_code="invalid_credentials")
            if exc.status_code == 429:
                return ConnectionTestResult(success=False, message="Bybit rate limited", error_code="rate_limited")
            return ConnectionTestResult(success=False, message="Bybit connection failed", error_code=exc.error_code)
        except Exception:
            return ConnectionTestResult(success=False, message="Bybit exchange unavailable", error_code="unavailable")

    async def fetch_snapshot(self) -> AccountSyncSnapshot:
        wallet = await self._signed_get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        balances: List[NormalizedBalance] = []
        equity = 0.0
        available = 0.0
        unrealized_total = 0.0
        for acct in wallet.get("list", []):
            equity += float(acct.get("totalEquity") or 0)
            available += float(acct.get("totalAvailableBalance") or 0)
            for coin in acct.get("coin", []):
                balances.append(
                    NormalizedBalance(
                        asset=str(coin.get("coin") or ""),
                        total_balance=float(coin.get("walletBalance") or 0),
                        available_balance=float(coin.get("availableToWithdraw") or coin.get("availableBalance") or 0),
                        equity=float(coin.get("equity") or 0),
                        used_margin=float(coin.get("totalPositionIM") or 0),
                        unrealized_pnl=float(coin.get("unrealisedPnl") or 0),
                        currency=str(coin.get("coin") or "USDT"),
                    )
                )
                unrealized_total += float(coin.get("unrealisedPnl") or 0)

        positions: List[NormalizedPosition] = []
        pos_result = await self._signed_get("/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
        for item in pos_result.get("list", []):
            size = float(item.get("size") or 0)
            if size <= 0:
                continue
            positions.append(
                NormalizedPosition(
                    symbol=str(item.get("symbol") or ""),
                    side=str(item.get("side") or "").lower(),
                    quantity=size,
                    entry_price=float(item.get("avgPrice") or 0) or None,
                    mark_price=float(item.get("markPrice") or 0) or None,
                    unrealized_pnl=float(item.get("unrealisedPnl") or 0),
                    leverage=float(item.get("leverage") or 0) or None,
                    liquidation_price=float(item.get("liqPrice") or 0) or None,
                )
            )

        orders: List[NormalizedOrder] = []
        try:
            order_result = await self._signed_get("/v5/order/realtime", {"category": "linear", "settleCoin": "USDT"})
            for item in order_result.get("list", []):
                orders.append(
                    NormalizedOrder(
                        exchange_order_id=str(item.get("orderId") or ""),
                        symbol=str(item.get("symbol") or ""),
                        side=str(item.get("side") or "").lower(),
                        order_type=str(item.get("orderType") or ""),
                        quantity=float(item.get("qty") or 0),
                        price=float(item.get("price") or 0) or None,
                        status=str(item.get("orderStatus") or "open"),
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
