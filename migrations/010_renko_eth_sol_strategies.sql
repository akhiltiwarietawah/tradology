-- Split Renko Ichimoku into separate ETH and SOL platform strategies.

UPDATE strategies
SET
    code = 'renko_ichimoku_eth',
    name = 'Renko Ichimoku ETH Perpetual',
    description = 'Traditional $15 Renko + Ichimoku Mode 3 on ETH perpetual (15m).',
    markets = '["ETH"]'::jsonb,
    metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{asset}', '"ETH"')
WHERE code = 'renko_ichimoku';

INSERT INTO strategies (code, name, description, supported_exchanges, markets, timeframe, risk_profile, metadata)
VALUES
    (
        'renko_ichimoku_sol',
        'Renko Ichimoku SOL Perpetual',
        '0.5% Renko box + Ichimoku Mode 3 on SOL perpetual (15m).',
        '["delta_india"]'::jsonb,
        '["SOL"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual", "asset": "SOL"}'::jsonb
    )
ON CONFLICT (code) DO NOTHING;

UPDATE trades
SET strategy_name = 'renko_ichimoku_eth'
WHERE strategy_name = 'renko_ichimoku';
