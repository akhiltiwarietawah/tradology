-- Extra Renko Ichimoku perpetual strategies (registry alts).

INSERT INTO strategies (code, name, description, supported_exchanges, markets, timeframe, risk_profile, metadata)
VALUES
    (
        'renko_ichimoku_btc',
        'Renko Ichimoku BTC Perpetual',
        '0.5% Renko box + Ichimoku Mode 3 on BTC perpetual (15m).',
        '["delta_india"]'::jsonb,
        '["BTC"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual", "asset": "BTC"}'::jsonb
    ),
    (
        'renko_ichimoku_bnb',
        'Renko Ichimoku BNB Perpetual',
        '0.5% Renko box + Ichimoku Mode 3 on BNB perpetual (15m).',
        '["delta_india"]'::jsonb,
        '["BNB"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual", "asset": "BNB"}'::jsonb
    ),
    (
        'renko_ichimoku_doge',
        'Renko Ichimoku DOGE Perpetual',
        '0.5% Renko box + Ichimoku Mode 3 on DOGE perpetual (15m).',
        '["delta_india"]'::jsonb,
        '["DOGE"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual", "asset": "DOGE"}'::jsonb
    ),
    (
        'renko_ichimoku_ada',
        'Renko Ichimoku ADA Perpetual',
        '0.5% Renko box + Ichimoku Mode 3 on ADA perpetual (15m).',
        '["delta_india"]'::jsonb,
        '["ADA"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual", "asset": "ADA"}'::jsonb
    ),
    (
        'renko_ichimoku_trx',
        'Renko Ichimoku TRX Perpetual',
        '0.5% Renko box + Ichimoku Mode 3 on TRX perpetual (15m).',
        '["delta_india"]'::jsonb,
        '["TRX"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual", "asset": "TRX"}'::jsonb
    ),
    (
        'renko_ichimoku_avax',
        'Renko Ichimoku AVAX Perpetual',
        '0.5% Renko box + Ichimoku Mode 3 on AVAX perpetual (15m).',
        '["delta_india"]'::jsonb,
        '["AVAX"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual", "asset": "AVAX"}'::jsonb
    ),
    (
        'renko_ichimoku_link',
        'Renko Ichimoku LINK Perpetual',
        '0.5% Renko box + Ichimoku Mode 3 on LINK perpetual (15m).',
        '["delta_india"]'::jsonb,
        '["LINK"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual", "asset": "LINK"}'::jsonb
    ),
    (
        'renko_ichimoku_hype',
        'Renko Ichimoku HYPE Perpetual',
        '0.5% Renko box + Ichimoku Mode 3 on HYPE perpetual (15m). Enable only if listed on your exchange.',
        '["delta_india"]'::jsonb,
        '["HYPE"]'::jsonb,
        '15m',
        'high',
        '{"engine_strategy": true, "category": "perpetual", "asset": "HYPE"}'::jsonb
    )
ON CONFLICT (code) DO NOTHING;
