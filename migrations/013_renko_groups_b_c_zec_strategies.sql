-- Group B + C + ZEC (watchlist) Renko strategies.

INSERT INTO strategies (code, name, description, supported_exchanges, markets, timeframe, risk_profile, metadata)
VALUES
    ('renko_ichimoku_sui', 'Renko Ichimoku SUI', 'Group B', '["delta_india"]'::jsonb, '["SUI"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "B"}'::jsonb),
    ('renko_ichimoku_inj', 'Renko Ichimoku INJ', 'Group B', '["delta_india"]'::jsonb, '["INJ"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "B"}'::jsonb),
    ('renko_ichimoku_near', 'Renko Ichimoku NEAR', 'Group B', '["delta_india"]'::jsonb, '["NEAR"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "B"}'::jsonb),
    ('renko_ichimoku_apt', 'Renko Ichimoku APT', 'Group B', '["delta_india"]'::jsonb, '["APT"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "B"}'::jsonb),
    ('renko_ichimoku_pepe', 'Renko Ichimoku PEPE', 'Group B', '["delta_india"]'::jsonb, '["PEPE"]'::jsonb, '15m', 'high', '{"engine_strategy": true, "group": "B"}'::jsonb),
    ('renko_ichimoku_wif', 'Renko Ichimoku WIF', 'Group B', '["delta_india"]'::jsonb, '["WIF"]'::jsonb, '15m', 'high', '{"engine_strategy": true, "group": "B"}'::jsonb),
    ('renko_ichimoku_ena', 'Renko Ichimoku ENA', 'Group B', '["delta_india"]'::jsonb, '["ENA"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "B"}'::jsonb),
    ('renko_ichimoku_jup', 'Renko Ichimoku JUP', 'Group B', '["delta_india"]'::jsonb, '["JUP"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "B"}'::jsonb),
    ('renko_ichimoku_ton', 'Renko Ichimoku TON', 'Group C', '["delta_india"]'::jsonb, '["TON"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_dot', 'Renko Ichimoku DOT', 'Group C', '["delta_india"]'::jsonb, '["DOT"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_atom', 'Renko Ichimoku ATOM', 'Group C', '["delta_india"]'::jsonb, '["ATOM"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_ltc', 'Renko Ichimoku LTC', 'Group C', '["delta_india"]'::jsonb, '["LTC"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_bch', 'Renko Ichimoku BCH', 'Group C', '["delta_india"]'::jsonb, '["BCH"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_uni', 'Renko Ichimoku UNI', 'Group C', '["delta_india"]'::jsonb, '["UNI"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_aave', 'Renko Ichimoku AAVE', 'Group C', '["delta_india"]'::jsonb, '["AAVE"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_pol', 'Renko Ichimoku POL', 'Group C', '["delta_india"]'::jsonb, '["POL"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_sei', 'Renko Ichimoku SEI', 'Group C', '["delta_india"]'::jsonb, '["SEI"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_tia', 'Renko Ichimoku TIA', 'Group C', '["delta_india"]'::jsonb, '["TIA"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_op', 'Renko Ichimoku OP', 'Group C', '["delta_india"]'::jsonb, '["OP"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_arb', 'Renko Ichimoku ARB', 'Group C', '["delta_india"]'::jsonb, '["ARB"]'::jsonb, '15m', 'medium', '{"engine_strategy": true, "group": "C"}'::jsonb),
    ('renko_ichimoku_paxg', 'Renko Ichimoku PAXG', 'Group C — gold', '["delta_india"]'::jsonb, '["PAXG"]'::jsonb, '15m', 'low', '{"engine_strategy": true, "group": "C", "asset": "Gold"}'::jsonb),
    ('renko_ichimoku_zec', 'Renko Ichimoku ZEC', 'Watchlist — backtested separately from A/B/C', '["delta_india"]'::jsonb, '["ZEC"]'::jsonb, '15m', 'high', '{"engine_strategy": true, "group": "ZEC"}'::jsonb)
ON CONFLICT (code) DO NOTHING;
