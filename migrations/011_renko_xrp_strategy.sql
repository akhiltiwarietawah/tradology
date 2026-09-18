-- Add XRP Renko Ichimoku as a separate platform strategy (ETH/SOL unchanged).

INSERT INTO strategies (code, name, description, supported_exchanges, markets, timeframe, risk_profile, metadata)
VALUES
    (
        'renko_ichimoku_xrp',
        'Renko Ichimoku XRP Perpetual',
        '0.5% Renko box + Ichimoku Mode 3 on XRP perpetual (15m).',
        '["delta_india"]'::jsonb,
        '["XRP"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual", "asset": "XRP"}'::jsonb
    )
ON CONFLICT (code) DO NOTHING;
