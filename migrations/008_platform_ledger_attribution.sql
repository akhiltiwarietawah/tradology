-- Migration 008: Platform ledger attribution for user-scoped P&L
-- Additive only. Legacy rows remain NULL-attributed.

-- trades: columns from 005 may already exist — ensure indexes
CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades (user_id);
CREATE INDEX IF NOT EXISTS idx_trades_strategy_account_id ON trades (strategy_account_id);
CREATE INDEX IF NOT EXISTS idx_trades_subscription_id ON trades (subscription_id);

-- orders: platform attribution
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS strategy_account_id UUID REFERENCES strategy_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS exchange_account_id UUID REFERENCES exchange_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS strategy_order_intent_id UUID;

CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders (user_id);
CREATE INDEX IF NOT EXISTS idx_orders_strategy_account_id ON orders (strategy_account_id);
CREATE INDEX IF NOT EXISTS idx_orders_exchange_account_id ON orders (exchange_account_id);

-- fills: platform attribution
ALTER TABLE fills
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS strategy_account_id UUID REFERENCES strategy_accounts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_fills_strategy_account_id ON fills (strategy_account_id);
CREATE INDEX IF NOT EXISTS idx_fills_user_id ON fills (user_id);

-- strategy-level equity snapshots
ALTER TABLE equity_snapshots
    ADD COLUMN IF NOT EXISTS strategy_account_id UUID REFERENCES strategy_accounts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_equity_snapshots_strategy_account_time
    ON equity_snapshots (strategy_account_id, snapshot_at DESC)
    WHERE strategy_account_id IS NOT NULL;
