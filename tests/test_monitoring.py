"""Tests for production monitoring, health, liveness, readiness, watchdog, and AlertService."""

import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from src.api.app import create_app
from src.engine import TradingEngine
from src.config.settings import Settings, Environment
from src.monitoring.alerts import AlertService, AlertSeverity
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.models.instrument import OptionType
from src.reconciliation.reconciler import ReconciliationResult


@pytest.fixture
def mock_engine(tmp_path, mock_exchange):
    """Fixture providing initialized TradingEngine with mock adapters."""
    settings = Settings(
        delta_env=Environment.TESTNET,
        kill_switch=False,
        dry_run=False,
        delta_testnet_api_key="mock_secret_key_12345",
        delta_testnet_api_secret="mock_secret_password_67890",
        data_dir=str(tmp_path / "data"),
        logs_dir=str(tmp_path / "logs"),
        state_file=str(tmp_path / "data" / "state.json"),
        alert_cooldown_seconds=60,
    )
    engine = TradingEngine(settings=settings)
    engine.delta_adapter = mock_exchange
    engine.exchange_service.register_adapter(mock_exchange)
    engine.execution_engine.exchange = mock_exchange
    engine.strategy.exchange = mock_exchange
    engine.reconciler.exchange = mock_exchange
    engine.risk_manager._kill_switch_flag = False

    # Mark as running and synchronized by default for testing
    engine._running = True
    engine._last_reconciliation_result = ReconciliationResult(
        is_synchronized=True,
        status="SYNCHRONIZED",
        details={},
    )
    return engine



@pytest.mark.asyncio
async def test_health_liveness_endpoint(mock_engine):
    """Verify GET /health returns lightweight status: ok without external dependencies."""
    app = create_app(mock_engine)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        resp_v1 = await ac.get("/api/v1/health")
        assert resp_v1.status_code == 200
        assert resp_v1.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_endpoint_healthy(mock_engine):
    """Verify GET /ready returns ready: true when engine is running, connected, and synchronized."""
    app = create_app(mock_engine)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is True
        assert data["engine"] == "RUNNING"
        assert data["exchange"] == "AVAILABLE"
        assert data["reconciliation"] == "SYNCHRONIZED"


@pytest.mark.asyncio
async def test_ready_endpoint_safe_halt_not_ready(mock_engine):
    """Verify GET /ready returns ready: false when engine is in SAFE_HALT."""
    mock_engine.risk_manager.activate_kill_switch()
    mock_engine._last_reconciliation_result = ReconciliationResult(
        is_synchronized=False,
        status="SAFE_HALT",
        details={"reason": "Position discrepancy"},
    )

    app = create_app(mock_engine)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is False
        assert data["engine"] == "SAFE_HALT"
        assert data["reconciliation"] == "UNSYNCHRONIZED"


@pytest.mark.asyncio
async def test_ready_endpoint_exchange_unavailable_not_ready(mock_engine):
    """Verify GET /ready returns ready: false when exchange is disconnected."""
    mock_engine.delta_adapter._connected = False

    app = create_app(mock_engine)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is False
        assert data["exchange"] == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_postgres_offline_does_not_make_engine_unready(mock_engine):
    """Verify PostgreSQL being unavailable does NOT make the engine unready."""
    mock_engine.db_manager._is_connected = False
    assert mock_engine.get_readiness()["ready"] is True


@pytest.mark.asyncio
async def test_comprehensive_status_response_and_no_secrets(mock_engine):
    """Verify GET /api/v1/status schema and verify no secrets/tokens are exposed."""
    now_iso = datetime.now(timezone.utc).isoformat()
    mock_engine.strategy.current_trade = StrategyTrade(
        strategy_trade_id="STRANGLE_STATUS_TEST",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_STATUS_TEST_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=105.0,
            sl_price=210.0,
            bracket_order_id="BRK_CE_123",
            exchange_sl_active=True,
            status=LegStatus.OPEN,
        ),
        pe_leg=StrategyLeg(
            leg_id="STRANGLE_STATUS_TEST_PE",
            option_type=OptionType.PUT,
            instrument_id="150402",
            symbol="P-BTC-92000-010926",
            strike=92000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=now_iso,
            entry_fill_price=95.0,
            sl_price=190.0,
            bracket_order_id="BRK_PE_456",
            exchange_sl_active=True,
            status=LegStatus.OPEN,
        ),
    )

    app = create_app(mock_engine)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()

        # Check sections
        assert "engine" in data
        assert data["engine"]["status"] == "RUNNING"
        assert data["engine"]["strategy_name"] == "short_strangle"

        assert "exchange" in data
        assert data["exchange"]["rest_connected"] is True

        assert "reconciliation" in data
        assert data["reconciliation"]["is_synchronized"] is True

        assert "database" in data
        assert "watchdog" in data

        assert "current_trade" in data
        ct = data["current_trade"]
        assert ct["trade_id"] == "STRANGLE_STATUS_TEST"
        assert ct["ce_symbol"] == "C-BTC-98000-010926"
        assert ct["ce_entry_price"] == 105.0
        assert ct["ce_sl_price"] == 210.0
        assert ct["ce_native_bracket_active"] is True
        assert ct["ce_bracket_order_id"] == "BRK_CE_123"

        # Security check: verify no secrets appear anywhere in payload
        payload_str = str(data)
        assert "mock_secret_key" not in payload_str
        assert "mock_secret_password" not in payload_str


@pytest.mark.asyncio
async def test_watchdog_heartbeat_updates(mock_engine):
    """Verify timer tick updates watchdog heartbeat and loop timestamps."""
    initial_heartbeat = mock_engine.last_heartbeat_time
    now = datetime.now(timezone.utc)

    await mock_engine._on_timer_tick(now)
    assert mock_engine.last_heartbeat_time >= initial_heartbeat
    assert mock_engine.last_loop_time is not None


@pytest.mark.asyncio
async def test_alert_service_deduplication():
    """Verify that identical alerts within cooldown window are deduplicated."""
    settings = Settings(
        alert_cooldown_seconds=300,
        telegram_enabled=False,
    )
    service = AlertService(settings=settings)

    # 1. First alert sent
    sent1 = await service.send(
        severity=AlertSeverity.WARNING,
        event="WS_STALE",
        message="Delta WebSocket stale for 30 seconds.",
    )
    assert sent1 is True
    assert len(service.get_recent_alerts()) == 1

    # 2. Duplicate alert immediately after -> suppressed
    sent2 = await service.send(
        severity=AlertSeverity.WARNING,
        event="WS_STALE",
        message="Delta WebSocket stale for 30 seconds.",
    )
    assert sent2 is False
    assert len(service.get_recent_alerts()) == 1

    # 3. State transition / new event -> sent
    sent3 = await service.send(
        severity=AlertSeverity.SUCCESS,
        event="WS_RECOVERED",
        message="Delta WebSocket connection recovered.",
    )
    assert sent3 is True
    assert len(service.get_recent_alerts()) == 2


@pytest.mark.asyncio
async def test_alert_service_telegram_disabled_behavior():
    """Verify AlertService operates smoothly when Telegram is disabled."""
    settings = Settings(telegram_enabled=False)
    service = AlertService(settings=settings)

    sent = await service.send(
        severity=AlertSeverity.CRITICAL,
        event="SAFE_HALT",
        message="Test alert with telegram disabled",
    )
    assert sent is True


@pytest.mark.asyncio
async def test_alert_service_telegram_failure_isolation():
    """Verify that Telegram delivery exceptions are caught and never crash the process."""
    settings = Settings(
        telegram_enabled=True,
        telegram_bot_token="fake_bot_token",
        telegram_chat_id="fake_chat_id",
    )
    service = AlertService(settings=settings)

    with patch("httpx.AsyncClient.post", side_effect=Exception("Connection timeout")):
        # Must return True without raising exception
        sent = await service.send(
            severity=AlertSeverity.CRITICAL,
            event="SAFE_HALT",
            message="Test telegram error isolation",
            force=True,
        )
        assert sent is True


@pytest.mark.asyncio
async def test_missing_bracket_sl_critical_alert(mock_engine):
    """Verify reconciler generates CRITICAL alert when an active strategy leg lacks native SL."""
    from src.core.models.position import Position
    mock_engine.delta_adapter.positions = [
        Position(
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            size=-1.0,
            entry_price=100.0,
        )
    ]

    mock_engine.strategy.current_trade = StrategyTrade(
        strategy_trade_id="STRANGLE_NO_BRK",
        strategy_name="short_strangle",
        trade_date="2026-09-01",
        state=StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id="STRANGLE_NO_BRK_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date="2026-09-01",
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=datetime.now(timezone.utc).isoformat(),
            entry_fill_price=100.0,
            sl_price=200.0,
            bracket_order_id=None,  # Missing bracket!
            exchange_sl_active=False,
            status=LegStatus.OPEN,
        ),
    )

    mock_engine.delta_adapter.create_bracket_order = AsyncMock(side_effect=Exception("Delta bracket creation failed"))

    await mock_engine.reconcile_state()
    alerts = mock_engine.alert_service.get_recent_alerts()
    missing_brk_alerts = [a for a in alerts if a["event"] == "MISSING_BRACKET_SL"]
    assert len(missing_brk_alerts) >= 1
    assert missing_brk_alerts[0]["severity"] == "CRITICAL"



