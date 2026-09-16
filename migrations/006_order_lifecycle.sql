-- Migration 006: Order lifecycle, intents, worker coordination, kill switch fields
-- Additive only.

CREATE TABLE IF NOT EXISTS strategy_order_intents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_account_id UUID NOT NULL REFERENCES strategy_accounts(id) ON DELETE CASCADE,
    runtime_id UUID REFERENCES strategy_runtime(id) ON DELETE SET NULL,
    signal_key VARCHAR(256),
    client_order_id VARCHAR(128) NOT NULL,
    symbol VARCHAR(64) NOT NULL,
    side VARCHAR(8) NOT NULL,
    order_type VARCHAR(32) NOT NULL DEFAULT 'market',
    quantity NUMERIC(16, 8) NOT NULL,
    price NUMERIC(16, 4),
    status VARCHAR(32) NOT NULL DEFAULT 'SIGNAL',
    exchange_order_id VARCHAR(128),
    execution_mode VARCHAR(16) NOT NULL DEFAULT 'PAPER',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    filled_at TIMESTAMPTZ,
    CONSTRAINT uq_strategy_order_intents_client UNIQUE (strategy_account_id, client_order_id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_order_intents_sa_status ON strategy_order_intents (strategy_account_id, status);
CREATE INDEX IF NOT EXISTS idx_strategy_order_intents_runtime ON strategy_order_intents (runtime_id);

-- Worker coordination heartbeat on runtime row already exists — stale detection index
CREATE INDEX IF NOT EXISTS idx_strategy_runtime_worker ON strategy_runtime (worker_id, last_heartbeat_at DESC);

-- Exchange account trading kill switch
ALTER TABLE exchange_accounts
    ADD COLUMN IF NOT EXISTS trading_enabled BOOLEAN NOT NULL DEFAULT TRUE;

-- Audit index for lifecycle events
CREATE INDEX IF NOT EXISTS idx_audit_events_type_time ON audit_events (event_type, created_at DESC);
