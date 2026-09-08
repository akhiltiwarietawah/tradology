"""End-to-End Verification Test Suite for Production Trading Dashboard (Scenarios 1-6)."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from src.config.settings import Settings, Environment
from src.core.models.trade import (
    StrategyTrade,
    StrategyLeg,
    StrategyState,
    LegStatus,
)
from src.core.models.instrument import OptionType
from src.core.models.market_data import Ticker
from src.core.models.position import Position
from src.reconciliation.reconciler import ReconciliationResult
from src.engine import TradingEngine
from src.api.app import create_app


@pytest.fixture
def e2e_engine(tmp_path, mock_exchange):
    """Fixture providing initialized TradingEngine configured for e2e verification."""
    settings = Settings(
        delta_env=Environment.TESTNET,
        kill_switch=False,
        dry_run=False,
        delta_testnet_api_key="mock_test_key",
        delta_testnet_api_secret="mock_test_secret",
        data_dir=str(tmp_path / "data"),
        logs_dir=str(tmp_path / "logs"),
        state_file=str(tmp_path / "data" / "state.json"),
        trades_log_file=str(tmp_path / "logs" / "trades.jsonl"),
        database_enabled=True,
    )
    engine = TradingEngine(settings=settings)
    engine.delta_adapter = mock_exchange
    engine.exchange_service.register_adapter(mock_exchange)
    engine.execution_engine.exchange = mock_exchange
    engine.strategy.exchange = mock_exchange
    engine.reconciler.exchange = mock_exchange
    engine.risk_manager._kill_switch_flag = False

    engine._running = True
    engine._last_reconciliation_result = ReconciliationResult(
        is_synchronized=True,
        status="SYNCHRONIZED",
        details={},
    )
    return engine


@pytest.mark.asyncio
async def test_scenario_1_clean_idle_state(e2e_engine):
    """Scenario 1: Clean/Idle state with no active trade and healthy connections."""
    e2e_engine.strategy.current_trade = None
    app = create_app(e2e_engine)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Health
        health_resp = await ac.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json() == {"status": "ok"}

        # 2. Readiness
        ready_resp = await ac.get("/ready")
        assert ready_resp.status_code == 200
        ready_data = ready_resp.json()
        assert ready_data["ready"] is True
        assert ready_data["engine"] == "RUNNING"
        assert ready_data["reconciliation"] == "SYNCHRONIZED"

        # 3. Status
        status_resp = await ac.get("/api/v1/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["engine"]["status"] == "RUNNING"
        assert status_data["current_trade"] is None
        assert status_data["reconciliation"]["is_synchronized"] is True

        # 4. Performance (empty cold-start)
        perf_resp = await ac.get("/api/v1/performance")
        assert perf_resp.status_code == 200
        perf_data = perf_resp.json()
        assert perf_data["status"] == "ok"
        assert perf_data["summary"]["trade_count"] == 0



@pytest.mark.asyncio
async def test_scenario_2_active_trade_simulation(e2e_engine):
    """Scenario 2: Active short strangle with CE & PE legs and native bracket SL IDs."""
    now_iso = datetime.now(timezone.utc).isoformat()
    e2e_engine.strategy.current_trade = StrategyTrade(
        strategy_trade_id="STRANGLE_20260901_090000",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_20260901_090000_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=105.0,
            current_price=80.0,
            sl_price=210.0,
            bracket_order_id="BRK_150401_210",
            exchange_sl_active=True,
            status=LegStatus.OPEN,
        ),
        pe_leg=StrategyLeg(
            leg_id="STRANGLE_20260901_090000_PE",
            option_type=OptionType.PUT,
            instrument_id="150402",
            symbol="P-BTC-92000-010926",
            strike=92000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=95.0,
            current_price=90.0,
            sl_price=190.0,
            bracket_order_id="BRK_150402_190",
            exchange_sl_active=True,
            status=LegStatus.OPEN,
        ),
    )

    app = create_app(e2e_engine)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        status_resp = await ac.get("/api/v1/status")
        assert status_resp.status_code == 200
        data = status_resp.json()

        ct = data["current_trade"]
        assert ct is not None
        assert ct["trade_id"] == "STRANGLE_20260901_090000"
        assert ct["trade_state"] == "ACTIVE"

        # CE Verification
        assert ct["ce_symbol"] == "C-BTC-98000-010926"
        assert ct["ce_strike"] == 98000.0
        assert ct["ce_quantity"] == 1.0
        assert ct["ce_entry_price"] == 105.0
        assert ct["ce_current_price"] == 80.0
        assert ct["ce_unrealized_pnl"] == 0.025
        assert ct["ce_sl_price"] == 210.0
        assert ct["ce_native_bracket_active"] is True
        assert ct["ce_bracket_order_id"] == "BRK_150401_210"

        # PE Verification
        assert ct["pe_symbol"] == "P-BTC-92000-010926"
        assert ct["pe_strike"] == 92000.0
        assert ct["pe_quantity"] == 1.0
        assert ct["pe_entry_price"] == 95.0
        assert ct["pe_current_price"] == 90.0
        assert ct["pe_unrealized_pnl"] == 0.005
        assert ct["pe_sl_price"] == 190.0
        assert ct["total_unrealized_pnl"] == 0.03
        assert ct["pe_native_bracket_active"] is True
        assert ct["pe_bracket_order_id"] == "BRK_150402_190"


@pytest.mark.asyncio
async def test_scenario_2b_unrealized_pnl_from_mark_cache(e2e_engine):
    """Live WS mark cache should populate current_price and unrealized PnL on /status."""
    now_iso = datetime.now(timezone.utc).isoformat()
    e2e_engine.strategy.current_trade = StrategyTrade(
        strategy_trade_id="STRANGLE_MARK_CACHE",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_MARK_CACHE_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            sl_price=200.0,
            bracket_order_id="BRK_CE",
            exchange_sl_active=True,
            status=LegStatus.OPEN,
        ),
        pe_leg=StrategyLeg(
            leg_id="STRANGLE_MARK_CACHE_PE",
            option_type=OptionType.PUT,
            instrument_id="150402",
            symbol="P-BTC-92000-010926",
            strike=92000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=100.0,
            sl_price=200.0,
            bracket_order_id="BRK_PE",
            exchange_sl_active=True,
            status=LegStatus.OPEN,
        ),
    )
    e2e_engine.delta_adapter.latest_tickers["C-BTC-98000-010926"] = Ticker(
        symbol="C-BTC-98000-010926",
        instrument_id="150401",
        mark_price=70.0,
    )
    e2e_engine.delta_adapter.latest_tickers["P-BTC-92000-010926"] = Ticker(
        symbol="P-BTC-92000-010926",
        instrument_id="150402",
        mark_price=130.0,
    )

    app = create_app(e2e_engine)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        data = (await ac.get("/api/v1/status")).json()["current_trade"]
        assert data["ce_current_price"] == 70.0
        assert data["pe_current_price"] == 130.0
        assert data["ce_unrealized_pnl"] == 0.03  # (100-70)*1*0.001
        assert data["pe_unrealized_pnl"] == -0.03  # (100-130)*1*0.001
        assert data["total_unrealized_pnl"] == 0.0


@pytest.mark.asyncio
async def test_scenario_3_safe_halt_state(e2e_engine):
    """Scenario 3: Corrupt/discrepant state triggers SAFE_HALT."""
    e2e_engine.strategy.current_trade = StrategyTrade(
        strategy_trade_id="STRANGLE_CORRUPT",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_CORRUPT_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_fill_price=0.0, # Ambiguous/corrupt
            sl_price=None,
            bracket_order_id=None,
            status=LegStatus.OPEN,
        ),
    )
    # Exchange has position but bracket is missing and persisted entry is corrupt
    e2e_engine.delta_adapter.positions = [
        Position(instrument_id="150401", symbol="C-BTC-98000-010926", size=-1.0, entry_price=100.0)
    ]

    await e2e_engine.reconcile_state()

    app = create_app(e2e_engine)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Readiness must be false
        ready_resp = await ac.get("/ready")
        assert ready_resp.status_code == 200
        ready_data = ready_resp.json()
        assert ready_data["ready"] is False
        assert ready_data["engine"] == "SAFE_HALT"
        assert ready_data["reconciliation"] == "UNSYNCHRONIZED"

        # 2. Status must report SAFE_HALT and discrepancy details
        status_resp = await ac.get("/api/v1/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["engine"]["status"] == "SAFE_HALT"
        assert status_data["engine"]["kill_switch"] is True
        assert status_data["reconciliation"]["is_synchronized"] is False
        assert "Missing native bracket SL" in str(status_data["reconciliation"]["latest_discrepancy"])


@pytest.mark.asyncio
async def test_scenario_5_postgres_failure_isolation(e2e_engine):
    """Scenario 5: PostgreSQL unavailable does not block trading or readiness."""
    # Simulate DB disconnected
    e2e_engine.db_manager._is_connected = False

    app = create_app(e2e_engine)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Readiness remains ready
        ready_resp = await ac.get("/ready")
        assert ready_resp.status_code == 200
        assert ready_resp.json()["ready"] is True

        # 2. Status reports DB unavailable
        status_resp = await ac.get("/api/v1/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["database"]["connected"] is False
        assert status_data["database"]["status"] == "UNAVAILABLE"

        # 3. Performance falls back gracefully without crashing
        perf_resp = await ac.get("/api/v1/performance")
        assert perf_resp.status_code == 200
        perf_data = perf_resp.json()
        assert perf_data["status"] == "ok"
        assert perf_data["source"] == "jsonl_fallback"
        assert "summary" in perf_data



@pytest.mark.asyncio
async def test_scenario_6_postgres_recovery(e2e_engine):
    """Scenario 6: PostgreSQL reconnects and status reflects recovery."""
    e2e_engine.db_manager._is_connected = True

    app = create_app(e2e_engine)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        status_resp = await ac.get("/api/v1/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["database"]["connected"] is True
        assert status_data["database"]["status"] == "AVAILABLE"
