-- Migration 007: Multi-leg strangle groups, fill tracking, validation stats, execution activity
-- Additive only.

CREATE TABLE IF NOT EXISTS strategy_order_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_account_id UUID NOT NULL REFERENCES strategy_accounts(id) ON DELETE CASCADE,
    runtime_id UUID REFERENCES strategy_runtime(id) ON DELETE SET NULL,
    signal_key VARCHAR(256) NOT NULL,
    trade_id VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    leg_1_role VARCHAR(16) NOT NULL DEFAULT 'CE',
    leg_2_role VARCHAR(16) NOT NULL DEFAULT 'PE',
    leg_1_client_order_id VARCHAR(128),
    leg_2_client_order_id VARCHAR(128),
    unwind_client_order_id VARCHAR(128),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_strategy_order_groups_signal UNIQUE (strategy_account_id, signal_key)
);

CREATE INDEX IF NOT EXISTS idx_strategy_order_groups_sa_status ON strategy_order_groups (strategy_account_id, status);

ALTER TABLE strategy_order_intents
    ADD COLUMN IF NOT EXISTS group_id UUID REFERENCES strategy_order_groups(id) ON DELETE SET NULL;

ALTER TABLE strategy_order_intents
    ADD COLUMN IF NOT EXISTS leg_role VARCHAR(16);

ALTER TABLE strategy_order_intents
    ADD COLUMN IF NOT EXISTS filled_quantity NUMERIC(16, 8);

ALTER TABLE strategy_order_intents
    ADD COLUMN IF NOT EXISTS average_fill_price NUMERIC(16, 4);

CREATE TABLE IF NOT EXISTS platform_execution_activity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_account_id UUID NOT NULL REFERENCES strategy_accounts(id) ON DELETE CASCADE,
    runtime_id UUID REFERENCES strategy_runtime(id) ON DELETE SET NULL,
    event_type VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'INFO',
    signal_key VARCHAR(256),
    symbol VARCHAR(64),
    side VARCHAR(8),
    quantity NUMERIC(16, 8),
    execution_mode VARCHAR(16),
    order_status VARCHAR(32),
    exchange_order_id VARCHAR(128),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_execution_activity_sa_time
    ON platform_execution_activity (strategy_account_id, created_at DESC);

CREATE TABLE IF NOT EXISTS platform_validation_stats (
    strategy_account_id UUID PRIMARY KEY REFERENCES strategy_accounts(id) ON DELETE CASCADE,
    signals_generated INT NOT NULL DEFAULT 0,
    would_execute INT NOT NULL DEFAULT 0,
    risk_rejected INT NOT NULL DEFAULT 0,
    duplicate_prevented INT NOT NULL DEFAULT 0,
    market_data_rejected INT NOT NULL DEFAULT 0,
    runtime_errors INT NOT NULL DEFAULT 0,
    last_reconciliation VARCHAR(16),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
