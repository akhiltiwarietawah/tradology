# ETHUSDT Traditional Renko + Ichimoku (independent strategy)

This strategy is **separate** from the BTC 0DTE short strangle. It has its own enable switch, account, state file, order IDs, and position. Short-strangle trading logic is not used here.

Renko box size and Ichimoku lengths are **fixed** (not for optimization):

- Traditional Renko, box **$15**, Source **Close**
- Signals only on **confirmed** brick closes (no projections)
- Tenkan **9**, Kijun **26**, Span B **52**, cloud displacement **26** bricks

## Enable / disable

| Variable | Default | Meaning |
|---|---|---|
| `EXISTING_STRATEGY_ENABLED` | `true` | BTC short strangle on/off |
| `RENKO_ICHIMOKU_STRATEGY_ENABLED` | `false` | Renko Ichimoku on/off |

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
| `RENKO_ICHIMOKU_SYMBOL` | `ETHUSDT` | Perpetual symbol (Delta may list `ETHUSD`; the adapter tries aliases) |
| `RENKO_ICHIMOKU_CANDLE_RESOLUTION` | `15m` | Closed-candle Close feed used to confirm bricks. Match your TradingView interval. |
| `RENKO_ICHIMOKU_STATE_FILE` | `data/renko_ichimoku_state_{testnet\|live}.json` | Independent of `STATE_FILE` |

Logs use `[EXISTING]` and `[RENKO_ICHIMOKU]`.

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

If both strategies use the **same** Delta account and the **same** ETH perpetual product, the exchange holds **one net position** per contract. Software keeps separate strategy state files, but Delta does not. Any manual ETH trade or another bot on that account can make Renko local state disagree with the exchange; the Renko path **halts** on mismatch (startup and every ~30s). Do not assume two independent exchange positions on one account.

### Flatten when disabling Renko

| Variable | Default | Meaning |
|---|---|---|
| `RENKO_ICHIMOKU_FLATTEN` | `false` | On startup only: send one reduce-only market close of the Renko instrument, then halt Renko trading |

If Renko is disabled but the state file still shows an open position, the engine logs a critical warning and **does not** close it. To flatten once: set `RENKO_ICHIMOKU_STRATEGY_ENABLED=true`, `RENKO_ICHIMOKU_FLATTEN=true`, restart, confirm flat, then set `ENABLED=false` and `FLATTEN=false`.

## Rules (frozen)

**Long in:** confirmed bullish brick close above both cloud boundaries and above Kijun.  
**Long out:** confirmed brick close inside the cloud (do not wait for Kijun).  
**Short in:** confirmed bearish brick close below both cloud boundaries and below Kijun.  
**Short out:** confirmed brick close at or above Kijun.  
One position; exit first, then opposite entry on the same confirmed brick if valid.
