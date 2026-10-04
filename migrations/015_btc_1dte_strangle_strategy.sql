-- BTC 1-DTE short strangle (10:45–10:50 PM IST entry, next-day exit).

INSERT INTO strategies (code, name, description, supported_exchanges, markets, timeframe, risk_profile, metadata)
VALUES
    (
        'btc_1dte_strangle',
        'BTC 1-DTE Short Strangle',
        'Evening BTC short strangle (parso expiry): 1.8× ref wings, 25% premium sizing, combined $3 TP (scaled), 100% per-leg bracket SL, next-day 17:25 IST exit.',
        '["delta_india"]'::jsonb,
        '["BTC"]'::jsonb,
        '1DTE',
        'medium',
        '{"integrated_runtime": true, "category": "options", "entry_time_ist": "22:45", "entry_window_minutes": 5}'::jsonb
    )
ON CONFLICT (code) DO NOTHING;
