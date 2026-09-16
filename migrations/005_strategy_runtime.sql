-- Migration 005: Multi-user strategy runtime execution architecture
-- Additive only. Does not modify existing Delta engine tables destructively.

-- 1. Strategy account execution controls
ALTER TABLE strategy_accounts
    ADD COLUMN IF NOT EXISTS execution_mode VARCHAR(16) NOT NULL DEFAULT 'PAPER',
    ADD COLUMN IF NOT EXISTS trading_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS runtime_status VARCHAR(32) NOT NULL DEFAULT 'STOPPED';

CREATE INDEX IF NOT EXISTS idx_strategy_accounts_runtime_status ON strategy_accounts (runtime_status);
CREATE INDEX IF NOT EXISTS idx_strategy_accounts_execution_mode ON strategy_accounts (execution_mode);

-- 2. Canonical runtime record (one active runtime row per strategy_account)
CREATE TABLE IF NOT EXISTS strategy_runtime (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_account_id UUID NOT NULL REFERENCES strategy_accounts(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'STOPPED',
    started_at TIMESTAMPTZ,
    stopped_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    last_error TEXT,
    last_error_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1,
    worker_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_strategy_runtime_strategy_account UNIQUE (strategy_account_id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_runtime_status ON strategy_runtime (status);
CREATE INDEX IF NOT EXISTS idx_strategy_runtime_heartbeat ON strategy_runtime (last_heartbeat_at DESC);

-- 3. Isolated runtime state (replaces JSON files for multi-user execution)
CREATE TABLE IF NOT EXISTS strategy_runtime_state (
    runtime_id UUID PRIMARY KEY REFERENCES strategy_runtime(id) ON DELETE CASCADE,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Order idempotency ledger
CREATE TABLE IF NOT EXISTS strategy_order_idempotency (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_account_id UUID NOT NULL REFERENCES strategy_accounts(id) ON DELETE CASCADE,
    client_order_id VARCHAR(128) NOT NULL,
    signal_key VARCHAR(256),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    exchange_order_id VARCHAR(128),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_strategy_order_idempotency_client UNIQUE (strategy_account_id, client_order_id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_order_idempotency_sa ON strategy_order_idempotency (strategy_account_id);
CREATE INDEX IF NOT EXISTS idx_strategy_order_idempotency_signal ON strategy_order_idempotency (strategy_account_id, signal_key);

-- 5. Multi-tenant traceability on existing trade ledger (nullable for backward compatibility)
ALTER TABLE trades
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS strategy_account_id UUID REFERENCES strategy_accounts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades (user_id);
CREATE INDEX IF NOT EXISTS idx_trades_subscription_id ON trades (subscription_id);
CREATE INDEX IF NOT EXISTS idx_trades_strategy_account_id ON trades (strategy_account_id);

-- 6. Subscription billing lifecycle support
ALTER TABLE subscriptions
    ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_subscriptions_expires_at ON subscriptions (expires_at);
