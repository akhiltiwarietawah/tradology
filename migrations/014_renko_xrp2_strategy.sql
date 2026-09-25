-- Second XRP Renko book (strangle/DELTA_LIVE wallet). Isolated from renko_ichimoku_xrp.

INSERT INTO strategies (code, name, description, supported_exchanges, markets, timeframe, risk_profile, metadata)
VALUES
    (
        'renko_ichimoku_xrp2',
        'Renko Ichimoku XRP Perpetual (strangle wallet)',
        'Same XRPUSD Renko+Ichimoku rules on a separate Delta account / virtual book.',
        '["delta_india"]'::jsonb,
        '["XRP"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual", "asset": "XRP", "wallet": "strangle"}'::jsonb
    )
ON CONFLICT (code) DO NOTHING;
