"""Phase 4 execution pipeline, safety, reconciliation, and parity tests."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.settings import Settings
from src.platform.execution.models import ExecutionLayerMode, OrderIntent, OrderLifecycleStatus
from src.platform.execution.paper_execution_adapter import PaperExecutionAdapter
from src.platform.execution.pipeline import OrderExecutionPipeline
from src.platform.execution.reconciliation import OrderReconciliationService, PositionReconciliationService
from src.platform.runtime.adapters.short_strangle_adapter import ShortStrangleRuntimeAdapter
from src.platform.runtime.market_data import NormalizedMarketDataFeed
from src.platform.runtime.models import ExecutionMode, RuntimeContext
from src.platform.runtime.safety import ExecutionSafetyChecker
from src.platform.runtime.worker_coordinator import RuntimeWorkerCoordinator


def _ctx(**overrides):
    base = dict(
        user_id=uuid.uuid4(),
        subscription_id=uuid.uuid4(),
        strategy_account_id=uuid.uuid4(),
        strategy_code="short_strangle",
        strategy_name="BTC Strangle",
        exchange="delta_india",
        exchange_account_id=uuid.uuid4(),
        exchange_account_label="Delta Main",
        execution_mode=ExecutionMode.PAPER,
        trading_enabled=True,
        subscription_status="ACTIVE",
        exchange_health_status="CONNECTED",
        exchange_connection_status="connected",
        is_testnet=True,
        exchange_trading_enabled=True,
    )
    base.update(overrides)
    return RuntimeContext(**base)


def test_global_kill_switch_blocks_live_orders():
    checker = ExecutionSafetyChecker(
        platform_runtime_execution_enabled=True,
        platform_live_trading_enabled=False,
        platform_delta_live_enabled=True,
    )
    ctx = _ctx(execution_mode=ExecutionMode.LIVE)
    result = checker.check_order_submission(ctx, runtime_status="RUNNING", adapter_supports_execution=True)
    assert result.approved is False
    assert result.code == "global_kill_switch"


def test_delta_live_flag_required_for_live():
    checker = ExecutionSafetyChecker(
        platform_runtime_execution_enabled=True,
        platform_live_trading_enabled=True,
        platform_delta_live_enabled=False,
    )
    ctx = _ctx(execution_mode=ExecutionMode.LIVE)
    result = checker.check_live_enable(ctx)
    assert result.approved is False
    assert result.code == "delta_live_disabled"


def test_account_trading_kill_switch():
    checker = ExecutionSafetyChecker()
    ctx = _ctx(exchange_trading_enabled=False)
    result = checker.check_order_submission(ctx, runtime_status="RUNNING", adapter_supports_execution=True)
    assert result.approved is False
    assert result.code == "account_trading_disabled"


def test_subscription_paused_blocks_entries():
    checker = ExecutionSafetyChecker()
    ctx = _ctx(subscription_status="PAUSED")
    result = checker.check_order_submission(ctx, runtime_status="RUNNING", adapter_supports_execution=True)
    assert result.approved is False
    assert result.code == "subscription_paused"


def test_live_dry_run_allowed_without_live_flags():
    checker = ExecutionSafetyChecker(platform_runtime_execution_enabled=False)
    ctx = _ctx(execution_mode=ExecutionMode.LIVE_DRY_RUN)
    result = checker.check_order_submission(ctx, runtime_status="RUNNING", adapter_supports_execution=True)
    assert result.approved is True


def test_pipeline_resolves_paper_layer():
    settings = Settings(_env_file=None, platform_runtime_execution_enabled=False)
    pipeline = OrderExecutionPipeline(
        context=_ctx(),
        settings=settings,
        safety_checker=ExecutionSafetyChecker(),
        runtime_repository=MagicMock(),
        lifecycle_repository=MagicMock(),
        credentials={},
    )
    assert pipeline._resolve_execution_layer() == ExecutionLayerMode.PAPER


def test_pipeline_live_falls_back_to_dry_run_when_flags_off():
    settings = Settings(
        _env_file=None,
        platform_runtime_execution_enabled=False,
        platform_live_dry_run_enabled=True,
    )
    pipeline = OrderExecutionPipeline(
        context=_ctx(execution_mode=ExecutionMode.LIVE),
        settings=settings,
        safety_checker=ExecutionSafetyChecker(),
        runtime_repository=MagicMock(),
        lifecycle_repository=MagicMock(),
        credentials={},
    )
    assert pipeline._resolve_execution_layer() == ExecutionLayerMode.LIVE_DRY_RUN


def test_pipeline_live_when_all_flags_enabled():
    settings = Settings(
        _env_file=None,
        platform_runtime_execution_enabled=True,
        platform_delta_live_enabled=True,
        platform_live_trading_enabled=True,
    )
    pipeline = OrderExecutionPipeline(
        context=_ctx(execution_mode=ExecutionMode.LIVE),
        settings=settings,
        safety_checker=ExecutionSafetyChecker(
            platform_runtime_execution_enabled=True,
            platform_live_trading_enabled=True,
            platform_delta_live_enabled=True,
        ),
        runtime_repository=MagicMock(),
        lifecycle_repository=MagicMock(),
        credentials={"api_key": "k", "api_secret": "s"},
    )
    assert pipeline._resolve_execution_layer() == ExecutionLayerMode.LIVE


@pytest.mark.asyncio
async def test_paper_pipeline_process_intent():
    os.environ["CREDENTIALS_ENCRYPTION_KEY"] = "phase4-test-key-32-characters!!"
    ctx = _ctx()
    lifecycle_repo = MagicMock()
    lifecycle_repo.create_intent = AsyncMock(return_value=uuid.uuid4())
    lifecycle_repo.update_status = AsyncMock()
    runtime_repo = MagicMock()
    runtime_repo.reserve_idempotency_key = AsyncMock(return_value=True)
    runtime_repo.update_idempotency_status = AsyncMock()

    pipeline = OrderExecutionPipeline(
        context=ctx,
        settings=Settings(_env_file=None),
        safety_checker=ExecutionSafetyChecker(),
        runtime_repository=runtime_repo,
        lifecycle_repository=lifecycle_repo,
        credentials={},
    )
    await pipeline.initialize()
    result = await pipeline.process_intent(
        OrderIntent(
            signal_key="sig1",
            client_order_id="P_test_1",
            symbol="BTC-OPT",
            side="sell",
            quantity=1.0,
        ),
        runtime_status="RUNNING",
    )
    assert result.success is True
    assert result.status == OrderLifecycleStatus.FILLED


@pytest.mark.asyncio
async def test_order_reconciliation_unknown_halts():
    lifecycle_repo = MagicMock()
    lifecycle_repo.list_open_intents = AsyncMock(return_value=[{"client_order_id": "x", "status": "UNKNOWN"}])
    adapter = MagicMock()
    adapter.get_open_orders = AsyncMock(return_value=[])
    halted = []
    service = OrderReconciliationService(lifecycle_repo)
    report = await service.reconcile(
        strategy_account_id=uuid.uuid4(),
        execution_adapter=adapter,
        halt_callback=lambda msg: halted.append(msg),
    )
    assert report.matched is False
    assert report.status == "UNKNOWN"
    assert halted


@pytest.mark.asyncio
async def test_position_reconciliation_mismatch():
    adapter = MagicMock()
    adapter.get_positions = AsyncMock(return_value=[{"symbol": "BTC-C", "size": 1.0}])
    service = PositionReconciliationService()
    report = await service.reconcile(
        expected_positions=[],
        execution_adapter=adapter,
    )
    assert report.matched is False
    assert report.status == "MISMATCH"


def test_market_data_stale_detection():
    feed = NormalizedMarketDataFeed(stale_after_seconds=0.01)
    feed.normalize_ticker(symbol="BTC", mark_price=100.0, source="delta")
    import time

    time.sleep(0.02)
    assert feed.is_stale is True


def test_short_strangle_adapter_find_leg():
    from src.core.models.trade import StrategyLeg, StrategyTrade, StrategyState
    from src.core.models.instrument import OptionType

    trade = StrategyTrade(
        strategy_trade_id="t1",
        strategy_name="short_strangle",
        trade_date="2026-01-01",
        ce_leg=StrategyLeg(
            leg_id="ce1",
            option_type=OptionType.CALL,
            instrument_id="1",
            symbol="BTC-C",
            strike=100000,
            expiry_date="2026-01-01",
            quantity=1,
            intended_premium=100,
        ),
        state=StrategyState.ACTIVE,
    )
    leg = ShortStrangleRuntimeAdapter._find_leg(trade, "ce1")
    assert leg is not None
    assert leg.symbol == "BTC-C"


@pytest.mark.asyncio
async def test_delta_adapter_timeout_returns_unknown():
    from src.platform.execution.delta_execution_adapter import DeltaExecutionAdapter

    adapter = DeltaExecutionAdapter(api_key="k", api_secret="s", is_testnet=True)
    adapter._adapter = MagicMock()
    adapter._adapter.place_order = AsyncMock(side_effect=__import__("asyncio").TimeoutError())
    adapter.get_order = AsyncMock(return_value=None)

    intent = OrderIntent(
        signal_key="s",
        client_order_id="c1",
        symbol="BTC",
        side="sell",
        quantity=1,
    )
    result = await adapter.place_order(intent)
    assert result.status == OrderLifecycleStatus.UNKNOWN
    assert result.success is False
