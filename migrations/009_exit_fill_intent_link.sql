-- Migration 009: Link exit fills to strategy order intents (additive, legacy NULL ok)

ALTER TABLE fills
    ADD COLUMN IF NOT EXISTS strategy_order_intent_id UUID;

CREATE INDEX IF NOT EXISTS idx_fills_strategy_order_intent_id
    ON fills (strategy_order_intent_id)
    WHERE strategy_order_intent_id IS NOT NULL;
