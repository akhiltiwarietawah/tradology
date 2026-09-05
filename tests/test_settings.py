"""Tests for single .env settings and environment switching."""

import pytest
from src.config.settings import Settings, Environment


def test_default_environment_is_testnet():
    s = Settings(
        _env_file=None,
        delta_testnet_api_key="test_key",
        delta_testnet_api_secret="test_sec",
    )
    assert s.delta_env == Environment.TESTNET
    assert s.active_api_key == "test_key"
    assert s.active_api_secret == "test_sec"
    assert "testnet" in s.active_rest_url.lower()


def test_switch_to_live_environment():
    s = Settings(
        _env_file=None,
        delta_env="live",
        delta_testnet_api_key="test_key",
        delta_testnet_api_secret="test_sec",
        delta_live_api_key="live_key",
        delta_live_api_secret="live_sec",
    )
    assert s.delta_env == Environment.LIVE
    assert s.active_api_key == "live_key"
    assert s.active_api_secret == "live_sec"
    assert "api.india.delta.exchange" in s.active_rest_url


def test_live_without_credentials_raises_error():
    with pytest.raises(ValueError, match="DELTA_ENV is set to 'live' but DELTA_LIVE_API_KEY"):
        Settings(
            _env_file=None,
            delta_env="live",
            delta_live_api_key="",
            delta_live_api_secret="",
            dry_run=False,
        )


def test_live_dry_run_allowed_without_credentials():
    s = Settings(
        _env_file=None,
        delta_env="live",
        delta_live_api_key="",
        delta_live_api_secret="",
        dry_run=True,
    )
    assert s.delta_env == Environment.LIVE
    assert s.dry_run is True


def test_settings_inlined_defaults():
    s = Settings(_env_file=None, delta_testnet_api_key="k", delta_testnet_api_secret="s")
    assert s.underlying == "BTC"
    assert s.entry_time_ist == "09:00:00"
    assert s.entry_window_minutes == 15
    assert s.exit_time_ist == "17:15:00"
    assert s.target_premium == 100.0
    assert s.premium_tolerance_usd == 30.0
    assert s.order_quantity == 1.0
    assert s.sl_percentage == 1.0
    assert s.max_daily_loss_pct == 2.1
    assert s.max_daily_loss_usd == 500.0
    assert s.two_leg_entry_timeout_seconds == 10.0
    assert s.reconciliation_interval_seconds == 30.0


def test_settings_propagation_to_engine_components():
    from src.engine import TradingEngine
    from datetime import time

    custom_settings = Settings(
        _env_file=None,
        delta_env="testnet",
        delta_testnet_api_key="custom_k",
        delta_testnet_api_secret="custom_s",
        underlying="BTC",
        target_premium=120.0,
        premium_tolerance_usd=25.0,
        order_quantity=5.0,
        sl_percentage=0.8,
        entry_time_ist="09:15:00",
        entry_window_minutes=10,
        exit_time_ist="16:45:00",
        max_daily_loss_pct=2.5,
        max_daily_loss_usd=750.0,
        two_leg_entry_timeout_seconds=15.0,
        reconciliation_interval_seconds=45.0,
        kill_switch=False,
        dry_run=True,
        db_enabled=False,
    )

    engine = TradingEngine(settings=custom_settings)

    # 1. Risk Manager
    assert engine.risk_manager.max_daily_loss_pct == 2.5
    assert engine.risk_manager.max_daily_loss_usd == 750.0

    # 2. Execution Engine
    assert engine.execution_engine.entry_timeout_seconds == 15.0

    # 3. Strategy & ShortStrangleConfig
    assert engine.strategy.config.underlying == "BTC"
    assert engine.strategy.config.target_premium == 120.0
    assert engine.strategy.config.premium_tolerance_usd == 25.0
    assert engine.strategy.config.quantity == 5.0
    assert engine.strategy.config.sl_percentage == 0.8
    assert engine.strategy.config.entry_time == time(9, 15, 0)
    assert engine.strategy.config.entry_window_minutes == 10
    assert engine.strategy.config.exit_time == time(16, 45, 0)
    assert engine.strategy.config.max_daily_loss_usd == 750.0

