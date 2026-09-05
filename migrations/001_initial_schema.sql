-- Migration 001: Initial Schema for Trades, Trade Legs, Orders, and Fills
-- Compatible with PostgreSQL 14+

-- 1. Trades Table
CREATE TABLE IF NOT EXISTS trades (
    trade_id VARCHAR(64) PRIMARY KEY,
    strategy_name VARCHAR(64) NOT NULL,
    exchange VARCHAR(32) NOT NULL DEFAULT 'delta_india',
    trade_date DATE NOT NULL,
    status VARCHAR(32) NOT NULL,
    entry_time TIMESTAMPTZ NULL,
    exit_time TIMESTAMPTZ NULL,
    total_entry_premium NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    total_exit_premium NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    realized_pnl NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    total_fees NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    net_pnl NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    exit_reason VARCHAR(64) NULL,
    strategy_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_date ON trades (trade_date);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades (strategy_name);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);
CREATE INDEX IF NOT EXISTS idx_trades_exchange ON trades (exchange);

-- 2. Trade Legs Table
CREATE TABLE IF NOT EXISTS trade_legs (
    leg_id VARCHAR(64) PRIMARY KEY,
    trade_id VARCHAR(64) NOT NULL REFERENCES trades(trade_id) ON DELETE CASCADE,
    leg_type VARCHAR(8) NOT NULL, -- 'CE' or 'PE'
    symbol VARCHAR(64) NOT NULL,
    product_id VARCHAR(32) NOT NULL,
    strike NUMERIC(16, 2) NOT NULL,
    quantity NUMERIC(16, 4) NOT NULL,
    side VARCHAR(8) NOT NULL DEFAULT 'sell',
    entry_price NUMERIC(16, 4) NULL,
    exit_price NUMERIC(16, 4) NULL,
    entry_time TIMESTAMPTZ NULL,
    exit_time TIMESTAMPTZ NULL,
    stop_loss_price NUMERIC(16, 4) NULL,
    bracket_order_id VARCHAR(64) NULL,
    realized_pnl NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    fees NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_legs_trade_id ON trade_legs (trade_id);
CREATE INDEX IF NOT EXISTS idx_legs_symbol ON trade_legs (symbol);
CREATE INDEX IF NOT EXISTS idx_legs_status ON trade_legs (status);
CREATE INDEX IF NOT EXISTS idx_legs_product_id ON trade_legs (product_id);

-- 3. Orders Table
CREATE TABLE IF NOT EXISTS orders (
    order_id VARCHAR(64) PRIMARY KEY,
    trade_id VARCHAR(64) NULL REFERENCES trades(trade_id) ON DELETE SET NULL,
    trade_leg_id VARCHAR(64) NULL REFERENCES trade_legs(leg_id) ON DELETE SET NULL,
    exchange VARCHAR(32) NOT NULL DEFAULT 'delta_india',
    exchange_order_id VARCHAR(64) NULL,
    client_order_id VARCHAR(64) NULL,
    symbol VARCHAR(64) NOT NULL,
    product_id VARCHAR(32) NOT NULL,
    side VARCHAR(8) NOT NULL, -- 'buy' or 'sell'
    order_type VARCHAR(32) NOT NULL, -- 'market_order', 'limit_order', etc.
    quantity NUMERIC(16, 4) NOT NULL,
    filled_quantity NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    average_fill_price NUMERIC(16, 4) NULL,
    status VARCHAR(32) NOT NULL, -- 'pending', 'open', 'filled', 'cancelled', 'rejected', 'expired'
    reduce_only BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_trade_id ON orders (trade_id);
CREATE INDEX IF NOT EXISTS idx_orders_leg_id ON orders (trade_leg_id);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders (symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_exchange_order_id ON orders (exchange, exchange_order_id) WHERE exchange_order_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_client_order_id ON orders (client_order_id) WHERE client_order_id IS NOT NULL;

-- 4. Fills Table
CREATE TABLE IF NOT EXISTS fills (
    fill_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    exchange_fill_id VARCHAR(64) NULL,
    quantity NUMERIC(16, 4) NOT NULL,
    price NUMERIC(16, 4) NOT NULL,
    fee NUMERIC(16, 4) NOT NULL DEFAULT 0.0000,
    fee_currency VARCHAR(16) NOT NULL DEFAULT 'USD',
    fill_time TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills (order_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_fills_exchange_fill_id ON fills (exchange_fill_id) WHERE exchange_fill_id IS NOT NULL;
