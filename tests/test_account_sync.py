"""Phase 2 account sync tests with mocked exchange adapters."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.platform.repositories.platform_repository import PlatformRepository
from src.platform.repositories.sync_repository import SyncRepository
from src.platform.security.credentials import CredentialVault
from src.platform.sync.account_sync_service import AccountSyncService
from src.platform.sync.event_hub import PlatformEventHub
from src.platform.sync.models import (
    AccountSyncSnapshot,
    ConnectionTestResult,
    NormalizedBalance,
    NormalizedPosition,
)


@pytest.fixture
def vault():
    os.environ["CREDENTIALS_ENCRYPTION_KEY"] = "phase2-test-key-32-characters!!"
    return CredentialVault("phase2-test-key-32-characters!!")


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.dev"


def _unique_label(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


class MockSyncAdapter:
    exchange_code = "binance"

    async def test_connection(self):
        return ConnectionTestResult(success=True, message="ok")

    async def fetch_snapshot(self):
        return AccountSyncSnapshot(
            equity=1000.0,
            available_balance=900.0,
            unrealized_pnl=25.0,
            realized_pnl=0.0,
            currency="USDT",
            balances=[
                NormalizedBalance(
                    asset="USDT",
                    total_balance=1000,
                    available_balance=900,
                    equity=1000,
                    currency="USDT",
                )
            ],
            positions=[
                NormalizedPosition(
                    symbol="BTCUSDT",
                    side="long",
                    quantity=0.01,
                    entry_price=50000,
                    mark_price=51000,
                    unrealized_pnl=25,
                )
            ],
            synced_at=datetime.now(timezone.utc),
        )

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_sync_persists_balances_positions_and_equity(test_db_manager, vault):
    if not test_db_manager.is_connected:
        pytest.skip("Database unavailable")

    platform_repo = PlatformRepository(test_db_manager, vault)
    sync_repo = SyncRepository(test_db_manager)
    service = AccountSyncService(test_db_manager, PlatformEventHub(), vault)

    user = await platform_repo.upsert_user(email=_unique_email("sync"))
    account = await platform_repo.create_exchange_account(
        user_id=user.id,
        exchange="binance",
        label=_unique_label("main"),
        api_key="12345678",
        api_secret="87654321",
    )

    with patch("src.platform.sync.account_sync_service.create_account_sync_adapter", return_value=MockSyncAdapter()):
        updated = await service.sync_account(account.id, user.id)

    assert float(updated.equity) == 1000.0
    positions = await sync_repo.get_account_positions(user.id, account.id)
    assert len(positions) == 1
    curve = await sync_repo.get_equity_curve(user_id=user.id, account_id=account.id, range_key="ALL")
    assert len(curve) >= 1


@pytest.mark.asyncio
async def test_user_isolation_on_account_detail(test_db_manager, vault):
    if not test_db_manager.is_connected:
        pytest.skip("Database unavailable")

    platform_repo = PlatformRepository(test_db_manager, vault)
    service = AccountSyncService(test_db_manager, PlatformEventHub(), vault)
    user_a = await platform_repo.upsert_user(email=_unique_email("a"))
    user_b = await platform_repo.upsert_user(email=_unique_email("b"))
    account = await platform_repo.create_exchange_account(
        user_id=user_a.id,
        exchange="binance",
        label=_unique_label("iso"),
        api_key="12345678",
        api_secret="87654321",
    )

    with pytest.raises(PermissionError):
        await service.get_account_detail(user_b.id, account.id)


@pytest.mark.asyncio
async def test_failed_sync_sets_error_health(test_db_manager, vault):
    if not test_db_manager.is_connected:
        pytest.skip("Database unavailable")

    platform_repo = PlatformRepository(test_db_manager, vault)
    service = AccountSyncService(test_db_manager, PlatformEventHub(), vault)
    user = await platform_repo.upsert_user(email=_unique_email("fail"))
    account = await platform_repo.create_exchange_account(
        user_id=user.id,
        exchange="binance",
        label=_unique_label("fail"),
        api_key="12345678",
        api_secret="87654321",
    )

    class FailingAdapter(MockSyncAdapter):
        async def fetch_snapshot(self):
            raise RuntimeError("boom")

    with patch("src.platform.sync.account_sync_service.create_account_sync_adapter", return_value=FailingAdapter()):
        with pytest.raises(RuntimeError):
            await service.sync_account(account.id, user.id)

    refreshed = await platform_repo.get_exchange_account(user.id, account.id)
    assert refreshed.health_status == "ERROR"


@pytest.mark.asyncio
async def test_equity_curve_timeframe_filter(test_db_manager, vault):
    if not test_db_manager.is_connected:
        pytest.skip("Database unavailable")

    sync_repo = SyncRepository(test_db_manager)
    platform_repo = PlatformRepository(test_db_manager, vault)
    user = await platform_repo.upsert_user(email=_unique_email("curve"))
    account = await platform_repo.create_exchange_account(
        user_id=user.id,
        exchange="binance",
        label=_unique_label("curve"),
        api_key="12345678",
        api_secret="87654321",
    )

    snapshot = AccountSyncSnapshot(
        equity=500.0,
        available_balance=500.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        currency="USDT",
    )
    await sync_repo.persist_snapshot(account=account, snapshot=snapshot)
    points = await sync_repo.get_equity_curve(user_id=user.id, account_id=account.id, range_key="1D")
    assert isinstance(points, list)
    assert len(points) >= 1


@pytest.mark.asyncio
async def test_equity_snapshot_deduplication(test_db_manager, vault):
    if not test_db_manager.is_connected:
        pytest.skip("Database unavailable")

    sync_repo = SyncRepository(test_db_manager)
    platform_repo = PlatformRepository(test_db_manager, vault)
    user = await platform_repo.upsert_user(email=_unique_email("dedupe"))
    account = await platform_repo.create_exchange_account(
        user_id=user.id,
        exchange="binance",
        label=_unique_label("dedupe"),
        api_key="12345678",
        api_secret="87654321",
    )

    snapshot = AccountSyncSnapshot(
        equity=500.0,
        available_balance=500.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        currency="USDT",
    )
    await sync_repo.persist_snapshot(account=account, snapshot=snapshot)
    await sync_repo.persist_snapshot(account=account, snapshot=snapshot)
    points = await sync_repo.get_equity_curve(user_id=user.id, account_id=account.id, range_key="ALL")
    assert len(points) == 1


@pytest.mark.asyncio
async def test_encrypted_credentials_not_stored_plaintext(test_db_manager, vault):
    if not test_db_manager.is_connected:
        pytest.skip("Database unavailable")

    platform_repo = PlatformRepository(test_db_manager, vault)
    user = await platform_repo.upsert_user(email=_unique_email("cipher"))
    account = await platform_repo.create_exchange_account(
        user_id=user.id,
        exchange="binance",
        label=_unique_label("cipher"),
        api_key="super-secret-key",
        api_secret="super-secret-secret",
    )
    encrypted_blob = account.credentials_encrypted
    if isinstance(encrypted_blob, str):
        encrypted_blob = encrypted_blob.encode()
    assert b"super-secret-key" not in encrypted_blob
    assert b"super-secret-secret" not in encrypted_blob


@pytest.mark.asyncio
async def test_invalid_credentials_test_connection(vault):
    service = AccountSyncService(None, PlatformEventHub(), vault)

    class FailAdapter(MockSyncAdapter):
        async def test_connection(self):
            return ConnectionTestResult(success=False, message="Invalid credentials")

    with patch("src.platform.sync.account_sync_service.create_account_sync_adapter", return_value=FailAdapter()):
        result = await service.test_connection(
            exchange="binance",
            api_key="bad",
            api_secret="bad",
        )
    assert result.success is False
