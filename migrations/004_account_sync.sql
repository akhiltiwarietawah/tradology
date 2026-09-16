-- Migration 004: Account sync health, denormalized metrics, extended balance/position/order storage

ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS health_status VARCHAR(32) NOT NULL DEFAULT 'DISCONNECTED';
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS last_successful_sync_at TIMESTAMPTZ;
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ;
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS equity NUMERIC(16, 4) NOT NULL DEFAULT 0.0000;
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS available_balance NUMERIC(16, 4) NOT NULL DEFAULT 0.0000;
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS unrealized_pnl NUMERIC(16, 4) NOT NULL DEFAULT 0.0000;
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS realized_pnl NUMERIC(16, 4) NOT NULL DEFAULT 0.0000;
ALTER TABLE exchange_accounts ADD COLUMN IF NOT EXISTS currency VARCHAR(16) NOT NULL DEFAULT 'USD';

CREATE INDEX IF NOT EXISTS idx_exchange_accounts_health ON exchange_accounts (health_status);
CREATE INDEX IF NOT EXISTS idx_exchange_accounts_user_health ON exchange_accounts (user_id, health_status);

ALTER TABLE account_balances ADD COLUMN IF NOT EXISTS unrealized_pnl NUMERIC(16, 4) NOT NULL DEFAULT 0.0000;
ALTER TABLE account_balances ADD COLUMN IF NOT EXISTS realized_pnl NUMERIC(16, 4) NOT NULL DEFAULT 0.0000;
ALTER TABLE account_balances ADD COLUMN IF NOT EXISTS used_margin NUMERIC(16, 4) NOT NULL DEFAULT 0.0000;
ALTER TABLE account_balances ADD COLUMN IF NOT EXISTS currency VARCHAR(16) NOT NULL DEFAULT 'USD';

ALTER TABLE account_positions ADD COLUMN IF NOT EXISTS leverage NUMERIC(8, 2);
ALTER TABLE account_positions ADD COLUMN IF NOT EXISTS liquidation_price NUMERIC(16, 4);
ALTER TABLE account_positions ADD COLUMN IF NOT EXISTS realized_pnl NUMERIC(16, 4) NOT NULL DEFAULT 0.0000;
ALTER TABLE account_positions ADD COLUMN IF NOT EXISTS exchange_symbol VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS uq_account_positions_account_symbol
    ON account_positions (exchange_account_id, symbol);

CREATE TABLE IF NOT EXISTS account_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exchange_account_id UUID NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
    exchange_order_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(64) NOT NULL,
    side VARCHAR(8) NOT NULL,
    order_type VARCHAR(32) NOT NULL,
    quantity NUMERIC(16, 8) NOT NULL DEFAULT 0,
    price NUMERIC(16, 4),
    status VARCHAR(32) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_account_orders_account_exchange_order UNIQUE (exchange_account_id, exchange_order_id)
);

CREATE INDEX IF NOT EXISTS idx_account_orders_account ON account_orders (exchange_account_id);
CREATE INDEX IF NOT EXISTS idx_equity_snapshots_account_scope_time
    ON equity_snapshots (exchange_account_id, scope, snapshot_at DESC);
