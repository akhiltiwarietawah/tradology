export type EngineStatusType = "RUNNING" | "STOPPED" | "SAFE_HALT";
export type EnvironmentType = "TESTNET" | "LIVE";
export type SyncStatusType = "SYNCHRONIZED" | "UNSYNCHRONIZED" | "SAFE_HALT";

export interface SystemStatus {
  engine: {
    status: EngineStatusType;
    uptime_seconds: number;
    start_time: string | null;
    environment: EnvironmentType;
    dry_run: boolean;
    kill_switch: boolean;
    strategy_name: string;
    strategy_active: boolean;
  };
  exchange: {
    rest_connected: boolean;
    ws_connected: boolean;
    last_rest_request_time: string | null;
    last_ws_tick_time: string | null;
    ws_stale: boolean;
  };
  reconciliation: {
    is_synchronized: boolean;
    status: SyncStatusType;
    last_reconciliation_time: string | null;
    latest_discrepancy: string | null;
  };
  database: {
    connected: boolean;
    status: string;
    last_db_operation: string | null;
  };
  watchdog: {
    last_heartbeat: string | null;
    last_loop: string | null;
  };
  current_trade: {
    trade_id: string;
    strategy_name: string;
    trade_state: string;
    entry_timestamp: string;
    ce_symbol?: string;
    pe_symbol?: string;
    ce_status?: string;
    pe_status?: string;
    ce_strike?: number;
    pe_strike?: number;
    ce_entry_price?: number;
    pe_entry_price?: number;
    ce_current_price?: number;
    pe_current_price?: number;
    ce_unrealized_pnl?: number;
    pe_unrealized_pnl?: number;
    ce_quantity?: number;
    pe_quantity?: number;
    ce_sl_price?: number;
    pe_sl_price?: number;
    ce_native_bracket_active?: boolean;
    pe_native_bracket_active?: boolean;
    ce_bracket_order_id?: string;
    pe_bracket_order_id?: string;
    total_realized_pnl?: number;
    total_unrealized_pnl?: number;
  } | null;
  alerts: {
    recent_count: number;
    recent_alerts: Array<{
      timestamp: string;
      severity: "CRITICAL" | "WARNING" | "INFO" | "SUCCESS";
      event: string;
      message: string;
      trade_id?: string;
    }>;
  };
  status: string;
  environment: string;
  kill_switch: boolean;
  connected_exchange: boolean;
  strategy: string;
  strategy_active: boolean;
  trading_enabled: boolean;
  underlying: string;
}

export interface PerformanceMetrics {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  breakeven_trades: number;
  win_rate: number;
  loss_rate: number;
  total_realized_pnl: number;
  total_fees: number;
  net_pnl: number;
  gross_profit: number;
  gross_loss: number;
  profit_factor: number;
  average_trade_pnl: number;
  average_win: number;
  average_loss: number;
  payoff_ratio: number;
  max_drawdown_amount: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  current_streak: number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  largest_winning_trade: number;
  largest_losing_trade: number;
  cumulative_pnl_curve: Array<{
    trade_id: string;
    trade_date: string;
    realized_pnl: number;
    net_pnl: number;
    cumulative_pnl: number;
    drawdown: number;
    drawdown_pct: number;
  }>;
  daily_pnl: Array<{
    date: string;
    trades_count: number;
    realized_pnl: number;
    fees: number;
    net_pnl: number;
    win_rate: number;
  }>;
  monthly_pnl: Array<{
    month: string;
    trades_count: number;
    realized_pnl: number;
    fees: number;
    net_pnl: number;
    win_rate: number;
  }>;
  strategy_breakdown: Record<string, any>;
  exchange_breakdown: Record<string, any>;
}

export interface ReadinessStatus {
  ready: boolean;
  engine: EngineStatusType;
  exchange: "AVAILABLE" | "UNAVAILABLE";
  reconciliation: "SYNCHRONIZED" | "UNSYNCHRONIZED";
}
