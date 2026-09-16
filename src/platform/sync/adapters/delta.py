"""Delta Exchange India read-only account sync."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.config.constants import LIVE_REST_URL, TESTNET_REST_URL
from src.exchanges.delta.client import DeltaAPIError, DeltaRestClient
from src.exchanges.delta.mapper import DeltaMapper
from src.platform.sync.adapter_base import AccountSyncAdapter
from src.platform.sync.models import (
    AccountSyncSnapshot,
    ConnectionTestResult,
    NormalizedBalance,
    NormalizedOrder,
    NormalizedPosition,
)


class DeltaAccountSyncAdapter(AccountSyncAdapter):
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        is_testnet: bool = False,
        logger: logging.Logger | None = None,
    ):
        self._exchange_code = "delta_india"
        self._logger = logger or logging.getLogger("delta_account_sync")
        rest_url = TESTNET_REST_URL if is_testnet else LIVE_REST_URL
        self._client = DeltaRestClient(
            base_url=rest_url,
            api_key=api_key,
            api_secret=api_secret,
            logger=self._logger,
        )

    @property
    def exchange_code(self) -> str:
        return self._exchange_code

    async def test_connection(self) -> ConnectionTestResult:
        try:
            await self._client.get_wallet_balances()
            return ConnectionTestResult(success=True, message="Delta credentials verified")
        except DeltaAPIError as exc:
            msg = str(exc)
            code = "invalid_credentials" if exc.status_code in (401, 403) else "exchange_error"
            return ConnectionTestResult(success=False, message="Invalid Delta credentials or permissions", error_code=code)
        except Exception:
            return ConnectionTestResult(success=False, message="Delta exchange unavailable", error_code="unavailable")

    async def fetch_snapshot(self) -> AccountSyncSnapshot:
        raw_balances = await self._client.get_wallet_balances()
        account_balance = DeltaMapper.to_account_balance(raw_balances)
        raw_positions = await self._client.get_positions()
        raw_orders = await self._client.get_open_orders()

        balances = []
        for sym, bal in account_balance.balances.items():
            balances.append(
                NormalizedBalance(
                    asset=sym,
                    total_balance=float(bal.balance),
                    available_balance=float(bal.available_balance),
                    equity=float(bal.balance),
                    used_margin=float(bal.blocked_margin or 0),
                    currency=sym,
                )
            )

        positions = []
        unrealized_total = 0.0
        for raw in raw_positions:
            pos = DeltaMapper.to_position(raw)
            if abs(pos.size) < 1e-8:
                continue
            side = "long" if pos.size > 0 else "short"
            positions.append(
                NormalizedPosition(
                    symbol=pos.symbol,
                    side=side,
                    quantity=abs(pos.size),
                    entry_price=pos.entry_price or None,
                    mark_price=pos.mark_price or None,
                    unrealized_pnl=float(pos.unrealized_pnl or 0),
                    realized_pnl=float(pos.realized_pnl or 0),
                    liquidation_price=pos.liquidation_price,
                )
            )
            unrealized_total += float(pos.unrealized_pnl or 0)

        orders = []
        for raw in raw_orders:
            orders.append(
                NormalizedOrder(
                    exchange_order_id=str(raw.get("id") or raw.get("order_id") or ""),
                    symbol=str(raw.get("product_symbol") or raw.get("symbol") or ""),
                    side=str(raw.get("side") or "").lower(),
                    order_type=str(raw.get("order_type") or raw.get("type") or "unknown"),
                    quantity=float(raw.get("size") or raw.get("quantity") or 0),
                    price=float(raw.get("limit_price") or raw.get("price") or 0) or None,
                    status=str(raw.get("state") or raw.get("status") or "open"),
                )
            )

        equity = float(account_balance.net_equity or 0)
        available = sum(b.available_balance for b in balances) if balances else equity

        return AccountSyncSnapshot(
            equity=equity,
            available_balance=available,
            unrealized_pnl=unrealized_total,
            realized_pnl=0.0,
            currency="USD",
            balances=balances,
            positions=positions,
            orders=orders,
            synced_at=datetime.now(timezone.utc),
        )

    async def close(self) -> None:
        await self._client.close()
