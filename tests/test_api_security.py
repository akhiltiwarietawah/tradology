"""Automated Production API Security Test Suite (Checkpoint 8.1)."""

import pytest
from httpx import AsyncClient, ASGITransport

from src.config.settings import Settings, Environment
from src.engine import TradingEngine
from src.api.app import create_app
from tests.conftest import MockExchangeAdapter


@pytest.fixture
def security_test_setup(tmp_path):
    """Create isolated FastAPI app with authentication enabled."""
    settings = Settings(
        delta_env=Environment.TESTNET,
        kill_switch=False,
        dry_run=False,
        delta_testnet_api_key="mock_secret_key_123",
        delta_testnet_api_secret="SUPER_SECRET_DELTA_TOKEN_ABC",
        postgres_password="SUPER_SECRET_POSTGRES_PASSWORD_XYZ",
        telegram_bot_token="SUPER_SECRET_TELEGRAM_BOT_TOKEN_123",
        data_dir=str(tmp_path / "data"),
        logs_dir=str(tmp_path / "logs"),
        state_file=str(tmp_path / "data" / "trade_state.json"),
        trades_log_file=str(tmp_path / "logs" / "trades.jsonl"),
        database_enabled=False,
        api_auth_enabled=True,
        dashboard_api_key="SECURE_DASHBOARD_KEY_999",
        cors_allowed_origins="http://localhost:3000,http://127.0.0.1:3000",
        rate_limit_per_minute=100,
    )
    engine = TradingEngine(settings=settings)
    mock_adapter = MockExchangeAdapter()
    engine.delta_adapter = mock_adapter
    engine.exchange_service.register_adapter(mock_adapter)
    engine.execution_engine.exchange = mock_adapter
    engine.strategy.exchange = mock_adapter
    engine.reconciler.exchange = mock_adapter
    engine.risk_manager._kill_switch_flag = False
    engine._running = True

    app = create_app(engine)
    return app, engine, settings


@pytest.mark.asyncio
async def test_public_health_and_ready_endpoints_no_auth(security_test_setup):
    """Public health & readiness endpoints are accessible anonymously."""
    app, engine, _ = security_test_setup
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Health check
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}

        # 2. Readiness check
        res = await client.get("/ready")
        assert res.status_code == 200
        data = res.json()
        assert "ready" in data
        assert "reconciliation" in data


@pytest.mark.asyncio
async def test_anonymous_access_to_protected_endpoints_rejected(security_test_setup):
    """Anonymous access to operational endpoints must return HTTP 401."""
    app, _, _ = security_test_setup
    protected_paths = [
        ("GET", "/api/v1/status"),
        ("GET", "/api/v1/trades"),
        ("GET", "/api/v1/performance"),
        ("GET", "/api/v1/account/balances"),
        ("POST", "/api/v1/reconcile"),
        ("POST", "/api/v1/kill-switch"),
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for method, path in protected_paths:
            if method == "GET":
                res = await client.get(path)
            else:
                res = await client.post(path)
            assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}"
            assert "Unauthorized" in res.json().get("detail", "")


@pytest.mark.asyncio
async def test_invalid_api_key_rejected(security_test_setup):
    """Providing wrong API key via header or Bearer token returns HTTP 401."""
    app, _, _ = security_test_setup
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Wrong X-API-Key
        res1 = await client.get("/api/v1/status", headers={"X-API-Key": "WRONG_TOKEN"})
        assert res1.status_code == 401
        assert "Invalid API key" in res1.json()["detail"]

        # Wrong Bearer token
        res2 = await client.get("/api/v1/status", headers={"Authorization": "Bearer WRONG_TOKEN"})
        assert res2.status_code == 401
        assert "Invalid API key" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_authenticated_access_succeeds(security_test_setup):
    """Providing valid API key grants access to protected endpoints."""
    app, _, settings = security_test_setup
    valid_key = settings.dashboard_api_key

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Via X-API-Key header
        res1 = await client.get("/api/v1/status", headers={"X-API-Key": valid_key})
        assert res1.status_code == 200
        assert res1.json()["engine"]["strategy_name"] == "short_strangle"

        # 2. Via Authorization Bearer header
        res2 = await client.get("/api/v1/status", headers={"Authorization": f"Bearer {valid_key}"})
        assert res2.status_code == 200
        assert res2.json()["engine"]["strategy_name"] == "short_strangle"


@pytest.mark.asyncio
async def test_zero_secrets_exposure_in_responses(security_test_setup):
    """Responses must never leak Delta API secrets, DB passwords, or telegram tokens."""
    app, _, settings = security_test_setup
    valid_key = settings.dashboard_api_key

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/status", headers={"X-API-Key": valid_key})
        body_text = res.text

        assert "SUPER_SECRET_DELTA_TOKEN_ABC" not in body_text
        assert "SUPER_SECRET_POSTGRES_PASSWORD_XYZ" not in body_text
        assert "SUPER_SECRET_TELEGRAM_BOT_TOKEN_123" not in body_text
        assert settings.delta_testnet_api_secret not in body_text


@pytest.mark.asyncio
async def test_security_headers_present(security_test_setup):
    """Verify security headers are attached to responses."""
    app, _, _ = security_test_setup
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/health")
        assert res.headers.get("X-Content-Type-Options") == "nosniff"
        assert res.headers.get("X-Frame-Options") == "DENY"
        assert res.headers.get("X-XSS-Protection") == "1; mode=block"
        assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "geolocation=()" in res.headers.get("Permissions-Policy", "")


@pytest.mark.asyncio
async def test_rate_limiting_blocks_abusive_requests(tmp_path):
    """Rate limiter enforces per-IP limits on protected routes while health remains exempt."""
    settings = Settings(
        delta_env=Environment.TESTNET,
        kill_switch=False,
        dry_run=False,
        data_dir=str(tmp_path / "data"),
        logs_dir=str(tmp_path / "logs"),
        state_file=str(tmp_path / "data" / "trade_state.json"),
        trades_log_file=str(tmp_path / "logs" / "trades.jsonl"),
        database_enabled=False,
        api_auth_enabled=True,
        dashboard_api_key="TEST_KEY",
        rate_limit_per_minute=3,  # Strict limit for this test
    )
    engine = TradingEngine(settings=settings)
    mock_adapter = MockExchangeAdapter()
    engine.delta_adapter = mock_adapter
    engine.exchange_service.register_adapter(mock_adapter)
    engine._running = True
    app = create_app(engine)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Send requests up to limit (3 req/min)
        for _ in range(3):
            res = await client.get("/api/v1/status", headers={"X-API-Key": "TEST_KEY"})
            assert res.status_code == 200

        # 4th request exceeds limit -> 429
        rate_limited_res = await client.get("/api/v1/status", headers={"X-API-Key": "TEST_KEY"})
        assert rate_limited_res.status_code == 429
        assert "Too many requests" in rate_limited_res.json()["detail"]
        assert rate_limited_res.headers.get("Retry-After") == "60"

        # Public /health is exempt and must still return 200 OK
        health_res = await client.get("/health")
        assert health_res.status_code == 200


@pytest.mark.asyncio
async def test_trading_engine_unaffected_by_api_auth_failures(security_test_setup):
    """Security rejections on the API layer have zero negative side-effects on engine."""
    app, engine, _ = security_test_setup
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(10):
            await client.get("/api/v1/status", headers={"X-API-Key": "ATTACKER_INVALID_KEY"})

        assert engine._running is True
        assert engine.risk_manager.is_kill_switch_active is False
