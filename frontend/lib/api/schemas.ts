import { z } from "zod";

// Health & Readiness Schemas
export const HealthResponseSchema = z.object({
  status: z.string(),
});

export const ReadinessResponseSchema = z.object({
  ready: z.boolean(),
  engine: z.enum(["RUNNING", "STOPPED", "SAFE_HALT"]).or(z.string()),
  exchange: z.enum(["AVAILABLE", "UNAVAILABLE"]).or(z.string()),
  reconciliation: z.enum(["SYNCHRONIZED", "UNSYNCHRONIZED", "SAFE_HALT"]).or(z.string()),
});

// Strategy Leg Schema
export const StrategyLegSchema = z.object({
  leg_id: z.string().optional(),
  option_type: z.string().optional(),
  symbol: z.string().optional(),
  strike: z.number().optional(),
  quantity: z.number().optional(),
  entry_fill_price: z.number().nullable().optional(),
  current_price: z.number().nullable().optional(),
  sl_price: z.number().nullable().optional(),
  status: z.string().optional(),
  bracket_order_id: z.string().nullable().optional(),
  exchange_sl_active: z.boolean().optional(),
});

// Current Trade Schema
export const CurrentTradeSchema = z.object({
  trade_id: z.string(),
  strategy_name: z.string().default("short_strangle"),
  trade_state: z.string().default("ACTIVE"),
  entry_timestamp: z.string().nullable().optional().default(""),
  ce_symbol: z.string().optional(),
  pe_symbol: z.string().optional(),
  ce_status: z.string().optional(),
  pe_status: z.string().optional(),
  ce_strike: z.number().optional(),
  pe_strike: z.number().optional(),
  ce_quantity: z.number().optional(),
  pe_quantity: z.number().optional(),
  ce_entry_price: z.number().nullable().optional(),
  pe_entry_price: z.number().nullable().optional(),
  ce_current_price: z.number().nullable().optional(),
  pe_current_price: z.number().nullable().optional(),
  ce_unrealized_pnl: z.coerce.number().optional(),
  pe_unrealized_pnl: z.coerce.number().optional(),
  ce_sl_price: z.number().nullable().optional(),
  pe_sl_price: z.number().nullable().optional(),
  ce_native_bracket_active: z.boolean().optional(),
  pe_native_bracket_active: z.boolean().optional(),
  ce_bracket_order_id: z.string().nullable().optional(),
  pe_bracket_order_id: z.string().nullable().optional(),
  total_realized_pnl: z.coerce.number().optional(),
  total_unrealized_pnl: z.coerce.number().optional(),
}).nullable();


// Alert Item Schema
export const AlertItemSchema = z.object({
  timestamp: z.string(),
  severity: z.enum(["CRITICAL", "WARNING", "INFO", "SUCCESS"]).or(z.string()),
  event: z.string(),
  message: z.string(),
  trade_id: z.string().optional(),
});

export const RenkoSnapshotSchema = z.object({
  enabled: z.boolean().optional(),
  account: z.string().optional(),
  symbol: z.string().optional(),
  configured_symbol: z.string().optional(),
  position: z.number().optional(),
  entry_price: z.number().nullable().optional(),
  entry_order_id: z.union([z.string(), z.number()]).nullable().optional(),
  active_trade_id: z.string().nullable().optional(),
  bricks: z.number().optional(),
  last_processed_candle_time: z.string().nullable().optional(),
  instrument_id: z.number().nullable().optional(),
  position_size: z.number().optional(),
  orders_halted: z.boolean().optional(),
  halt_reason: z.string().nullable().optional(),
  in_flight_client_order_id: z.string().nullable().optional(),
}).nullable();

export const RenkoTradeLegSchema = z.object({
  leg_id: z.string().optional(),
  leg_type: z.string().optional(),
  symbol: z.string().optional(),
  side: z.string().optional(),
  quantity: z.number().optional(),
  entry_price: z.number().nullable().optional(),
  exit_price: z.number().nullable().optional(),
  realized_pnl: z.number().optional(),
  status: z.string().optional(),
});

export const RenkoTradeRecordSchema = z.object({
  trade_id: z.string(),
  strategy_name: z.string().optional(),
  exchange: z.string().optional(),
  trade_date: z.string().optional(),
  status: z.string(),
  entry_time: z.string().nullable().optional(),
  exit_time: z.string().nullable().optional(),
  realized_pnl: z.number().optional(),
  net_pnl: z.number().optional(),
  total_fees: z.number().optional(),
  exit_reason: z.string().nullable().optional(),
  strategy_config: z.record(z.any()).optional(),
  legs: z.array(RenkoTradeLegSchema).default([]),
});

export const RenkoTradesResponseSchema = z.object({
  connected: z.boolean().default(false),
  open_trade: RenkoTradeRecordSchema.nullable().optional(),
  trades: z.array(RenkoTradeRecordSchema).default([]),
});

// Comprehensive System Status Schema
export const SystemStatusSchema = z.object({
  engine: z.object({
    status: z.enum(["RUNNING", "STOPPED", "SAFE_HALT"]).or(z.string()),
    uptime_seconds: z.number().default(0),
    start_time: z.string().nullable().optional(),
    environment: z.enum(["TESTNET", "LIVE"]).or(z.string()),
    dry_run: z.boolean().default(false),
    kill_switch: z.boolean().default(false),
    strategy_name: z.string().default("short_strangle"),
    strategy_active: z.boolean().default(false),
  }),
  exchange: z.object({
    rest_connected: z.boolean().default(false),
    ws_connected: z.boolean().default(false),
    last_rest_request_time: z.string().nullable().optional(),
    last_ws_tick_time: z.string().nullable().optional(),
    ws_stale: z.boolean().default(false),
  }),
  reconciliation: z.object({
    is_synchronized: z.boolean().default(true),
    status: z.enum(["SYNCHRONIZED", "UNSYNCHRONIZED", "SAFE_HALT"]).or(z.string()),
    last_reconciliation_time: z.string().nullable().optional(),
    latest_discrepancy: z.string().nullable().optional(),
  }),
  database: z.object({
    connected: z.boolean().default(false),
    status: z.string().default("UNKNOWN"),
    last_db_operation: z.string().nullable().optional(),
  }),
  watchdog: z.object({
    last_heartbeat: z.string().nullable().optional(),
    last_loop: z.string().nullable().optional(),
  }),
  current_trade: CurrentTradeSchema.optional(),
  strategies: z
    .object({
      existing: z
        .object({
          name: z.string().optional(),
          enabled: z.boolean().optional(),
          account: z.string().optional(),
          active: z.boolean().optional(),
        })
        .optional(),
      renko_ichimoku: RenkoSnapshotSchema.optional(),
    })
    .optional(),
  alerts: z.object({
    recent_count: z.number().default(0),
    recent_alerts: z.array(AlertItemSchema).default([]),
  }).default({ recent_count: 0, recent_alerts: [] }),
  status: z.string().optional(),
  environment: z.string().optional(),
  kill_switch: z.boolean().optional(),
  connected_exchange: z.boolean().optional(),
  strategy: z.string().optional(),
  strategy_active: z.boolean().optional(),
  trading_enabled: z.boolean().optional(),
  underlying: z.string().optional(),
});

// Performance Analytics Schemas
export const CumulativePnlPointSchema = z.object({
  trade_id: z.string(),
  trade_date: z.string(),
  realized_pnl: z.number().default(0),
  net_pnl: z.number().default(0),
  cumulative_pnl: z.number().default(0),
  drawdown: z.number().default(0),
  drawdown_pct: z.number().default(0),
});

export const DailyPnlPointSchema = z.object({
  date: z.string(),
  trades_count: z.number().default(0),
  realized_pnl: z.number().default(0),
  fees: z.number().default(0),
  net_pnl: z.number().default(0),
  win_rate: z.number().default(0),
});

export const MonthlyPnlPointSchema = z.object({
  month: z.string(),
  trades_count: z.number().default(0),
  realized_pnl: z.number().default(0),
  fees: z.number().default(0),
  net_pnl: z.number().default(0),
  win_rate: z.number().default(0),
});

export const PerformanceMetricsSchema = z.object({
  total_trades: z.number().default(0),
  winning_trades: z.number().default(0),
  losing_trades: z.number().default(0),
  breakeven_trades: z.number().default(0),
  win_rate: z.number().default(0),
  loss_rate: z.number().default(0),
  total_realized_pnl: z.number().default(0),
  total_fees: z.number().default(0),
  net_pnl: z.number().default(0),
  gross_profit: z.number().default(0),
  gross_loss: z.number().default(0),
  profit_factor: z.number().default(0),
  average_trade_pnl: z.number().default(0),
  average_win: z.number().default(0),
  average_loss: z.number().default(0),
  payoff_ratio: z.number().default(0),
  max_drawdown_amount: z.number().default(0),
  max_drawdown_pct: z.number().default(0),
  sharpe_ratio: z.number().default(0),
  sortino_ratio: z.number().default(0),
  calmar_ratio: z.number().default(0),
  current_streak: z.number().default(0),
  max_consecutive_wins: z.number().default(0),
  max_consecutive_losses: z.number().default(0),
  largest_winning_trade: z.number().default(0),
  largest_losing_trade: z.number().default(0),
  cumulative_pnl_curve: z.array(CumulativePnlPointSchema).default([]),
  daily_pnl: z.array(DailyPnlPointSchema).default([]),
  monthly_pnl: z.array(MonthlyPnlPointSchema).default([]),
  strategy_breakdown: z.record(z.any()).default({}),
  exchange_breakdown: z.record(z.any()).default({}),
});

// Infer TypeScript types from Zod
export type RenkoSnapshot = z.infer<typeof RenkoSnapshotSchema>;
export type RenkoTradeRecord = z.infer<typeof RenkoTradeRecordSchema>;
export type RenkoTradesResponse = z.infer<typeof RenkoTradesResponseSchema>;
export type HealthResponse = z.infer<typeof HealthResponseSchema>;
export type ReadinessResponse = z.infer<typeof ReadinessResponseSchema>;
export type SystemStatusResponse = z.infer<typeof SystemStatusSchema>;
export type PerformanceMetricsResponse = z.infer<typeof PerformanceMetricsSchema>;
export type CumulativePnlPoint = z.infer<typeof CumulativePnlPointSchema>;
export type DailyPnlPoint = z.infer<typeof DailyPnlPointSchema>;
export type MonthlyPnlPoint = z.infer<typeof MonthlyPnlPointSchema>;
