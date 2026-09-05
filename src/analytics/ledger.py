"""Simple trade ledger analytics computing daily and monthly P&L from trade records."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict


class TradeLedgerAnalytics:
    """Reads structured trade ledger and computes daily/monthly performance metrics."""

    def __init__(self, trades_log_path: str = "logs/trades.jsonl", logger: Optional[logging.Logger] = None):
        self.trades_log_path = Path(trades_log_path)
        self.logger = logger or logging.getLogger("trade_ledger_analytics")

    def load_completed_trades(self, fallback_history: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Load completed trades from logs/trades.jsonl or fallback to memory state history."""
        trades = []

        if self.trades_log_path.exists():
            try:
                with open(self.trades_log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                            if record.get("event_type") == "TRADE_COMPLETED":
                                trades.append(record.get("trade_data", {}))
                        except Exception:
                            continue
            except Exception as e:
                self.logger.warning(f"Error reading trade ledger {self.trades_log_path}: {e}")

        # If trades.jsonl is empty or missing, fallback to history objects
        if not trades and fallback_history:
            for item in fallback_history:
                trades.append(item.to_dict() if hasattr(item, "to_dict") else item)

        return trades

    def compute_daily_pnl(self, trades: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Calculate realized P&L, fees, and net return aggregated by day (YYYY-MM-DD)."""
        trade_list = trades if trades is not None else self.load_completed_trades()
        daily_map = defaultdict(lambda: {"realized_pnl": 0.0, "fees": 0.0, "trades_count": 0, "wins": 0, "losses": 0})

        for t in trade_list:
            trade_date = t.get("trade_date") or str(t.get("created_at", ""))[:10] or "UNKNOWN"
            pnl = float(t.get("total_realized_pnl", 0.0))
            fees = float(t.get("total_fees", 0.0))

            daily_map[trade_date]["realized_pnl"] += pnl
            daily_map[trade_date]["fees"] += fees
            daily_map[trade_date]["trades_count"] += 1
            if pnl > 0:
                daily_map[trade_date]["wins"] += 1
            elif pnl < 0:
                daily_map[trade_date]["losses"] += 1

        result = []
        for date_str in sorted(daily_map.keys()):
            stats = daily_map[date_str]
            net_pnl = stats["realized_pnl"] - stats["fees"]
            result.append({
                "date": date_str,
                "realized_pnl": round(stats["realized_pnl"], 4),
                "fees": round(stats["fees"], 4),
                "net_pnl": round(net_pnl, 4),
                "trades_count": stats["trades_count"],
                "wins": stats["wins"],
                "losses": stats["losses"],
            })

        return result

    def compute_monthly_pnl(self, trades: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Calculate realized P&L, fees, and net return aggregated by month (YYYY-MM)."""
        trade_list = trades if trades is not None else self.load_completed_trades()
        monthly_map = defaultdict(lambda: {"realized_pnl": 0.0, "fees": 0.0, "trades_count": 0, "wins": 0, "losses": 0})

        for t in trade_list:
            trade_date = t.get("trade_date") or str(t.get("created_at", ""))[:10]
            month_str = trade_date[:7] if len(trade_date) >= 7 else "UNKNOWN"
            pnl = float(t.get("total_realized_pnl", 0.0))
            fees = float(t.get("total_fees", 0.0))

            monthly_map[month_str]["realized_pnl"] += pnl
            monthly_map[month_str]["fees"] += fees
            monthly_map[month_str]["trades_count"] += 1
            if pnl > 0:
                monthly_map[month_str]["wins"] += 1
            elif pnl < 0:
                monthly_map[month_str]["losses"] += 1

        result = []
        for month_str in sorted(monthly_map.keys()):
            stats = monthly_map[month_str]
            net_pnl = stats["realized_pnl"] - stats["fees"]
            win_rate = (stats["wins"] / stats["trades_count"] * 100) if stats["trades_count"] > 0 else 0.0
            result.append({
                "month": month_str,
                "realized_pnl": round(stats["realized_pnl"], 4),
                "fees": round(stats["fees"], 4),
                "net_pnl": round(net_pnl, 4),
                "trades_count": stats["trades_count"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "win_rate_pct": round(win_rate, 2),
            })

        return result

    def compute_summary_statistics(self, trades: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Calculate overall summary statistics: total P&L, win rate, total trades, profit factor."""
        trade_list = trades if trades is not None else self.load_completed_trades()
        if not trade_list:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate_pct": 0.0,
                "total_realized_pnl": 0.0,
                "total_fees": 0.0,
                "net_pnl": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "profit_factor": 0.0,
            }

        total_pnl = 0.0
        total_fees = 0.0
        wins = 0
        losses = 0
        gross_profit = 0.0
        gross_loss = 0.0

        for t in trade_list:
            pnl = float(t.get("total_realized_pnl", 0.0))
            fees = float(t.get("total_fees", 0.0))
            total_pnl += pnl
            total_fees += fees

            if pnl > 0:
                wins += 1
                gross_profit += pnl
            elif pnl < 0:
                losses += 1
                gross_loss += abs(pnl)

        total_trades = len(trade_list)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

        return {
            "total_trades": total_trades,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate_pct": round(win_rate, 2),
            "total_realized_pnl": round(total_pnl, 4),
            "total_fees": round(total_fees, 4),
            "net_pnl": round(total_pnl - total_fees, 4),
            "gross_profit": round(gross_profit, 4),
            "gross_loss": round(gross_loss, 4),
            "profit_factor": round(profit_factor, 2),
        }
