-- BTC 0-DTE Long Straddle (1:00 PM IST entry, 5:30 PM auto-settlement).

INSERT INTO strategies (code, name, description, supported_exchanges, markets, timeframe, risk_profile, metadata)
VALUES
    (
        'btc_0dte_long_straddle',
        'BTC 0-DTE Long Straddle',
        '1:00 PM IST weekday BTC ATM Long Straddle (0DTE): Mon-Fri entry ahead of London open, 10 lots fixed or dynamic margin sizing, auto cash-settlement at 17:30 IST to save exit fees on worthless legs.',
        '["delta_india"]'::jsonb,
        '["BTC"]'::jsonb,
        '0DTE',
        'medium',
        '{"integrated_runtime": true, "category": "options", "entry_time_ist": "13:00", "entry_window_minutes": 15, "exit_time_ist": "17:30"}'::jsonb
    )
ON CONFLICT (code) DO NOTHING;
