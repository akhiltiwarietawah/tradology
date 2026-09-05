"""Tests for FastAPI control and monitoring endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport
from src.api.app import create_app
from src.engine import TradingEngine
from src.config.settings import Settings, Environment


@pytest.mark.asyncio
async def test_fastapi_endpoints(tmp_path, mock_exchange):
    settings = Settings(
        delta_env=Environment.TESTNET,
        delta_testnet_api_key="test_key",
        delta_testnet_api_secret="test_sec",
        data_dir=str(tmp_path / "data"),
        logs_dir=str(tmp_path / "logs"),
        state_file=str(tmp_path / "data" / "state.json"),
    )
    engine = TradingEngine(settings=settings)
    engine.delta_adapter = mock_exchange
    engine.exchange_service.register_adapter(mock_exchange)
    engine.execution_engine.exchange = mock_exchange
    engine.strategy.exchange = mock_exchange
    engine.reconciler.exchange = mock_exchange

    app = create_app(engine)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Status endpoint
        resp = await ac.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["environment"] == "TESTNET"
        assert data["strategy"] == "short_strangle"

        # 2. Trades endpoint
        resp2 = await ac.get("/api/v1/trades")
        assert resp2.status_code == 200
        assert "current_trade" in resp2.json()

        # 3. Performance endpoint
        resp_perf = await ac.get("/api/v1/performance")
        assert resp_perf.status_code == 200
        perf_data = resp_perf.json()
        assert "summary" in perf_data
        assert "drawdown" in perf_data
        assert "daily" in perf_data
        assert "monthly" in perf_data
        assert "daily_pnl" in perf_data
        assert "monthly_pnl" in perf_data

        # 3b. Performance with filters
        resp_perf_filtered = await ac.get("/api/v1/performance?from_date=2026-09-01&to_date=2026-09-30&strategy_name=short_strangle")
        assert resp_perf_filtered.status_code == 200
        filtered_data = resp_perf_filtered.json()
        assert filtered_data["period"]["from"] == "2026-09-01"
        assert filtered_data["period"]["to"] == "2026-09-30"

        # 4. Kill-switch endpoint
        resp3 = await ac.post("/api/v1/kill-switch")
        assert resp3.status_code == 200
        assert resp3.json()["status"] == "KILL_SWITCH_ACTIVATED"
        assert engine.risk_manager.is_kill_switch_active is True

        # 5. Reconcile endpoint
        resp4 = await ac.post("/api/v1/reconcile")
        assert resp4.status_code == 200
        assert "is_synchronized" in resp4.json()

        # 6. Account balances endpoint
        resp_bal = await ac.get("/api/v1/account/balances")
        assert resp_bal.status_code == 200
        bal_data = resp_bal.json()
        assert "balances" in bal_data
        assert "USD" in bal_data["balances"]

