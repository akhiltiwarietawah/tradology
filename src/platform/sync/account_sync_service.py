"""Account synchronization service — read-only exchange polling."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, Optional

from src.persistence.db import DatabaseManager
from src.persistence.platform_models import ExchangeAccountModel
from src.platform.repositories.platform_repository import PlatformRepository
from src.platform.repositories.sync_repository import SyncRepository
from src.platform.security.credentials import CredentialVault
from src.platform.sync.event_hub import PlatformEventHub
from src.platform.sync.factory import create_account_sync_adapter
from src.platform.sync.http_utils import ExchangeHttpError
from src.platform.sync.models import ConnectionTestResult


class AccountSyncService:
    def __init__(
        self,
        db_manager: DatabaseManager,
        event_hub: Optional[PlatformEventHub] = None,
        vault: Optional[CredentialVault] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.db = db_manager
        self.event_hub = event_hub or PlatformEventHub()
        self.vault = vault or CredentialVault()
        self.platform_repo = PlatformRepository(db_manager, self.vault)
        self.sync_repo = SyncRepository(db_manager)
        self.logger = logger or logging.getLogger("account_sync_service")
        self._sync_locks: Dict[str, asyncio.Lock] = {}

    def _lock_for(self, account_id: uuid.UUID) -> asyncio.Lock:
        key = str(account_id)
        if key not in self._sync_locks:
            self._sync_locks[key] = asyncio.Lock()
        return self._sync_locks[key]

    async def test_connection(
        self,
        *,
        exchange: str,
        api_key: str,
        api_secret: str,
        passphrase: Optional[str] = None,
        is_testnet: bool = False,
    ) -> ConnectionTestResult:
        adapter = create_account_sync_adapter(
            exchange,
            {"api_key": api_key, "api_secret": api_secret, "passphrase": passphrase},
            is_testnet=is_testnet,
            logger=self.logger,
        )
        try:
            return await adapter.test_connection()
        finally:
            await adapter.close()

    async def sync_account(self, account_id: uuid.UUID, user_id: uuid.UUID) -> ExchangeAccountModel:
        account = await self.platform_repo.get_exchange_account(user_id, account_id)
        if not account:
            raise PermissionError("Account not found")

        lock = self._lock_for(account_id)
        if lock.locked():
            await self.sync_repo.set_account_health(account_id, health_status="SYNCING")
            return account

        async with lock:
            await self.sync_repo.set_account_health(account_id, health_status="SYNCING")
            await self._publish(user_id, "account.status.updated", {"account_id": str(account_id), "status": "SYNCING"})

            credentials = self.vault.decrypt_credentials(account.credentials_encrypted)
            adapter = create_account_sync_adapter(
                account.exchange,
                credentials,
                is_testnet=account.is_testnet,
                logger=self.logger,
            )
            try:
                snapshot = await adapter.fetch_snapshot()
                updated = await self.sync_repo.persist_snapshot(account=account, snapshot=snapshot)
                await self._publish(
                    str(user_id),
                    "account.balance.updated",
                    {
                        "account_id": str(account_id),
                        "equity": float(updated.equity or 0),
                        "available_balance": float(updated.available_balance or 0),
                        "unrealized_pnl": float(updated.unrealized_pnl or 0),
                    },
                )
                await self._publish(
                    str(user_id),
                    "account.position.updated",
                    {"account_id": str(account_id), "positions_count": len(snapshot.positions)},
                )
                return updated
            except ExchangeHttpError as exc:
                msg = "Exchange rate limited" if exc.error_code == "rate_limited" else "Exchange sync failed"
                await self.sync_repo.set_account_health(
                    account_id,
                    health_status="DEGRADED" if exc.error_code == "rate_limited" else "ERROR",
                    connection_status="error",
                    last_error=msg,
                )
                await self._publish(user_id, "account.status.updated", {"account_id": str(account_id), "status": "ERROR"})
                raise
            except Exception as exc:
                self.logger.warning("Account sync failed for %s: %s", account_id, type(exc).__name__)
                await self.sync_repo.set_account_health(
                    account_id,
                    health_status="ERROR",
                    connection_status="error",
                    last_error="Unable to synchronize account",
                )
                await self._publish(user_id, "account.status.updated", {"account_id": str(account_id), "status": "ERROR"})
                raise
            finally:
                await adapter.close()

    async def sync_all_accounts(self) -> int:
        if not self.db.is_connected:
            return 0
        accounts = await self.sync_repo.list_accounts_for_background_sync()
        synced = 0
        for account in accounts:
            try:
                await self.sync_account(account.id, account.user_id)
                synced += 1
            except Exception:
                continue
        return synced

    async def get_account_detail(self, user_id: uuid.UUID, account_id: uuid.UUID) -> Dict[str, Any]:
        account = await self.platform_repo.get_exchange_account(user_id, account_id)
        if not account:
            raise PermissionError("Account not found")
        positions = await self.sync_repo.get_account_positions(user_id, account_id)
        orders = await self.sync_repo.get_account_orders(account_id)
        return {
            "account": self.account_to_safe_dict(account),
            "positions": [self._position_dict(p) for p in positions],
            "orders": [self._order_dict(o) for o in orders],
        }

    @staticmethod
    def account_to_safe_dict(account: ExchangeAccountModel) -> Dict[str, Any]:
        return {
            "id": str(account.id),
            "exchange": account.exchange,
            "label": account.label,
            "account_name": account.label,
            "status": account.health_status or account.connection_status,
            "health_status": account.health_status,
            "connection_status": account.connection_status,
            "balance": float(account.equity or 0),
            "equity": float(account.equity or 0),
            "available_balance": float(account.available_balance or 0),
            "unrealized_pnl": float(account.unrealized_pnl or 0),
            "realized_pnl": float(account.realized_pnl or 0),
            "currency": account.currency or "USD",
            "last_synced_at": account.last_sync_at.isoformat() if account.last_sync_at else None,
            "last_successful_sync_at": account.last_successful_sync_at.isoformat() if account.last_successful_sync_at else None,
            "last_error": account.last_error,
            "last_error_at": account.last_error_at.isoformat() if account.last_error_at else None,
            "is_testnet": account.is_testnet,
            "trading_enabled": bool(getattr(account, "trading_enabled", True)),
        }

    @staticmethod
    def _position_dict(pos) -> Dict[str, Any]:
        return {
            "symbol": pos.symbol,
            "side": pos.side,
            "quantity": float(pos.quantity),
            "entry_price": float(pos.entry_price) if pos.entry_price is not None else None,
            "mark_price": float(pos.mark_price) if pos.mark_price is not None else None,
            "unrealized_pnl": float(pos.unrealized_pnl or 0),
            "realized_pnl": float(pos.realized_pnl or 0),
            "leverage": float(pos.leverage) if pos.leverage is not None else None,
            "liquidation_price": float(pos.liquidation_price) if pos.liquidation_price is not None else None,
        }

    @staticmethod
    def _order_dict(order) -> Dict[str, Any]:
        return {
            "exchange_order_id": order.exchange_order_id,
            "symbol": order.symbol,
            "side": order.side,
            "order_type": order.order_type,
            "quantity": float(order.quantity or 0),
            "price": float(order.price) if order.price is not None else None,
            "status": order.status,
        }

    async def _publish(self, user_id: Any, event_type: str, payload: Dict[str, Any]) -> None:
        await self.event_hub.publish(str(user_id), event_type, payload)
