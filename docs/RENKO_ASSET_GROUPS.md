# Renko asset groups (A / B / C + ZEC)

Mode 3, 15m Close Renko. **ETH = $15 box**; alts **0.5% median** (override per coin in `.env`).

## Group A — Primary 11

ETH/SOL/XRP via dedicated flags + `RENKO_ICHIMOKU_ALTS_ENABLED` for:
`btc,bnb,doge,ada,trx,avax,link,hype`

Migration: `012_renko_alt_strategies.sql`

## Group B — Extension 8

`RENKO_ICHIMOKU_ALTS_GROUP_B_ENABLED=sui,inj,near,apt,pepe,wif,ena,jup`

## Group C — Exploratory 13

`RENKO_ICHIMOKU_ALTS_GROUP_C_ENABLED=ton,dot,atom,ltc,bch,uni,aave,pol,sei,tia,op,arb,paxg`

## ZEC — Separate watchlist

Not in A/B/C. Enable only after Delta symbol check + backtest review:

```env
RENKO_ICHIMOKU_ZEC_ENABLED=true
```

Backtest: `btc-backtest/results/renko_zec_mode3/`

## Platform DB

Run `013_renko_groups_b_c_zec_strategies.sql` for B/C/ZEC strategy rows.

Catalog source: `src/strategies/renko_ichimoku/asset_registry.py`
