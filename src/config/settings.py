"""Configuration & Settings Management supporting Single .env for Testnet and Live."""

import os
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from src.strategies.renko_ichimoku.instance_config import RenkoInstanceConfig
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
    credentials_encryption_key: Optional[str] = Field(
        default=None,
        description="Fernet key for encrypting user exchange credentials at rest",
    )
    cors_allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="Comma-separated list of allowed CORS origins",
    )
    rate_limit_per_minute: int = Field(default=120, description="Max API requests per minute per IP")
    platform_sync_interval_seconds: int = Field(default=60, description="Background exchange account sync interval")
    platform_runtime_execution_enabled: bool = Field(
        default=False,
        description="Master switch for multi-user platform runtime live execution. Keep false until verified.",
    )
    platform_delta_live_enabled: bool = Field(
        default=False,
        description="Allow platform runtime to submit live orders to Delta India.",
    )
    platform_live_trading_enabled: bool = Field(
        default=False,
        description="Global kill switch for all platform live order submission.",
    )
    platform_live_dry_run_enabled: bool = Field(
        default=True,
        description="When LIVE mode requested but live flags off, use LIVE_DRY_RUN (log WOULD EXECUTE).",
    )
    platform_runtime_heartbeat_seconds: int = Field(default=15, description="Runtime heartbeat interval")
    platform_runtime_worker_id: str = Field(default="api-worker-1", description="Worker identity for runtime coordination")
    platform_max_live_test_quantity: Optional[float] = Field(
        default=1.0,
        description="Maximum order quantity for controlled LIVE test (backend enforced). None disables cap.",
    )
    platform_max_live_test_notional: Optional[float] = Field(
        default=500.0,
        description="Maximum notional USD for controlled LIVE test orders. None disables cap.",
    )

    # Independent strategy enablement (existing BTC short strangle vs ETH Renko Ichimoku)
    existing_strategy_enabled: bool = Field(
        default=True,
        description="Enable the existing BTC 0DTE short-strangle strategy. Default true (unchanged production).",
    )
    existing_strategy_account: str = Field(
        default="primary",
        description="Account label for the short-strangle strategy. Optional keys in EXISTING_STRATEGY_API_* when set.",
    )
    existing_strategy_api_key: str = Field(
        default="",
        description="Optional Delta API key for EXISTING_STRATEGY_ACCOUNT. Uses DELTA_* when empty.",
    )
    existing_strategy_api_secret: str = Field(
        default="",
        description="Optional Delta API secret for EXISTING_STRATEGY_ACCOUNT.",
    )
    renko_ichimoku_strategy_enabled: bool = Field(
        default=False,
        description="Enable the independent ETHUSDT Renko+Ichimoku strategy. Default false.",
    )
    renko_ichimoku_account: str = Field(
        default="renko",
        description="Account label for Renko Ichimoku. If different from EXISTING_STRATEGY_ACCOUNT, use RENKO_ICHIMOKU_* keys.",
    )
    renko_ichimoku_api_key: str = Field(
        default="",
        description="Optional API key for the Renko account when it differs from the existing strategy account.",
    )
    renko_ichimoku_api_secret: str = Field(
        default="",
        description="Optional API secret for the Renko account when it differs from the existing strategy account.",
    )
    renko_ichimoku_symbol: str = Field(
        default="ETHUSDT",
        description="Delta perpetual symbol for the ETH Renko instance (ETHUSDT / ETHUSD).",
    )
    renko_ichimoku_box_size: float = Field(
        default=15.0,
        description="Fixed USD Renko box size for the ETH instance.",
    )
    renko_ichimoku_position_size: float = Field(
        default=0.0,
        description="ETH Renko order size in contracts. Independent of ORDER_QUANTITY. 0 = no orders.",
    )
    renko_ichimoku_sol_enabled: bool = Field(
        default=False,
        description="Enable the SOL Renko+Ichimoku instance alongside ETH when RENKO_ICHIMOKU_STRATEGY_ENABLED=true.",
    )
    renko_ichimoku_sol_symbol: str = Field(
        default="SOLUSDT",
        description="Delta perpetual symbol for the SOL Renko instance.",
    )
    renko_ichimoku_sol_box_size: float = Field(
        default=0.42,
        description="Fixed USD Renko box size for SOL (~0.5% at ~$84).",
    )
    renko_ichimoku_sol_position_size: float = Field(
        default=0.0,
        description="SOL Renko order size in contracts. 0 = signals only.",
    )
    renko_ichimoku_sol_state_file: Optional[str] = Field(
        default=None,
        description="Independent state file for the SOL Renko instance.",
    )
    renko_ichimoku_sol_flatten: bool = Field(
        default=False,
        description="Startup flatten for the SOL Renko instrument only.",
    )
    renko_ichimoku_xrp_enabled: bool = Field(
        default=False,
        description="Enable the XRP Renko+Ichimoku instance alongside ETH/SOL.",
    )
    renko_ichimoku_xrp_symbol: str = Field(
        default="XRPUSDT",
        description="Delta perpetual symbol for the XRP Renko instance.",
    )
    renko_ichimoku_xrp_box_size: float = Field(
        default=0.003,
        description="Fixed USD Renko box size for XRP (~0.5% at ~$0.60).",
    )
    renko_ichimoku_xrp_position_size: float = Field(
        default=0.0,
        description="XRP Renko order size in contracts. 0 = signals only.",
    )
    renko_ichimoku_xrp_state_file: Optional[str] = Field(
        default=None,
        description="Independent state file for the XRP Renko instance.",
    )
    renko_ichimoku_xrp_flatten: bool = Field(
        default=False,
        description="Startup flatten for the XRP Renko instrument only.",
    )
    renko_ichimoku_candle_resolution: str = Field(
        default="15m",
        description="Closed-candle Close feed used to confirm Renko bricks. Must match the intended chart interval.",
    )
    renko_ichimoku_state_file: Optional[str] = Field(
        default=None,
        description="Independent state file for Renko Ichimoku. Never the short-strangle state file.",
    )
    renko_ichimoku_flatten: bool = Field(
        default=False,
        description="If true at startup, send one reduce-only flatten of the Renko instrument then halt. Leave false during normal trading.",
    )
    renko_ichimoku_position_sizing_mode: str = Field(
        default="fixed",
        description="Renko sizing: 'fixed' = RENKO_*_POSITION_SIZE contracts; 'dynamic' = margin = sizing_equity × margin_pct × leverage.",
    )
    renko_ichimoku_sizing_base_usd: float = Field(
        default=50.0,
        description="Starting virtual sizing equity (USD) per coin when state has no sizing_equity yet.",
    )
    renko_ichimoku_margin_pct: float = Field(
        default=0.25,
        description="Dynamic mode: margin per entry = sizing_equity × this value (e.g. 0.25 = 25%).",
    )
    renko_ichimoku_leverage: float = Field(
        default=10.0,
        description="Dynamic mode: notional = margin × leverage (e.g. 10x).",
    )
    renko_ichimoku_profit_retain_pct: float = Field(
        default=0.5,
        description=(
            "Dynamic mode: fraction of realized profit kept in sizing_equity after each win "
            "(0.5 = simulate 50% withdraw; loss always applied in full)."
        ),
    )
    renko_ichimoku_alts_enabled: str = Field(
        default="",
        description=(
            "Comma-separated extra Renko instances from the asset registry: "
            "btc,bnb,doge,ada,trx,avax,link,hype. Each gets its own state file and strategy code."
        ),
    )
    renko_ichimoku_split_margin_across_book: bool = Field(
        default=False,
        description=(
            "When true, divide RENKO_ICHIMOKU_MARGIN_PCT by the number of enabled Renko instances "
            "so one account is not sized as if each asset may use a full 25% slice simultaneously."
        ),
    )


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

        env_suffix = "live" if self.delta_env == Environment.LIVE else "testnet"
        if not self.renko_ichimoku_state_file:
            self.renko_ichimoku_state_file = f"{self.data_dir}/renko_ichimoku_eth_state_{env_suffix}.json"
        if not self.renko_ichimoku_sol_state_file:
            self.renko_ichimoku_sol_state_file = f"{self.data_dir}/renko_ichimoku_sol_state_{env_suffix}.json"
        if not self.renko_ichimoku_xrp_state_file:
            self.renko_ichimoku_xrp_state_file = f"{self.data_dir}/renko_ichimoku_xrp_state_{env_suffix}.json"

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

    def uses_separate_renko_account(self) -> bool:
        return (
            self.has_any_renko_enabled()
            and self.renko_ichimoku_account.strip().lower() != self.existing_strategy_account.strip().lower()
        )

    def existing_strategy_api_credentials(self) -> tuple[str, str]:
        """Short-strangle account credentials. Falls back to active DELTA_* keys."""
        if self.existing_strategy_api_key and self.existing_strategy_api_secret:
            return self.existing_strategy_api_key, self.existing_strategy_api_secret
        return self.active_api_key, self.active_api_secret

    def renko_uses_shared_primary_adapter(self) -> bool:
        """
        Renko trades on DELTA_LIVE_* / DELTA_TESTNET_* without RENKO_ICHIMOKU_API_*.

        True when account labels match, or when strangle is off and Renko keys are not set
        (primary Delta keys are the Renko trader's account).
        """
        if not self.uses_separate_renko_account():
            return True
        if self.renko_ichimoku_api_key and self.renko_ichimoku_api_secret:
            return False
        if not self.existing_strategy_enabled:
            return True
        return False

    def renko_api_credentials(self) -> tuple[str, str]:
        if not self.renko_uses_shared_primary_adapter():
            return self.renko_ichimoku_api_key, self.renko_ichimoku_api_secret
        return self.active_api_key, self.active_api_secret

    def has_any_renko_enabled(self) -> bool:
        from src.strategies.renko_ichimoku.asset_registry import parse_enabled_alt_ids

        return bool(
            self.renko_ichimoku_strategy_enabled
            or self.renko_ichimoku_sol_enabled
            or self.renko_ichimoku_xrp_enabled
            or parse_enabled_alt_ids(self.renko_ichimoku_alts_enabled)
        )

    def _renko_env_float(self, env_key: str, default: float) -> float:
        raw = os.getenv(env_key)
        if raw is None or not str(raw).strip():
            return float(default)
        return float(raw)

    def _renko_env_str(self, env_key: str, default: str) -> str:
        raw = os.getenv(env_key)
        if raw is None or not str(raw).strip():
            return default
        return str(raw).strip()

    def _sizing_base_for_instance(self, instance_id: str) -> float:
        prefix = instance_id.upper()
        return self._renko_env_float(
            f"RENKO_ICHIMOKU_{prefix}_SIZING_BASE_USD",
            self.renko_ichimoku_sizing_base_usd,
        )

    def _renko_credentials_for_instance(self, instance_id: str) -> tuple[str, str, str]:
        """Return (account_label, api_key, api_secret) for one Renko instance."""
        prefix = instance_id.upper()
        account = self._renko_env_str(f"RENKO_ICHIMOKU_{prefix}_ACCOUNT", self.renko_ichimoku_account)
        inst_key = os.getenv(f"RENKO_ICHIMOKU_{prefix}_API_KEY")
        inst_secret = os.getenv(f"RENKO_ICHIMOKU_{prefix}_API_SECRET")
        if inst_key and inst_secret and str(inst_key).strip() and str(inst_secret).strip():
            return account, str(inst_key).strip(), str(inst_secret).strip()
        default_key, default_secret = self.renko_api_credentials()
        if default_key and default_secret:
            return account, default_key, default_secret
        if self.renko_uses_shared_primary_adapter():
            return account, self.active_api_key, self.active_api_secret
        return account, "", ""

    def _renko_state_path(self, instance_id: str) -> str:
        env_suffix = "live" if self.delta_env == Environment.LIVE else "testnet"
        override = os.getenv(f"RENKO_ICHIMOKU_{instance_id.upper()}_STATE_FILE")
        if override and str(override).strip():
            return str(override).strip()
        return f"{self.data_dir}/renko_ichimoku_{instance_id}_state_{env_suffix}.json"

    def renko_state_file_candidates(self) -> List[str]:
        """Default state paths for ETH/SOL/XRP and every registry alt (warning scan)."""
        from src.strategies.renko_ichimoku.asset_registry import RENKO_ALT_REGISTRY

        env_suffix = "live" if self.delta_env == Environment.LIVE else "testnet"
        paths = [
            self.renko_ichimoku_state_file
            or f"{self.data_dir}/renko_ichimoku_eth_state_{env_suffix}.json",
            self.renko_ichimoku_sol_state_file
            or f"{self.data_dir}/renko_ichimoku_sol_state_{env_suffix}.json",
            self.renko_ichimoku_xrp_state_file
            or f"{self.data_dir}/renko_ichimoku_xrp_state_{env_suffix}.json",
        ]
        for alt_id in RENKO_ALT_REGISTRY:
            paths.append(self._renko_state_path(alt_id))
        seen: set[str] = set()
        out: List[str] = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def all_renko_state_files(self) -> List[str]:
        """State paths for enabled Renko instances."""
        return [c.state_file for c in self.renko_instance_configs()]

    def renko_instance_configs(self) -> List["RenkoInstanceConfig"]:
        """Build enabled Renko instances (ETH / SOL / XRP + registry alts)."""
        from dataclasses import replace

        from src.strategies.renko_ichimoku.asset_registry import RENKO_ALT_REGISTRY, parse_enabled_alt_ids
        from src.strategies.renko_ichimoku.instance_config import (
            RENKO_ETH_STRATEGY_CODE,
            RENKO_SOL_STRATEGY_CODE,
            RENKO_XRP_STRATEGY_CODE,
            RenkoInstanceConfig,
        )

        configs: List[RenkoInstanceConfig] = []
        sizing_mode = (self.renko_ichimoku_position_sizing_mode or "fixed").strip().lower()
        def sizing_common(instance_id: str) -> dict:
            return {
                "position_sizing_mode": sizing_mode,
                "sizing_base_usd": self._sizing_base_for_instance(instance_id),
                "margin_pct": self.renko_ichimoku_margin_pct,
                "leverage": self.renko_ichimoku_leverage,
                "profit_retain_pct": self.renko_ichimoku_profit_retain_pct,
            }

        if self.renko_ichimoku_strategy_enabled:
            configs.append(
                RenkoInstanceConfig(
                    instance_id="eth",
                    strategy_code=RENKO_ETH_STRATEGY_CODE,
                    symbol=self.renko_ichimoku_symbol,
                    box_size=self.renko_ichimoku_box_size,
                    position_size=self.renko_ichimoku_position_size,
                    state_file=self.renko_ichimoku_state_file or self._renko_state_path("eth"),
                    candle_resolution=self.renko_ichimoku_candle_resolution,
                    flatten=self.renko_ichimoku_flatten,
                    **sizing_common("eth"),
                )
            )
        if self.renko_ichimoku_sol_enabled:
            configs.append(
                RenkoInstanceConfig(
                    instance_id="sol",
                    strategy_code=RENKO_SOL_STRATEGY_CODE,
                    symbol=self.renko_ichimoku_sol_symbol,
                    box_size=self.renko_ichimoku_sol_box_size,
                    position_size=self.renko_ichimoku_sol_position_size,
                    state_file=self.renko_ichimoku_sol_state_file or self._renko_state_path("sol"),
                    candle_resolution=self.renko_ichimoku_candle_resolution,
                    flatten=self.renko_ichimoku_sol_flatten,
                    **sizing_common("sol"),
                )
            )
        if self.renko_ichimoku_xrp_enabled:
            configs.append(
                RenkoInstanceConfig(
                    instance_id="xrp",
                    strategy_code=RENKO_XRP_STRATEGY_CODE,
                    symbol=self.renko_ichimoku_xrp_symbol,
                    box_size=self.renko_ichimoku_xrp_box_size,
                    position_size=self.renko_ichimoku_xrp_position_size,
                    state_file=self.renko_ichimoku_xrp_state_file or self._renko_state_path("xrp"),
                    candle_resolution=self.renko_ichimoku_candle_resolution,
                    flatten=self.renko_ichimoku_xrp_flatten,
                    **sizing_common("xrp"),
                )
            )
        for alt_id in parse_enabled_alt_ids(self.renko_ichimoku_alts_enabled):
            spec = RENKO_ALT_REGISTRY[alt_id]
            prefix = alt_id.upper()
            symbol = self._renko_env_str(f"RENKO_ICHIMOKU_{prefix}_SYMBOL", spec.default_symbol)
            box = self._renko_env_float(f"RENKO_ICHIMOKU_{prefix}_BOX_SIZE", spec.default_box_usd)
            pos_raw = os.getenv(f"RENKO_ICHIMOKU_{prefix}_POSITION_SIZE")
            position_size = float(pos_raw) if pos_raw is not None and str(pos_raw).strip() else 0.0
            flatten_raw = os.getenv(f"RENKO_ICHIMOKU_{prefix}_FLATTEN", "").strip().lower()
            flatten = flatten_raw in ("1", "true", "yes")
            configs.append(
                RenkoInstanceConfig(
                    instance_id=spec.instance_id,
                    strategy_code=spec.strategy_code,
                    symbol=symbol,
                    box_size=box,
                    position_size=position_size,
                    state_file=self._renko_state_path(spec.instance_id),
                    candle_resolution=self.renko_ichimoku_candle_resolution,
                    flatten=flatten,
                    **sizing_common(alt_id),
                )
            )
        bound: List[RenkoInstanceConfig] = []
        for c in configs:
            acct, key, secret = self._renko_credentials_for_instance(c.instance_id)
            bound.append(replace(c, account_name=acct, api_key=key, api_secret=secret))
        configs = bound
        if self.renko_ichimoku_split_margin_across_book and configs:
            div = max(1, len(configs))
            scaled_margin = float(self.renko_ichimoku_margin_pct) / div
            configs = [replace(c, margin_pct=scaled_margin) for c in configs]
        return configs

    def get_parsed_entry_time(self) -> time:
        return datetime.strptime(self.entry_time_ist, "%H:%M:%S").time()

    def get_parsed_exit_time(self) -> time:
        return datetime.strptime(self.exit_time_ist, "%H:%M:%S").time()



def get_settings() -> Settings:
    """Retrieve settings instance loaded from single .env."""
    return Settings()
