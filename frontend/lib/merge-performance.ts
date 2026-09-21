import type {
  CumulativePnlPoint,
  DailyPnlPoint,
  MonthlyPnlPoint,
  PerformanceMetricsResponse,
} from "@/lib/api/schemas";

function sumKeyed<T extends Record<string, any>>(
  rows: T[][],
  key: keyof T,
  numericKeys: (keyof T)[]
): T[] {
  const map = new Map<string, T>();
  for (const list of rows) {
    for (const row of list || []) {
      const id = String(row[key] ?? "");
      if (!id) continue;
      const cur = map.get(id);
      if (!cur) {
        map.set(id, { ...row });
        continue;
      }
      const next = { ...cur };
      for (const nk of numericKeys) {
        (next as any)[nk] = Number(cur[nk] || 0) + Number(row[nk] || 0);
      }
      map.set(id, next);
    }
  }
  return Array.from(map.values()).sort((a, b) => String(a[key]).localeCompare(String(b[key])));
}

export function mergePerformanceMetrics(
  parts: Array<PerformanceMetricsResponse | null | undefined>
): PerformanceMetricsResponse | null {
  const live = parts.filter((p): p is PerformanceMetricsResponse => Boolean(p));
  if (live.length === 0) return null;
  if (live.length === 1) return live[0];

  const totalTrades = live.reduce((s, p) => s + (p.total_trades || 0), 0);
  const winning = live.reduce((s, p) => s + (p.winning_trades || 0), 0);
  const losing = live.reduce((s, p) => s + (p.losing_trades || 0), 0);
  const fees = live.reduce((s, p) => s + (p.total_fees || 0), 0);
  const net = live.reduce((s, p) => s + (p.net_pnl || 0), 0);
  const realized = live.reduce((s, p) => s + (p.total_realized_pnl || 0), 0);
  const grossProfit = live.reduce((s, p) => s + (p.gross_profit || 0), 0);
  const grossLoss = live.reduce((s, p) => s + (p.gross_loss || 0), 0);

  const curveSrc = live
    .flatMap((p) => p.cumulative_pnl_curve || [])
    .sort((a, b) => String(a.trade_date).localeCompare(String(b.trade_date)));
  let cum = 0;
  let peak = 0;
  const cumulative_pnl_curve: CumulativePnlPoint[] = curveSrc.map((pt) => {
    cum += Number(pt.net_pnl || 0);
    peak = Math.max(peak, cum);
    const dd = peak - cum;
    return {
      ...pt,
      cumulative_pnl: cum,
      drawdown: dd,
      drawdown_pct: peak > 0 ? (dd / peak) * 100 : 0,
    };
  });

  return {
    ...live[0],
    total_trades: totalTrades,
    winning_trades: winning,
    losing_trades: losing,
    breakeven_trades: live.reduce((s, p) => s + (p.breakeven_trades || 0), 0),
    win_rate: totalTrades > 0 ? (winning / totalTrades) * 100 : 0,
    loss_rate: totalTrades > 0 ? (losing / totalTrades) * 100 : 0,
    total_realized_pnl: realized,
    total_fees: fees,
    net_pnl: net,
    gross_profit: grossProfit,
    gross_loss: grossLoss,
    profit_factor: grossLoss !== 0 ? Math.abs(grossProfit / grossLoss) : 0,
    average_trade_pnl: totalTrades > 0 ? net / totalTrades : 0,
    max_drawdown_amount: Math.max(...live.map((p) => p.max_drawdown_amount || 0), 0),
    max_drawdown_pct: Math.max(...live.map((p) => p.max_drawdown_pct || 0), 0),
    cumulative_pnl_curve,
    daily_pnl: sumKeyed(live.map((p) => p.daily_pnl || []), "date", [
      "trades_count",
      "realized_pnl",
      "fees",
      "net_pnl",
    ]) as DailyPnlPoint[],
    monthly_pnl: sumKeyed(live.map((p) => p.monthly_pnl || []), "month", [
      "trades_count",
      "realized_pnl",
      "fees",
      "net_pnl",
    ]) as MonthlyPnlPoint[],
  };
}
