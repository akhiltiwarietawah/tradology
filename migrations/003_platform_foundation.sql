-- Migration 003: Multi-tenant platform foundation (users, accounts, strategies, subscriptions)
-- Does NOT alter existing trade ledger tables — additive only.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Users
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    google_id VARCHAR(255) UNIQUE,
    name VARCHAR(255),
    avatar_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

-- 2. Strategy catalog (platform-level, not runtime engine config)
CREATE TABLE IF NOT EXISTS strategies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    supported_exchanges JSONB NOT NULL DEFAULT '[]'::jsonb,
    markets JSONB NOT NULL DEFAULT '[]'::jsonb,
    timeframe VARCHAR(32),
    risk_profile VARCHAR(32),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategies_code ON strategies (code);
CREATE INDEX IF NOT EXISTS idx_strategies_active ON strategies (is_active);

-- 3. User strategy subscriptions (one row per user per strategy)
CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    strategy_id UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    billing_plan VARCHAR(64) NOT NULL DEFAULT 'free',
    risk_settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    subscribed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_subscriptions_user_strategy UNIQUE (user_id, strategy_id)
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions (user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions (status);

-- 4. Connected exchange accounts (encrypted credentials server-side only)
CREATE TABLE IF NOT EXISTS exchange_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exchange VARCHAR(32) NOT NULL,
    label VARCHAR(128) NOT NULL,
    credentials_encrypted BYTEA NOT NULL,
    connection_status VARCHAR(32) NOT NULL DEFAULT 'disconnected',
    last_sync_at TIMESTAMPTZ,
    is_testnet BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_exchange_accounts_user_exchange_label UNIQUE (user_id, exchange, label)
);

CREATE INDEX IF NOT EXISTS idx_exchange_accounts_user ON exchange_accounts (user_id);
CREATE INDEX IF NOT EXISTS idx_exchange_accounts_exchange ON exchange_accounts (exchange);

-- 5. Strategy ↔ exchange account bindings (via subscription)
CREATE TABLE IF NOT EXISTS strategy_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'paused',
    allocation_pct NUMERIC(5, 2) NOT NULL DEFAULT 100.00,
    risk_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
    runtime_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_strategy_accounts_sub_account UNIQUE (subscription_id, exchange_account_id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_accounts_subscription ON strategy_accounts (subscription_id);
CREATE INDEX IF NOT EXISTS idx_strategy_accounts_account ON strategy_accounts (exchange_account_id);

-- 6. Equity snapshots (account / strategy / portfolio curves)
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exchange_account_id UUID REFERENCES exchange_accounts(id) ON DELETE SET NULL,
    subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL,
    scope VARCHAR(32) NOT NULL,
    equity NUMERIC(16, 4) NOT NULL,
    available_balance NUMERIC(16, 4),
    unrealized_pnl NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    realized_pnl NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_equity_snapshots_user_time ON equity_snapshots (user_id, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_equity_snapshots_account_time ON equity_snapshots (exchange_account_id, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_equity_snapshots_subscription_time ON equity_snapshots (subscription_id, snapshot_at DESC);

-- 7. Account balance snapshots
CREATE TABLE IF NOT EXISTS account_balances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    asset VARCHAR(32) NOT NULL DEFAULT 'USD',
    total_balance NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    available_balance NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    equity NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_account_balances_account_time ON account_balances (exchange_account_id, recorded_at DESC);

-- 8. Platform positions (synced from exchange adapters — not engine JSON state)
CREATE TABLE IF NOT EXISTS account_positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL,
    symbol VARCHAR(64) NOT NULL,
    side VARCHAR(8) NOT NULL,
    quantity NUMERIC(16, 8) NOT NULL,
    entry_price NUMERIC(16, 4),
    mark_price NUMERIC(16, 4),
    unrealized_pnl NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_account_positions_user ON account_positions (user_id);
CREATE INDEX IF NOT EXISTS idx_account_positions_account ON account_positions (exchange_account_id);

-- 9. Strategy execution runs (runtime lifecycle per strategy_account)
CREATE TABLE IF NOT EXISTS strategy_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_account_id UUID NOT NULL REFERENCES strategy_accounts(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'idle',
    started_at TIMESTAMPTZ,
    stopped_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_runs_sa ON strategy_runs (strategy_account_id);

-- 10. Audit / platform events
CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    event_type VARCHAR(64) NOT NULL,
    resource_type VARCHAR(64),
    resource_id VARCHAR(64),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_user_time ON audit_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events (event_type);

-- Seed built-in strategies (idempotent)
INSERT INTO strategies (code, name, description, supported_exchanges, markets, timeframe, risk_profile, metadata)
VALUES
    (
        'short_strangle',
        'BTC 0DTE Short Strangle',
        'Daily BTC options short strangle with native bracket stop-loss and EOD square-off on Delta Exchange India.',
        '["delta_india"]'::jsonb,
        '["BTC"]'::jsonb,
        '0DTE',
        'medium',
        '{"engine_strategy": true, "category": "options"}'::jsonb
    ),
    (
        'renko_ichimoku',
        'Renko Ichimoku ETH Perpetual',
        'Renko brick + Ichimoku trend strategy on ETH perpetual with isolated account support.',
        '["delta_india"]'::jsonb,
        '["ETH"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual"}'::jsonb
    )
ON CONFLICT (code) DO NOTHING;
