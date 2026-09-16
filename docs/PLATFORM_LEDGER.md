# Platform Ledger — User-Scoped Attribution & P&L

## Ownership Model

Every platform-originated ledger row is attributable server-side:

```
USER
  └── SUBSCRIPTION (strategy catalog enrollment)
        └── STRATEGY_ACCOUNT (subscription + exchange account link)
              └── ORDER / FILL / TRADE
```

Required attribution fields (nullable for legacy engine data):

| Table | Fields |
|-------|--------|
| `trades` | `user_id`, `subscription_id`, `strategy_account_id` |
| `orders` | above + `exchange_account_id`, `strategy_order_intent_id` |
| `fills` | above + `strategy_order_intent_id` |
| `equity_snapshots` | `strategy_account_id` (scope=`strategy_account`) |

Legacy global trades remain in `trades` with NULL attribution and are **excluded** from platform user APIs.

## Canonical Flow (Entry + Exit)

```
RuntimeContext
  → strategy_order_intents (OrderLifecycleRepository.create_intent)
  → OrderExecutionPipeline.process_intent
  → ExecutionAdapter (paper / dry-run / live — flags unchanged)
  → ExecutionResult (includes order_intent_id)
  → ENTRY: PlatformFillBridge.record_strangle_entry
  → EXIT:  PlatformExitLedger.persist_exit → PlatformFillBridge.record_leg_exit
  → TradeRepository.record_entry / record_leg_exit
  → Strategy equity snapshot (optional, per fill)
```

Exit paths wired through `PlatformExitLedger`:

| Exit type | Handler | exit_reason |
|-----------|---------|-------------|
| Stop-loss | `ShortStrangleRuntimeAdapter._handle_sl` | `STOP_LOSS` |
| EOD square-off | `ShortStrangleRuntimeAdapter._handle_exit` | `EOD_EXIT` |
| Emergency unwind | `StrangleExecutionCoordinator._emergency_unwind` | `EMERGENCY_UNWIND` |
| Recovery/reconcile | `ShortStrangleRuntimeAdapter.start` → `persist_reconciled_exit` | `EXCHANGE_CLOSE` |

`PlatformFillBridge.attribution_from_context()` derives ownership from runtime context — never from frontend input.

## Order Intent Linkage

```
strategy_order_intents.id
  → orders.strategy_order_intent_id
  → fills.strategy_order_intent_id
  → trade / trade_leg (via order.trade_id / trade_leg_id)
```

Intent IDs are created in `OrderExecutionPipeline.process_intent` and propagated through `ExecutionResult.order_intent_id`. Never inferred from symbol alone.

## Idempotency

| Layer | Key |
|-------|-----|
| Order submission | `strategy_order_idempotency (strategy_account_id, client_order_id)` |
| Order row | `orders.order_id` ON CONFLICT UPDATE |
| Fill row | `fills.fill_id` ON CONFLICT DO NOTHING |
| Exit economic effect | `PlatformExitLedger.stable_fill_id()` — skip if fill exists |

Duplicate exchange fill reports must not double-count realized P&L or fees.

## Realized P&L

- Source: attributed `trades` where `user_id` and `strategy_account_id` are NOT NULL.
- **Per-leg accounting** for strangles (CE and PE independent).
- Example: CE sell 100 / buy 40 → +60; PE sell 120 / buy 150 → −30; trade gross = +30.
- Partial exits: `compute_leg_realized_pnl()` uses `min(entry_qty, exit_qty)`; remaining quantity stays OPEN.
- Fees: gross P&L − entry fees − exit fees = net (stored on leg and trade).

## Unrealized P&L

- Uses open attributed legs + account position mark prices.
- A symbol is included only if **uniquely** owned by one `strategy_account_id` on that exchange account.
- If two strategies share the same symbol on one account → `available: false` (no invented attribution).

## Emergency Unwind

- Classified as `EMERGENCY_UNWIND` with leg status `UNWOUND_ON_FAILURE`.
- Economic sign preserved (loss on failed entry unwind is negative when buy-back > entry).
- If CE was filled but strangle entry not ledgered, `ensure_attributed_leg_entry` writes entry before exit.

## Strategy Equity Snapshots

Written after attributed fills via `PlatformLedgerRepository.record_strategy_equity_snapshot()`:

- Scoped by `user_id`, `subscription_id`, `strategy_account_id`
- Fields: equity, realized_pnl, unrealized_pnl, metadata (fees, funding)

## Account vs Strategy vs Portfolio

| View | Source of truth |
|------|-----------------|
| **Account equity** | `exchange_accounts.equity` + sync equity curve |
| **Strategy P&L** | Attributed trades + strategy equity snapshots |
| **Combined portfolio equity** | Sum account equity **once per account** (no double counting) |
| **Combined portfolio realized** | Sum attributed strategy trades (not account equity) |

Do **not** sum strategy equity snapshots as independent account balances.

## APIs

| Endpoint | Scope |
|----------|-------|
| `GET /platform/trades` | User's attributed trades only |
| `GET /platform/strategies/{code}/performance` | User's subscribed strategy accounts |
| `GET /platform/portfolio/performance` | User's accounts + attributed strategy breakdown |

Optional `?benchmark=true` on strategy performance returns legacy global engine data separately.

## Security

All endpoints verify:

1. Authenticated user
2. Subscription ownership (via `subscriptions.user_id`)
3. Strategy account ownership (join subscription)
4. Exchange account ownership (for account filters)

## Legacy Handling

- Do not backfill NULL-attributed trades to users.
- Platform views filter `user_id IS NOT NULL AND strategy_account_id IS NOT NULL`.
