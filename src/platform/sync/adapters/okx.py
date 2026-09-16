"""OKX v5 read-only account sync."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from src.platform.sync.adapter_base import AccountSyncAdapter
from src.platform.sync.http_utils import ExchangeHttpError, http_get_json, okx_sign
from src.platform.sync.models import (
    AccountSyncSnapshot,
    ConnectionTestResult,
    NormalizedBalance,
    NormalizedOrder,
    NormalizedPosition,
)


class OkxAccountSyncAdapter(AccountSyncAdapter):
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        passphrase: str,
        is_testnet: bool = False,
        logger: logging.Logger | None = None,
    ):
        self._api_key = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase
        self._base = "https://www.okx.com" if not is_testnet else "https://www.okx.com"
        self._logger = logger or logging.getLogger("okx_account_sync")

    @property
    def exchange_code(self) -> str:
        return "okx"

    async def _signed_get(self, path: str, params: Dict[str, Any] | None = None) -> Any:
        params = dict(params or {})
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        request_path = path if not query else f"{path}?{query}"
        sign = okx_sign(self._api_secret, timestamp, "GET", request_path)
        headers = {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self._passphrase,
            "Content-Type": "application/json",
        }
        url = f"{self._base}{request_path}"
        data = await http_get_json(url, headers=headers)
        if str(data.get("code")) != "0":
            raise ExchangeHttpError(str(data.get("msg") or "OKX API error"), error_code=str(data.get("code")))
        return data.get("data") or []

    async def test_connection(self) -> ConnectionTestResult:
        try:
            await self._signed_get("/api/v5/account/balance")
            return ConnectionTestResult(success=True, message="OKX credentials verified")
        except ExchangeHttpError as exc:
            if exc.error_code in ("50111", "50113", "50114"):
                return ConnectionTestResult(success=False, message="Invalid OKX credentials", error_code="invalid_credentials")
            if exc.status_code == 429:
                return ConnectionTestResult(success=False, message="OKX rate limited", error_code="rate_limited")
            return ConnectionTestResult(success=False, message="OKX connection failed", error_code=exc.error_code)
        except Exception:
            return ConnectionTestResult(success=False, message="OKX exchange unavailable", error_code="unavailable")

    async def fetch_snapshot(self) -> AccountSyncSnapshot:
        balance_rows = await self._signed_get("/api/v5/account/balance")
        balances: List[NormalizedBalance] = []
        equity = 0.0
        available = 0.0
        unrealized_total = 0.0
        for row in balance_rows:
            equity += float(row.get("totalEq") or 0)
            for detail in row.get("details", []):
                ccy = str(detail.get("ccy") or "")
                avail = float(detail.get("availBal") or 0)
                eq = float(detail.get("eq") or 0)
                available += avail
                balances.append(
                    NormalizedBalance(
                        asset=ccy,
                        total_balance=float(detail.get("cashBal") or eq),
                        available_balance=avail,
                        equity=eq,
                        used_margin=float(detail.get("frozenBal") or 0),
                        unrealized_pnl=float(detail.get("upl") or 0),
                        currency=ccy,
                    )
                )
                unrealized_total += float(detail.get("upl") or 0)

        positions: List[NormalizedPosition] = []
        pos_rows = await self._signed_get("/api/v5/account/positions")
        for item in pos_rows:
            qty = float(item.get("pos") or 0)
            if abs(qty) < 1e-12:
                continue
            positions.append(
                NormalizedPosition(
                    symbol=str(item.get("instId") or ""),
                    side=str(item.get("posSide") or ("long" if qty > 0 else "short")).lower(),
                    quantity=abs(qty),
                    entry_price=float(item.get("avgPx") or 0) or None,
                    mark_price=float(item.get("markPx") or 0) or None,
                    unrealized_pnl=float(item.get("upl") or 0),
                    leverage=float(item.get("lever") or 0) or None,
                    liquidation_price=float(item.get("liqPx") or 0) or None,
                )
            )

        orders: List[NormalizedOrder] = []
        try:
            order_rows = await self._signed_get("/api/v5/trade/orders-pending")
            for item in order_rows:
                orders.append(
                    NormalizedOrder(
                        exchange_order_id=str(item.get("ordId") or ""),
                        symbol=str(item.get("instId") or ""),
                        side=str(item.get("side") or "").lower(),
                        order_type=str(item.get("ordType") or ""),
                        quantity=float(item.get("sz") or 0),
                        price=float(item.get("px") or 0) or None,
                        status=str(item.get("state") or "live"),
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
