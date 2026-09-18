# Renko + Ichimoku (ETH / SOL / XRP — independent strategies)

This strategy is **separate** from the BTC 0DTE short strangle. Each symbol (ETH, SOL, XRP) has its own state file, order IDs, and position. Short-strangle trading logic is not used here.

Ichimoku lengths are **fixed** (not for optimization):

- Traditional Renko, Source **Close** (per-symbol box size below)
- Signals only on **confirmed** brick closes (no projections)
- Tenkan **9**, Kijun **26**, Span B **52**, cloud displacement **26** bricks

## Enable / disable

| Variable | Default | Meaning |
|---|---|---|
| `EXISTING_STRATEGY_ENABLED` | `true` | BTC short strangle on/off |
| `RENKO_ICHIMOKU_STRATEGY_ENABLED` | `false` | ETH Renko (`renko_ichimoku_eth`) on/off |
| `RENKO_ICHIMOKU_SOL_ENABLED` | `false` | SOL Renko (`renko_ichimoku_sol`) on/off — independent |
| `RENKO_ICHIMOKU_XRP_ENABLED` | `false` | XRP Renko (`renko_ichimoku_xrp`) on/off — independent |

## Accounts

| Variable | Default | Meaning |
|---|---|---|
| `EXISTING_STRATEGY_ACCOUNT` | `primary` | Label for the strangle account (uses `DELTA_*` keys) |
| `RENKO_ICHIMOKU_ACCOUNT` | `renko` | Label for the Renko account |
| `RENKO_ICHIMOKU_API_KEY` | empty | Required when Renko account **differs** from the existing account |
| `RENKO_ICHIMOKU_API_SECRET` | empty | Required when Renko account **differs** from the existing account |

If `RENKO_ICHIMOKU_ACCOUNT` equals `EXISTING_STRATEGY_ACCOUNT`, both strategies use the primary Delta keys but still keep **separate** positions and state. If the names differ, set `RENKO_ICHIMOKU_API_KEY` / `RENKO_ICHIMOKU_API_SECRET` for Account B.

## Renko-only sizing and symbol

| Variable | Default | Meaning |
|---|---|---|
| `RENKO_ICHIMOKU_POSITION_SIZE` | `0` | Contracts to trade. **Not** `ORDER_QUANTITY`. `0` logs signals and sends no orders. |
| `RENKO_ICHIMOKU_SYMBOL` | `ETHUSDT` | ETH perpetual symbol |
| `RENKO_ICHIMOKU_BOX_SIZE` | `15` | ETH Renko box in USD |
| `RENKO_ICHIMOKU_CANDLE_RESOLUTION` | `15m` | Closed-candle Close feed used to confirm bricks. Match your TradingView interval. |
| `RENKO_ICHIMOKU_STATE_FILE` | `data/renko_ichimoku_eth_state_{testnet\|live}.json` | ETH state (independent of `STATE_FILE`) |
| `RENKO_ICHIMOKU_SOL_SYMBOL` | `SOLUSDT` | SOL perpetual symbol |
| `RENKO_ICHIMOKU_SOL_BOX_SIZE` | `0.42` | SOL Renko box in USD (~0.5% at ~$84) |
| `RENKO_ICHIMOKU_SOL_POSITION_SIZE` | `0` | SOL contracts. `0` = signal-only |
| `RENKO_ICHIMOKU_SOL_STATE_FILE` | `data/renko_ichimoku_sol_state_{testnet\|live}.json` | SOL state |
| `RENKO_ICHIMOKU_XRP_SYMBOL` | `XRPUSDT` | XRP perpetual symbol |
| `RENKO_ICHIMOKU_XRP_BOX_SIZE` | `0.003` | XRP Renko box in USD (~0.5% at ~$0.60) |
| `RENKO_ICHIMOKU_XRP_POSITION_SIZE` | `0` | XRP contracts. `0` = signal-only |
| `RENKO_ICHIMOKU_XRP_STATE_FILE` | `data/renko_ichimoku_xrp_state_{testnet\|live}.json` | XRP state |

### Position sizing mode (ETH + SOL + XRP share these)

| Variable | Default | Meaning |
|---|---|---|
| `RENKO_ICHIMOKU_POSITION_SIZING_MODE` | `fixed` | `fixed` = use `*_POSITION_SIZE` contracts; `dynamic` = % equity sizing |
| `RENKO_ICHIMOKU_SIZING_BASE_USD` | `100` | Initial virtual `sizing_equity` on first run (or when state has none) |
| `RENKO_ICHIMOKU_MARGIN_PCT` | `0.25` | Dynamic: **each** entry uses `25%` of effective equity as margin (independent per signal) |
| `RENKO_ICHIMOKU_LEVERAGE` | `10` | Dynamic: notional = margin × leverage |
| `RENKO_ICHIMOKU_PROFIT_RETAIN_PCT` | `0.5` | Dynamic: on a **win**, only 50% of realized PnL is added to virtual `sizing_equity` (simulates 50% withdraw). **Losses apply in full.** |

**Dynamic mode** sizes from virtual `sizing_equity` (starts at `SIZING_BASE_USD`), capped by live wallet on each entry: effective equity = `min(account_balance, virtual sizing_equity)`. Example: `$60` virtual base → `$15` margin per trade → `$150` notional at `10x` (each asset uses its own 25% slice when it signals). Virtual equity is adjusted after exits (50% profit retain). Contract size uses each product's real `contract_value` from Delta (e.g. ETH `0.01`, SOL `1`, XRP per product spec).

Logs use `[EXISTING]`, `[RENKO_ETH]`, `[RENKO_SOL]`, and `[RENKO_XRP]`.

## How to run

From the repo `.env` (plus process env). Existing strangle defaults are unchanged if you omit the new keys.

### A) Existing strategy only

```
EXISTING_STRATEGY_ENABLED=true
RENKO_ICHIMOKU_STRATEGY_ENABLED=false
```

Same as today: BTC short strangle only.

### B) Renko Ichimoku only

```
EXISTING_STRATEGY_ENABLED=false
RENKO_ICHIMOKU_STRATEGY_ENABLED=true
RENKO_ICHIMOKU_ACCOUNT=account_b
RENKO_ICHIMOKU_API_KEY=...
RENKO_ICHIMOKU_API_SECRET=...
RENKO_ICHIMOKU_POSITION_SIZE=1
```

If Renko should use the **same** Delta keys as the strangle account:

```
EXISTING_STRATEGY_ENABLED=false
RENKO_ICHIMOKU_STRATEGY_ENABLED=true
EXISTING_STRATEGY_ACCOUNT=primary
RENKO_ICHIMOKU_ACCOUNT=primary
RENKO_ICHIMOKU_POSITION_SIZE=1
```

### C) Both at once

```
EXISTING_STRATEGY_ENABLED=true
RENKO_ICHIMOKU_STRATEGY_ENABLED=true
EXISTING_STRATEGY_ACCOUNT=account_a
RENKO_ICHIMOKU_ACCOUNT=account_b
RENKO_ICHIMOKU_API_KEY=...
RENKO_ICHIMOKU_API_SECRET=...
RENKO_ICHIMOKU_POSITION_SIZE=1
```

Each strategy sends orders only to its assigned account. State files remain separate (`STATE_FILE` vs `RENKO_ICHIMOKU_STATE_FILE`). Restart does not open a Renko position from historical bricks; it restores only the persisted Renko position.

### Same Delta account (important)

If both strategies use the **same** Delta account and the **same** ETH perpetual product, the exchange holds **one net position** per contract. Software keeps separate strategy state files, but Delta does not. Do not assume two independent exchange positions on one account.

**Manual close on exchange:** If local state shows an open position but the exchange position for the Renko instrument is **flat (0)**, reconcile (startup and every ~30s) syncs local state to flat, logs `Position manually closed`, looks up the latest closing fill/order on Delta when available, and resumes trading. Opposite-side exposure (e.g. local long, exchange short) still **halts** and needs manual intervention.

### Flatten when disabling Renko

| Variable | Default | Meaning |
|---|---|---|
| `RENKO_ICHIMOKU_FLATTEN` | `false` | On startup only: send one reduce-only market close of the Renko instrument, then halt Renko trading |

If Renko is disabled but the state file still shows an open position, the engine logs a critical warning and **does not** close it. To flatten once: set `RENKO_ICHIMOKU_STRATEGY_ENABLED=true`, `RENKO_ICHIMOKU_FLATTEN=true`, restart, confirm flat, then set `ENABLED=false` and `FLATTEN=false`.

## Rules (frozen)

**Long in:** confirmed bullish brick close above both cloud boundaries and above Kijun.  
**Long out:** confirmed brick close inside the cloud **or** at/below Kijun (whichever is true).  
**Short in:** confirmed bearish brick close below both cloud boundaries and below Kijun.  
**Short out:** confirmed brick close inside the cloud **or** at/above Kijun (whichever is true).  
One position; exit first, then opposite entry on the same confirmed brick if valid.

## Persistence (production)

Renko round-trips are stored in PostgreSQL (same `trades` / `trade_legs` / `orders` / `fills` tables as the strangle):

| Layer | Path / endpoint |
|---|---|
| Runtime state (restart) | `RENKO_ICHIMOKU_STATE_FILE` (default `data/renko_ichimoku_state_{testnet\|live}.json`) |
| Order audit events | `logs/trades.jsonl` (`trade_id=renko_ichimoku`) |
| PostgreSQL | `strategy_name=renko_ichimoku`, `exchange=delta_india_renko` |
| API | `GET /api/v1/renko/trades`, `GET /api/v1/trades` (includes `renko_ichimoku` block) |
| Performance | `GET /api/v1/performance?strategy_name=renko_ichimoku` |

Apply migration `002_renko_perpetual_support.sql` via `python migrations/run_migrations.py`.

On startup, if state shows an open position but DB has no `ACTIVE` row, the engine backfills the entry once (`startup_backfill`).
