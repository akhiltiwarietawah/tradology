"""Configuration & Settings Management supporting Single .env for Testnet and Live."""

import os
from enum import Enum
from pathlib import Path
from typing import Optional
from datetime import datetime, time
import pytz
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config.constants import (
    IST_TIMEZONE,
    TESTNET_REST_URL,
    TESTNET_WS_URL,
    LIVE_REST_URL,
    LIVE_WS_URL,
)


class Environment(str, Enum):
    TESTNET = "testnet"
    LIVE = "live"


class EmergencyPolicy(str, Enum):
    UNWIND_FILLED_LEG = "UNWIND_FILLED_LEG"


class Settings(BaseSettings):
    # Active Environment Selector (Default: TESTNET)
    delta_env: Environment = Field(
        default=Environment.TESTNET,
        description="Active environment: 'testnet' or 'live'. Default is strictly testnet.",
    )

    # Testnet Configuration
    delta_testnet_api_key: str = Field(default="", description="Delta India Testnet API Key")
    delta_testnet_api_secret: str = Field(default="", description="Delta India Testnet API Secret")
    delta_testnet_rest_url: str = Field(default=TESTNET_REST_URL, description="Delta India Testnet REST URL")
    delta_testnet_ws_url: str = Field(default=TESTNET_WS_URL, description="Delta India Testnet WebSocket URL")

    # Live Configuration
    delta_live_api_key: str = Field(default="", description="Delta India Live API Key")
    delta_live_api_secret: str = Field(default="", description="Delta India Live API Secret")
    delta_live_rest_url: str = Field(default=LIVE_REST_URL, description="Delta India Live REST URL")
    delta_live_ws_url: str = Field(default=LIVE_WS_URL, description="Delta India Live WebSocket URL")

    # Strategy Parameters
    strategy: str = Field(default="short_strangle", description="Strategy identifier")
    underlying: str = Field(default="BTC", description="Underlying asset (e.g. BTC)")
    entry_time_ist: str = Field(default="09:00:00", description="Strategy entry time (HH:MM:SS in IST)")
    entry_window_minutes: int = Field(default=15, description="Entry window duration in minutes")
    exit_time_ist: str = Field(default="17:15:00", description="Forced square-off time (HH:MM:SS in IST)")
    target_premium: float = Field(default=100.0, description="Target premium per leg in USD")
    premium_tolerance_usd: float = Field(default=30.0, description="Acceptable tolerance in USD")
    order_quantity: float = Field(
        default=1.0,
        description="Quantity in contracts (1 contract = 0.001 BTC on Delta India)",
    )
    sl_percentage: float = Field(default=1.0, description="Stop loss percentage (1.0 = 100% loss / 2x entry)")
    target_price: Optional[float] = Field(
        default=5.0,
        description="Take profit target price per contract in USD for exchange-side bracket TP (None or <=0 to disable)",
    )

    # Two-Leg Entry Safety & Emergency Policy
    two_leg_entry_timeout_seconds: float = Field(
        default=10.0,
        description="Timeout in seconds to confirm 2nd leg entry before emergency unwind",
    )
    two_leg_emergency_policy: EmergencyPolicy = Field(
        default=EmergencyPolicy.UNWIND_FILLED_LEG,
        description="Emergency policy if one leg fills and other fails: UNWIND_FILLED_LEG",
    )

    # Risk Management & Kill Switch
    max_daily_loss_pct: Optional[float] = Field(
        default=2.1,
        description="Maximum cumulative daily loss as multiple/percentage of initial entry premium (e.g. 2.1 = 210%) before full exit & halt",
    )
    max_daily_loss_usd: float = Field(
        default=500.0,
        description="Fallback maximum cumulative daily loss (realized + unrealized) in USD before full exit & halt",
    )
    kill_switch: bool = Field(default=False, description="Emergency kill switch: when True, prevents any new orders")
    dry_run: bool = Field(default=False, description="Dry-run simulation mode")

    # FastAPI Server & Operational Settings
    server_host: str = Field(default="0.0.0.0", description="FastAPI server host")
    server_port: int = Field(default=8000, description="FastAPI server port")
    log_level: str = Field(default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR")
    data_dir: str = Field(default="data", description="Directory for persistent state and trade history")
    state_file: Optional[str] = Field(default=None, description="Path to state persistence JSON file")
    logs_dir: str = Field(default="logs", description="Directory for log files")
    ws_reconnect_max_attempts: int = Field(default=10, description="Max WS reconnection attempts before alerting")
    ws_reconnect_base_delay_seconds: float = Field(default=2.0, description="Base backoff delay for WS reconnect")
    rest_request_timeout_seconds: float = Field(default=10.0, description="REST API request timeout in seconds")
    reconciliation_interval_seconds: float = Field(
        default=30.0,
        description="Interval in seconds for periodic state reconciliation",
    )

    # Database Configuration (PostgreSQL)
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_db: str = Field(default="crypto_trading", description="PostgreSQL database name")
    postgres_user: str = Field(default="postgres", description="PostgreSQL username")
    postgres_password: str = Field(default="postgres", description="PostgreSQL password")
    db_pool_size: int = Field(default=5, description="Database connection pool size")
    db_max_overflow: int = Field(default=10, description="Database connection pool max overflow")
    db_timeout_seconds: float = Field(default=5.0, description="Database query timeout in seconds")
    db_enabled: bool = Field(default=True, description="Enable historical database persistence")

    # Monitoring & Alert Configuration
    telegram_enabled: bool = Field(default=False, description="Enable Telegram alert notifications")
    telegram_bot_token: Optional[str] = Field(default=None, description="Telegram Bot Token (never exposed)")
    telegram_chat_id: Optional[str] = Field(default=None, description="Telegram Chat ID")
    alert_cooldown_seconds: int = Field(default=300, description="Deduplication cooldown window in seconds")

    # API Security, Authentication & Abuse Protection
    api_auth_enabled: bool = Field(default=False, description="Enable API key authentication on protected routes")
    dashboard_api_key: Optional[str] = Field(default=None, description="Secret API key required for protected endpoints (X-API-Key or Bearer token)")
    cors_allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="Comma-separated list of allowed CORS origins",
    )
    rate_limit_per_minute: int = Field(default=120, description="Max API requests per minute per IP")


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("delta_env", mode="before")
    @classmethod
    def validate_delta_env(cls, v):
        if isinstance(v, str):
            v_lower = v.strip().lower()
            if v_lower in ("testnet", "sandbox", "demo"):
                return Environment.TESTNET
            elif v_lower in ("live", "prod", "production"):
                return Environment.LIVE
            raise ValueError(f"Invalid DELTA_ENV: {v}. Must be 'testnet' or 'live'.")
        return v

    @model_validator(mode="after")
    def populate_and_validate_active_env(self):
        # Set state file path if not provided
        if not self.state_file:
            env_suffix = "live" if self.delta_env == Environment.LIVE else "testnet"
            self.state_file = f"{self.data_dir}/trade_state_{env_suffix}.json"

        # Ensure LIVE environment requires valid credentials unless dry_run is true
        if self.delta_env == Environment.LIVE and not self.dry_run:
            if not self.delta_live_api_key or not self.delta_live_api_secret:
                raise ValueError(
                    "DELTA_ENV is set to 'live' but DELTA_LIVE_API_KEY or DELTA_LIVE_API_SECRET is missing. "
                    "LIVE environment requires valid credentials or DRY_RUN=true."
                )

        return self

    @property
    def async_db_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def sync_db_url(self) -> str:
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def active_api_key(self) -> str:
        return self.delta_live_api_key if self.delta_env == Environment.LIVE else self.delta_testnet_api_key

    @property
    def active_api_secret(self) -> str:
        return self.delta_live_api_secret if self.delta_env == Environment.LIVE else self.delta_testnet_api_secret

    @property
    def active_rest_url(self) -> str:
        return self.delta_live_rest_url if self.delta_env == Environment.LIVE else self.delta_testnet_rest_url

    @property
    def active_ws_url(self) -> str:
        return self.delta_live_ws_url if self.delta_env == Environment.LIVE else self.delta_testnet_ws_url

    def get_parsed_entry_time(self) -> time:
        return datetime.strptime(self.entry_time_ist, "%H:%M:%S").time()

    def get_parsed_exit_time(self) -> time:
        return datetime.strptime(self.exit_time_ist, "%H:%M:%S").time()



def get_settings() -> Settings:
    """Retrieve settings instance loaded from single .env."""
    return Settings()
