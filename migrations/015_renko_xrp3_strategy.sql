-- Third XRP Renko book (own Delta account). Isolated from renko_ichimoku_xrp and renko_ichimoku_xrp2.
-- Virtual book $10, dynamic sizing at 50x (notional = equity × margin_pct × 50).

INSERT INTO strategies (code, name, description, supported_exchanges, markets, timeframe, risk_profile, metadata)
VALUES
    (
        'renko_ichimoku_xrp3',
        'Renko Ichimoku XRP Perpetual (third wallet)',
        'Same XRPUSD Renko+Ichimoku rules on a third Delta account. $10 virtual book, 50x position sizing.',
        '["delta_india"]'::jsonb,
        '["XRP"]'::jsonb,
        '15m',
        'medium',
        '{"engine_strategy": true, "category": "perpetual", "asset": "XRP", "wallet": "xrp3", "sizing_base_usd": 10, "leverage": 50}'::jsonb
    )
ON CONFLICT (code) DO NOTHING;
