"""SQLAlchemy ORM models for the multi-tenant Tradology platform layer."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class PlatformBase(DeclarativeBase):
    pass


class UserModel(PlatformBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    google_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    exchange_accounts: Mapped[list["ExchangeAccountModel"]] = relationship(back_populates="user")
    subscriptions: Mapped[list["SubscriptionModel"]] = relationship(back_populates="user")


class StrategyCatalogModel(PlatformBase):
    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    supported_exchanges: Mapped[dict] = mapped_column(JSONB, default=list)
    markets: Mapped[dict] = mapped_column(JSONB, default=list)
    timeframe: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_profile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    subscriptions: Mapped[list["SubscriptionModel"]] = relationship(back_populates="strategy")


class SubscriptionModel(PlatformBase):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "strategy_id", name="uq_subscriptions_user_strategy"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategies.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    billing_plan: Mapped[str] = mapped_column(String(64), default="free", nullable=False)
    risk_settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    subscribed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["UserModel"] = relationship(back_populates="subscriptions")
    strategy: Mapped["StrategyCatalogModel"] = relationship(back_populates="subscriptions")
    strategy_accounts: Mapped[list["StrategyAccountModel"]] = relationship(back_populates="subscription")


class ExchangeAccountModel(PlatformBase):
    __tablename__ = "exchange_accounts"
    __table_args__ = (UniqueConstraint("user_id", "exchange", "label", name="uq_exchange_accounts_user_exchange_label"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    credentials_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    connection_status: Mapped[str] = mapped_column(String(32), default="disconnected", nullable=False)
    health_status: Mapped[str] = mapped_column(String(32), default="DISCONNECTED", nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    equity: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    available_balance: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    realized_pnl: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    currency: Mapped[str] = mapped_column(String(16), default="USD")
    is_testnet: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trading_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["UserModel"] = relationship(back_populates="exchange_accounts")
    strategy_accounts: Mapped[list["StrategyAccountModel"]] = relationship(back_populates="exchange_account")


class StrategyAccountModel(PlatformBase):
    __tablename__ = "strategy_accounts"
    __table_args__ = (UniqueConstraint("subscription_id", "exchange_account_id", name="uq_strategy_accounts_sub_account"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"))
    exchange_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exchange_accounts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="paused", nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), default="PAPER", nullable=False)
    trading_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    runtime_status: Mapped[str] = mapped_column(String(32), default="STOPPED", nullable=False)
    allocation_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=100.0)
    risk_overrides: Mapped[dict] = mapped_column(JSONB, default=dict)
    runtime_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    subscription: Mapped["SubscriptionModel"] = relationship(back_populates="strategy_accounts")
    exchange_account: Mapped["ExchangeAccountModel"] = relationship(back_populates="strategy_accounts")
    runtime: Mapped["StrategyRuntimeModel | None"] = relationship(back_populates="strategy_account", uselist=False)


class StrategyRuntimeModel(PlatformBase):
    __tablename__ = "strategy_runtime"
    __table_args__ = (UniqueConstraint("strategy_account_id", name="uq_strategy_runtime_strategy_account"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_accounts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="STOPPED", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(default=1)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    strategy_account: Mapped["StrategyAccountModel"] = relationship(back_populates="runtime")
    state: Mapped["StrategyRuntimeStateModel | None"] = relationship(back_populates="runtime", uselist=False)


class StrategyRuntimeStateModel(PlatformBase):
    __tablename__ = "strategy_runtime_state"

    runtime_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_runtime.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    runtime: Mapped["StrategyRuntimeModel"] = relationship(back_populates="state")


class StrategyOrderIdempotencyModel(PlatformBase):
    __tablename__ = "strategy_order_idempotency"
    __table_args__ = (UniqueConstraint("strategy_account_id", "client_order_id", name="uq_strategy_order_idempotency_client"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_accounts.id", ondelete="CASCADE"))
    client_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    signal_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class EquitySnapshotModel(PlatformBase):
    __tablename__ = "equity_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    exchange_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("exchange_accounts.id", ondelete="SET NULL"), nullable=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True)
    strategy_account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("strategy_accounts.id", ondelete="SET NULL"), nullable=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    equity: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False)
    available_balance: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    realized_pnl: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


class AccountBalanceModel(PlatformBase):
    __tablename__ = "account_balances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exchange_accounts.id", ondelete="CASCADE"))
    asset: Mapped[str] = mapped_column(String(32), default="USD")
    total_balance: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    available_balance: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    equity: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    used_margin: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    realized_pnl: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    currency: Mapped[str] = mapped_column(String(16), default="USD")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AccountPositionModel(PlatformBase):
    __tablename__ = "account_positions"
    __table_args__ = (UniqueConstraint("exchange_account_id", "symbol", name="uq_account_positions_account_symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    exchange_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exchange_accounts.id", ondelete="CASCADE"))
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(16, 8), nullable=False)
    entry_price: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    mark_price: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    realized_pnl: Mapped[float] = mapped_column(Numeric(16, 4), default=0)
    leverage: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    liquidation_price: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AccountOrderModel(PlatformBase):
    __tablename__ = "account_orders"
    __table_args__ = (UniqueConstraint("exchange_account_id", "exchange_order_id", name="uq_account_orders_account_exchange_order"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("exchange_accounts.id", ondelete="CASCADE"))
    exchange_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(16, 8), default=0)
    price: Mapped[float | None] = mapped_column(Numeric(16, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AuditEventModel(PlatformBase):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
