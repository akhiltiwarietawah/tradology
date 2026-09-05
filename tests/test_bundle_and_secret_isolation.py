"""Security Audit & Bundle Secret Isolation Tests (Checkpoint 8.2)."""

import os
import re
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from src.config.settings import Settings, Environment
from src.engine import TradingEngine
from src.api.app import create_app
from tests.conftest import MockExchangeAdapter


def test_api_key_and_secrets_absent_from_client_js_bundles():
    """Verify that no API keys, tokens, or credentials exist in compiled client JS bundles."""
    repo_root = Path(__file__).parent.parent
    chunks_dir = repo_root / "frontend" / ".next" / "static" / "chunks"
    if not chunks_dir.exists():
        pytest.skip("Frontend chunks not built yet - skipping bundle scan")

    sensitive_patterns = [
        re.compile(r"SECURE_DASHBOARD_KEY"),
        re.compile(r"SUPER_SECRET"),
        re.compile(r"FASTAPI_API_KEY"),
        re.compile(r"NEXT_PUBLIC_API_KEY"),
        re.compile(r"delta_testnet_api_secret"),
        re.compile(r"postgres_password"),
        re.compile(r"telegram_bot_token"),
    ]

    for js_file in chunks_dir.rglob("*.js"):
        content = js_file.read_text(encoding="utf-8", errors="ignore")
        for pattern in sensitive_patterns:
            match = pattern.search(content)
            assert match is None, f"Found sensitive token pattern {pattern.pattern} in client bundle {js_file.name}"


def test_no_next_public_secrets_in_env_files():
    """Verify that no secret credentials are assigned to NEXT_PUBLIC_* variables."""
    repo_root = Path(__file__).parent.parent
    frontend_dir = repo_root / "frontend"
    env_files = list(frontend_dir.glob(".env*"))

    for env_file in env_files:
        content = env_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("NEXT_PUBLIC_"):
                var_name, _, val = line.partition("=")
                assert "API_KEY" not in var_name, f"Forbidden NEXT_PUBLIC_API_KEY found in {env_file.name}"
                assert "SECRET" not in var_name, f"Forbidden NEXT_PUBLIC secret found in {env_file.name}"
                assert "PASSWORD" not in var_name, f"Forbidden NEXT_PUBLIC password found in {env_file.name}"


@pytest.mark.asyncio
async def test_fastapi_rejects_direct_unauthenticated_protected_requests(tmp_path):
    """Verify FastAPI rejects all direct anonymous requests to sensitive data."""
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
        dashboard_api_key="SUPER_PRIVATE_FASTAPI_KEY_888",
    )
    engine = TradingEngine(settings=settings)
    mock_adapter = MockExchangeAdapter()
    engine.delta_adapter = mock_adapter
    engine.exchange_service.register_adapter(mock_adapter)
    engine._running = True
    app = create_app(engine)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Sensitive balance endpoint rejected without key
        res = await client.get("/api/v1/account/balances")
        assert res.status_code == 401
        assert "Unauthorized" in res.json().get("detail", "")

        # Reconcile endpoint rejected without key
        res = await client.post("/api/v1/reconcile")
        assert res.status_code == 401

        # Providing valid private key succeeds
        res_auth = await client.get(
            "/api/v1/account/balances",
            headers={"X-API-Key": "SUPER_PRIVATE_FASTAPI_KEY_888"},
        )
        assert res_auth.status_code == 200
