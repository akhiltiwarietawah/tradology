"""Phase 3 strategy runtime tests."""

from __future__ import annotations

import os
import uuid

import pytest

from src.config.settings import Settings
from src.platform.repositories.platform_repository import PlatformRepository
from src.platform.runtime.manager import StrategyRuntimeManager
from src.platform.runtime.models import ExecutionMode, RuntimeContext
from src.platform.runtime.repository import RuntimeRepository
from src.platform.runtime.risk_engine import PlatformRiskEngine
from src.platform.runtime.safety import ExecutionSafetyChecker
from src.platform.security.credentials import CredentialVault
from src.platform.sync.event_hub import PlatformEventHub


@pytest.fixture
def vault():
    os.environ["CREDENTIALS_ENCRYPTION_KEY"] = "phase3-test-key-32-characters!!"
    return CredentialVault("phase3-test-key-32-characters!!")


@pytest.fixture
def runtime_settings():
    return Settings(
        _env_file=None,
        platform_runtime_execution_enabled=False,
        platform_runtime_heartbeat_seconds=1,
        postgres_db="crypto_trading_test",
    )


def _ctx(**overrides):
    base = dict(
        user_id=uuid.uuid4(),
        subscription_id=uuid.uuid4(),
        strategy_account_id=uuid.uuid4(),
        strategy_code="renko_ichimoku_eth",
        strategy_name="Renko",
        exchange="delta_india",
        exchange_account_id=uuid.uuid4(),
        exchange_account_label="Delta Main",
        execution_mode=ExecutionMode.PAPER,
        trading_enabled=False,
        subscription_status="ACTIVE",
        exchange_health_status="CONNECTED",
        exchange_connection_status="connected",
        is_testnet=True,
    )
    base.update(overrides)
    return RuntimeContext(**base)


def test_safety_rejects_trading_when_disabled():
    checker = ExecutionSafetyChecker(platform_runtime_execution_enabled=False)
    ctx = _ctx(trading_enabled=False)
    result = checker.check_order_submission(
        ctx,
        runtime_status="RUNNING",
        adapter_supports_execution=True,
    )
    assert result.approved is False
    assert result.code == "trading_disabled"


def test_safety_rejects_live_when_platform_disabled():
    checker = ExecutionSafetyChecker(platform_runtime_execution_enabled=False)
    ctx = _ctx(execution_mode=ExecutionMode.LIVE, trading_enabled=True)
    result = checker.check_live_enable(ctx)
    assert result.approved is False
    assert result.code == "platform_disabled"


def test_risk_engine_rejects_oversized_order():
    engine = PlatformRiskEngine({"max_order_size": 1.0})
    result = engine.evaluate_order(order_size=5.0)
    assert result.approved is False
    assert result.code == "max_order_size"


@pytest.mark.asyncio
async def test_idempotency_prevents_duplicate_orders(test_db_manager, vault):
    if not test_db_manager.is_connected:
        pytest.skip("Database unavailable")

    repo = RuntimeRepository(test_db_manager)
    platform_repo = PlatformRepository(test_db_manager, vault)
    user = await platform_repo.upsert_user(email=f"idem-{uuid.uuid4().hex[:8]}@test.dev")
    account = await platform_repo.create_exchange_account(
        user_id=user.id,
        exchange="binance",
        label=f"idem-{uuid.uuid4().hex[:6]}",
        api_key="12345678",
        api_secret="87654321",
    )
    strategy = await platform_repo.get_strategy_by_code("short_strangle")
    sub = await platform_repo.create_subscription(user.id, strategy.id)
    sa = await platform_repo.link_strategy_account(
        subscription_id=sub.id,
        exchange_account_id=account.id,
    )

    first = await repo.reserve_idempotency_key(sa.id, "client-1", signal_key="sig-1")
    second = await repo.reserve_idempotency_key(sa.id, "client-1", signal_key="sig-1")
    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_runtime_start_stop_paper_mode(test_db_manager, vault, runtime_settings):
    if not test_db_manager.is_connected:
        pytest.skip("Database unavailable")

    platform_repo = PlatformRepository(test_db_manager, vault)
    manager = StrategyRuntimeManager(test_db_manager, runtime_settings, PlatformEventHub(), vault)
    user = await platform_repo.upsert_user(email=f"rt-{uuid.uuid4().hex[:8]}@test.dev")
    account = await platform_repo.create_exchange_account(
        user_id=user.id,
        exchange="delta_india",
        label=f"rt-{uuid.uuid4().hex[:6]}",
        api_key="12345678",
        api_secret="87654321",
        is_testnet=True,
    )
    strategy = await platform_repo.get_strategy_by_code("renko_ichimoku_eth")
    if strategy is None:
        strategy = await platform_repo.get_strategy_by_code("renko_ichimoku")
    sub = await platform_repo.create_subscription(user.id, strategy.id)
    sa = await platform_repo.link_strategy_account(subscription_id=sub.id, exchange_account_id=account.id)

    from src.persistence.platform_models import ExchangeAccountModel

    async with test_db_manager.get_session() as session:
        row = await session.get(ExchangeAccountModel, account.id)
        row.health_status = "CONNECTED"
        row.connection_status = "connected"
        await session.commit()

    snapshot = await manager.start_runtime(user.id, sa.id)
    assert snapshot.status == "RUNNING"
    assert snapshot.execution_mode == "PAPER"

    stopped = await manager.stop_runtime(user.id, sa.id)
    assert stopped.status == "STOPPED"


@pytest.mark.asyncio
async def test_user_isolation_on_runtime_start(test_db_manager, vault, runtime_settings):
    if not test_db_manager.is_connected:
        pytest.skip("Database unavailable")

    platform_repo = PlatformRepository(test_db_manager, vault)
    manager = StrategyRuntimeManager(test_db_manager, runtime_settings, PlatformEventHub(), vault)
    user_a = await platform_repo.upsert_user(email=f"a-{uuid.uuid4().hex[:8]}@test.dev")
    user_b = await platform_repo.upsert_user(email=f"b-{uuid.uuid4().hex[:8]}@test.dev")
    account = await platform_repo.create_exchange_account(
        user_id=user_a.id,
        exchange="binance",
        label=f"iso-{uuid.uuid4().hex[:6]}",
        api_key="12345678",
        api_secret="87654321",
    )
    strategy = await platform_repo.get_strategy_by_code("short_strangle")
    sub = await platform_repo.create_subscription(user_a.id, strategy.id)
    sa = await platform_repo.link_strategy_account(subscription_id=sub.id, exchange_account_id=account.id)

    with pytest.raises(PermissionError):
        await manager.build_context(user_b.id, sa.id)


def test_paper_runtime_rejects_when_trading_disabled():
    checker = ExecutionSafetyChecker(platform_runtime_execution_enabled=False)
    ctx = _ctx(trading_enabled=False)
    result = checker.check_order_submission(
        ctx,
        runtime_status="RUNNING",
        adapter_supports_execution=True,
    )
    assert result.approved is False
    assert result.code == "trading_disabled"


@pytest.mark.asyncio
async def test_recovery_marks_interrupted_runtimes(test_db_manager, vault):
    if not test_db_manager.is_connected:
        pytest.skip("Database unavailable")

    repo = RuntimeRepository(test_db_manager)
    platform_repo = PlatformRepository(test_db_manager, vault)
    user = await platform_repo.upsert_user(email=f"rec-{uuid.uuid4().hex[:8]}@test.dev")
    account = await platform_repo.create_exchange_account(
        user_id=user.id,
        exchange="binance",
        label=f"rec-{uuid.uuid4().hex[:6]}",
        api_key="12345678",
        api_secret="87654321",
    )
    strategy = await platform_repo.get_strategy_by_code("short_strangle")
    sub = await platform_repo.create_subscription(user.id, strategy.id)
    sa = await platform_repo.link_strategy_account(subscription_id=sub.id, exchange_account_id=account.id)
    await repo.upsert_runtime(sa.id, status="RUNNING")

    from src.platform.runtime.recovery import RuntimeRecoveryService

    service = RuntimeRecoveryService(repo)
    count = await service.recover_on_startup(platform_runtime_execution_enabled=False)
    assert count >= 1
    runtime = await repo.get_runtime_by_strategy_account(sa.id)
    assert runtime.status == "RECOVERY_REQUIRED"
