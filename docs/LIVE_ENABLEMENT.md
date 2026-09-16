# Live Enablement — Staged Process

All flags default to **FALSE**. Do not skip stages.

## Stage 1 — Paper
- `execution_mode=PAPER` on one strategy account
- Start runtime, verify signals and risk checks
- No exchange orders

## Stage 2 — Live Dry Run
- Set `execution_mode=LIVE_DRY_RUN` with `confirm_live=true`
- Start runtime against real Delta account (testnet recommended first)
- Inspect `GET /platform/strategy-accounts/{id}/validation`
- Confirm: signals, WOULD_EXECUTE events, reconciliation PASS, zero real submissions

## Stage 3 — Enable Platform Runtime
```env
PLATFORM_RUNTIME_EXECUTION_ENABLED=true
```
- Still no live orders until Stage 4+5

## Stage 4 — Enable Delta Platform Live
```env
PLATFORM_DELTA_LIVE_ENABLED=true
```
- Orders still blocked by global kill switch

## Stage 5 — Enable Trading on ONE Strategy Account
- Use isolated test account
- `trading_enabled=true` with `confirm_live=true`
- Limits enforced: `PLATFORM_MAX_LIVE_TEST_QUANTITY`, `PLATFORM_MAX_LIVE_TEST_NOTIONAL`

## Stage 6 — Controlled Tiny Live Test
```env
PLATFORM_LIVE_TRADING_ENABLED=true
```
- **Manual only** — one tiny strangle entry
- Stop global `TradingEngine` first if using same Delta account (`LEGACY_ENGINE` guard)

## Stage 7 — Verify
- Order on exchange matches `strategy_order_intents`
- Fills in trade ledger
- Position reconciliation PASS
- Group status `COMPLETE`

## Stage 8 — Increase Limits
- Only after Stage 7 verified
- Increase quantity/notional gradually

## Emergency Stop
```env
PLATFORM_LIVE_TRADING_ENABLED=false
```
Or `POST /platform/internal/global-kill-switch` with API key auth.

## Status
**CODE READY / LIVE NOT VERIFIED** until a manual controlled test completes Stage 7.
