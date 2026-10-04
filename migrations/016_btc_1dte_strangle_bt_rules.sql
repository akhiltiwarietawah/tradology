-- Align live strategy metadata with backtest (10:45–11:00, parso 17:25 exit, no TP).

UPDATE strategies
SET
    description = 'Evening BTC short strangle (parso expiry): ATM ref straddle × 1.8 OTM wings, 25% premium sizing, 100% per-leg bracket SL, exit 17:25 IST on expiry day — no take-profit.',
    metadata = metadata || '{"entry_time_ist": "22:45", "entry_window_minutes": 15, "enable_combined_take_profit": false}'::jsonb
WHERE code = 'btc_1dte_strangle';
