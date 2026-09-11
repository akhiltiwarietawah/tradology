-- Migration 002: Allow perpetual (Renko) legs without option strikes

ALTER TABLE trade_legs ALTER COLUMN strike DROP NOT NULL;

-- leg_type may be CE/PE (options) or LONG/SHORT (perpetuals)

CREATE INDEX IF NOT EXISTS idx_trades_strategy_status ON trades (strategy_name, status);
