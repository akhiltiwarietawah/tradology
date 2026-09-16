"""Tests for platform foundation (users, strategies, subscriptions, exchange accounts)."""

import os
import uuid
import pytest

from src.platform.security.credentials import CredentialVault
from src.platform.repositories.platform_repository import PlatformRepository


@pytest.fixture
def vault():
    os.environ["CREDENTIALS_ENCRYPTION_KEY"] = "test-platform-key-32chars-minimum!!"
    return CredentialVault("test-platform-key-32chars-minimum!!")


def test_credential_vault_roundtrip(vault):
    payload = {"api_key": "abc123secret", "api_secret": "supersecretvalue"}
    encrypted = vault.encrypt_credentials(payload)
    decrypted = vault.decrypt_credentials(encrypted)
    assert decrypted == payload
    redacted = vault.redact_for_response(decrypted)
    assert "supersecretvalue" not in str(redacted)


@pytest.mark.asyncio
async def test_platform_user_upsert_and_strategy_seed(test_db_manager, vault):
    if not test_db_manager.is_connected:
        pytest.skip("Database not available")

    repo = PlatformRepository(test_db_manager, vault)
    email = f"trader-{uuid.uuid4().hex[:8]}@example.com"
    user = await repo.upsert_user(email=email, name="Trader One")
    assert user.email == email

    strategies = await repo.list_strategies()
    codes = {s.code for s in strategies}
    assert "short_strangle" in codes
    assert "renko_ichimoku_eth" in codes or "renko_ichimoku" in codes

    strategy = await repo.get_strategy_by_code("short_strangle")
    sub = await repo.create_subscription(user.id, strategy.id)
    assert sub.user_id == user.id

    account = await repo.create_exchange_account(
        user_id=user.id,
        exchange="binance",
        label=f"Binance-{uuid.uuid4().hex[:6]}",
        api_key="key12345678",
        api_secret="secret12345678",
    )
    assert account.exchange == "binance"

    link = await repo.link_strategy_account(
        subscription_id=sub.id,
        exchange_account_id=account.id,
        status="paused",
    )
    assert link.subscription_id == sub.id
