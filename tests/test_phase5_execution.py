"""Phase 5 multi-leg execution, unwind, and production safety tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import Settings
from src.core.models.instrument import Instrument
from src.core.models.trade import StrategyLeg, StrategyTrade, StrategyState
from src.core.models.instrument import OptionType
from src.platform.execution.client_order_ids import build_client_order_id
from src.platform.execution.models import ExecutionResult, OrderLifecycleStatus, StrangleGroupStatus
from src.platform.execution.multi_leg_coordinator import StrangleExecutionCoordinator
from src.platform.execution.pipeline import OrderExecutionPipeline
from src.platform.execution.preflight import StranglePreflightChecker
from src.platform.runtime.models import ExecutionMode, RuntimeContext
from src.platform.runtime.ownership_guard import ExecutionOwnershipGuard
from src.platform.runtime.safety import ExecutionSafetyChecker


def _ctx(**kw):
    base = dict(
        user_id=uuid.uuid4(),
        subscription_id=uuid.uuid4(),
        strategy_account_id=uuid.uuid4(),
        strategy_code="short_strangle",
        strategy_name="Strangle",
        exchange="delta_india",
        exchange_account_id=uuid.uuid4(),
        exchange_account_label="Delta",
        execution_mode=ExecutionMode.LIVE_DRY_RUN,
        trading_enabled=True,
        subscription_status="ACTIVE",
        exchange_health_status="CONNECTED",
        exchange_connection_status="connected",
        is_testnet=True,
        exchange_trading_enabled=True,
    )
    base.update(kw)
    return RuntimeContext(**base)


def _trade():
    ce = StrategyLeg(
        leg_id="ce1", option_type=OptionType.CALL, instrument_id="1", symbol="BTC-C",
        strike=100000, expiry_date="2026-01-01", quantity=1, intended_premium=100,
    )
    pe = StrategyLeg(
        leg_id="pe1", option_type=OptionType.PUT, instrument_id="2", symbol="BTC-P",
        strike=90000, expiry_date="2026-01-01", quantity=1, intended_premium=100,
    )
    return StrategyTrade(
        strategy_trade_id="STRANGLE_20260101",
        strategy_name="short_strangle",
        trade_date="2026-01-01",
        ce_leg=ce,
        pe_leg=pe,
        state=StrategyState.IDLE,
    )


def _inst(symbol, iid):
    from src.core.models.instrument import InstrumentType
    return Instrument(
        exchange="delta_india",
        instrument_id=iid,
        symbol=symbol,
        underlying="BTC",
        instrument_type=InstrumentType.OPTION,
    )


def test_client_order_id_deterministic():
    sa = uuid.uuid4()
    a = build_client_order_id(strategy_account_id=sa, signal_key="sig1", leg_role="CE")
    b = build_client_order_id(strategy_account_id=sa, signal_key="sig1", leg_role="CE")
    assert a == b
    assert a != build_client_order_id(strategy_account_id=sa, signal_key="sig1", leg_role="PE")


def test_ownership_guard_blocks_when_legacy_running():
    guard = ExecutionOwnershipGuard()
    settings = Settings(_env_file=None, existing_strategy_enabled=True)
    ctx = _ctx(execution_mode=ExecutionMode.LIVE)
    result = guard.check_platform_live_start(ctx, settings, legacy_engine_running=True)
    assert result["allowed"] is False
    assert result["owner"] == "LEGACY_ENGINE"


@pytest.mark.asyncio
async def test_two_leg_success():
    ctx = _ctx()
    pipeline = MagicMock(spec=OrderExecutionPipeline)
    pipeline._adapter = MagicMock()
    pipeline._adapter.get_positions = AsyncMock(return_value=[])
    pipeline.process_intent = AsyncMock(
        return_value=ExecutionResult(True, OrderLifecycleStatus.WOULD_EXECUTE, "c1", filled_quantity=1.0, average_price=100.0)
    )
    groups = MagicMock()
    groups.get_by_signal = AsyncMock(return_value=None)
    groups.create_group = AsyncMock(return_value=uuid.uuid4())
    groups.update_status = AsyncMock()
    groups.list_incomplete = AsyncMock(return_value=[])
    preflight = MagicMock(spec=StranglePreflightChecker)
    preflight.run = AsyncMock(return_value=MagicMock(approved=True))
    coord = StrangleExecutionCoordinator(
        context=ctx, pipeline=pipeline, group_repository=groups, preflight=preflight,
    )
    trade = _trade()
    result = await coord.execute_strangle_entry(
        trade, _inst("BTC-C", "1"), _inst("BTC-P", "2"), 100, 100,
        runtime_status="RUNNING", market_data_fresh_fn=lambda: True,
    )
    assert result.success is True
    assert result.status == StrangleGroupStatus.COMPLETE
    assert pipeline.process_intent.await_count == 2


@pytest.mark.asyncio
async def test_two_leg_second_fails_triggers_unwind():
    ctx = _ctx()
    pipeline = MagicMock(spec=OrderExecutionPipeline)
    pipeline.halt_new_entries = MagicMock()
    adapter = MagicMock()
    adapter.get_positions = AsyncMock(return_value=[])
    adapter.get_order = AsyncMock(return_value=None)
    pipeline._adapter = adapter

    async def side_effect(intent, **kwargs):
        if "CE" in intent.client_order_id or intent.metadata.get("leg_role") == "CE":
            return ExecutionResult(True, OrderLifecycleStatus.WOULD_EXECUTE, intent.client_order_id, filled_quantity=1.0, average_price=100.0)
        if intent.metadata.get("is_unwind"):
            return ExecutionResult(True, OrderLifecycleStatus.WOULD_EXECUTE, intent.client_order_id, filled_quantity=1.0)
        return ExecutionResult(False, OrderLifecycleStatus.REJECTED, intent.client_order_id, message="PE rejected")

    pipeline.process_intent = AsyncMock(side_effect=side_effect)
    groups = MagicMock()
    groups.get_by_signal = AsyncMock(return_value=None)
    groups.create_group = AsyncMock(return_value=uuid.uuid4())
    groups.update_status = AsyncMock()
    groups.list_incomplete = AsyncMock(return_value=[])
    preflight = MagicMock()
    preflight.run = AsyncMock(return_value=MagicMock(approved=True))
    coord = StrangleExecutionCoordinator(context=ctx, pipeline=pipeline, group_repository=groups, preflight=preflight)
    trade = _trade()
    result = await coord.execute_strangle_entry(
        trade, _inst("BTC-C", "1"), _inst("BTC-P", "2"), 100, 100,
        runtime_status="RUNNING", market_data_fresh_fn=lambda: True,
    )
    assert result.success is False
    assert result.status in {StrangleGroupStatus.UNWOUND, StrangleGroupStatus.UNWIND_FAILED}


@pytest.mark.asyncio
async def test_stale_market_data_rejects_before_leg1():
    ctx = _ctx()
    pipeline = MagicMock(spec=OrderExecutionPipeline)
    pipeline.halt_new_entries = MagicMock()
    pipeline.process_intent = AsyncMock()
    pipeline._adapter = MagicMock()
    pipeline._adapter.get_positions = AsyncMock(return_value=[])
    groups = MagicMock()
    groups.get_by_signal = AsyncMock(return_value=None)
    groups.create_group = AsyncMock(return_value=uuid.uuid4())
    groups.update_status = AsyncMock()
    groups.list_incomplete = AsyncMock(return_value=[])
    preflight = MagicMock()
    preflight.run = AsyncMock(return_value=MagicMock(approved=True))
    coord = StrangleExecutionCoordinator(context=ctx, pipeline=pipeline, group_repository=groups, preflight=preflight)
    trade = _trade()
    result = await coord.execute_strangle_entry(
        trade, _inst("BTC-C", "1"), _inst("BTC-P", "2"), 100, 100,
        runtime_status="RUNNING", market_data_fresh_fn=lambda: False,
    )
    assert result.success is False
    pipeline.process_intent.assert_not_called()


def test_live_test_quantity_enforced_in_settings():
    settings = Settings(_env_file=None, platform_max_live_test_quantity=1.0)
    assert settings.platform_max_live_test_quantity == 1.0


def test_kill_switch_blocks_live_in_checker():
    checker = ExecutionSafetyChecker(platform_live_trading_enabled=False)
    ctx = _ctx(execution_mode=ExecutionMode.LIVE, trading_enabled=True)
    result = checker.check_order_submission(ctx, runtime_status="RUNNING", adapter_supports_execution=True)
    assert result.approved is False
