"""Performance Analytics Service computing historical and period metrics from PostgreSQL."""

import logging
from decimal import Decimal
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from collections import defaultdict

from sqlalchemy import select, and_

from src.persistence.db import DatabaseManager
from src.persistence.models import TradeModel
from src.analytics.ledger import TradeLedgerAnalytics


class PerformanceService:
    """Queries completed trades from PostgreSQL and computes comprehensive performance analytics."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        jsonl_path: str = "logs/trades.jsonl",
        logger: Optional[logging.Logger] = None,
    ):
        self.db = db_manager
        self.jsonl_path = jsonl_path
        self.logger = logger or logging.getLogger("performance_service")

    async def get_performance(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        strategy_name: Optional[str] = None,
        exchange: Optional[str] = None,
        fallback_history: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """
        Compute performance summary, drawdown, daily and monthly metrics.
        Queries PostgreSQL if available; gracefully falls back to JSONL ledger if offline.
        """
        # Parse date filters if provided
        parsed_from: Optional[date] = None
        parsed_to: Optional[date] = None
        if from_date:
            try:
                parsed_from = datetime.strptime(from_date.strip(), "%Y-%m-%d").date()
            except ValueError:
                pass
        if to_date:
            try:
                parsed_to = datetime.strptime(to_date.strip(), "%Y-%m-%d").date()
            except ValueError:
                pass

        # 1. Primary path: PostgreSQL
        if self.db and self.db.is_connected:
            try:
                trades = await self._query_db_completed_trades(
                    from_date=parsed_from,
                    to_date=parsed_to,
                    strategy_name=strategy_name,
                    exchange=exchange,
                )
                return self._compute_metrics_from_records(
                    records=trades,
                    from_date=from_date,
                    to_date=to_date,
                    source="postgresql",
                )
            except Exception as e:
                self.logger.warning(
                    f"⚠️ PostgreSQL query failed in PerformanceService: {e}. Falling back to JSONL ledger."
                )

        # 2. Fallback path: JSONL Ledger / Memory History
        return self._compute_fallback_metrics(
            from_date=from_date,
            to_date=to_date,
            strategy_name=strategy_name,
            fallback_history=fallback_history,
        )

    async def _query_db_completed_trades(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        strategy_name: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch completed trades ordered chronologically from PostgreSQL."""
        if not self.db:
            return []

        conditions = [TradeModel.status == "COMPLETED"]
        if from_date:
            conditions.append(TradeModel.trade_date >= from_date)
        if to_date:
            conditions.append(TradeModel.trade_date <= to_date)
        if strategy_name:
            conditions.append(TradeModel.strategy_name == strategy_name)
        if exchange:
            conditions.append(TradeModel.exchange == exchange)

        async with self.db.get_session() as session:
            stmt = (
                select(TradeModel)
                .where(and_(*conditions))
                .order_by(
                    TradeModel.trade_date.asc(),
                    TradeModel.exit_time.asc().nulls_last(),
                    TradeModel.created_at.asc(),
                )
            )
            res = await session.execute(stmt)
            trades = res.scalars().all()

            records = []
            for t in trades:
                records.append({
                    "trade_id": t.trade_id,
                    "strategy_name": t.strategy_name,
                    "exchange": t.exchange,
                    "trade_date": t.trade_date.isoformat(),
                    "status": t.status,
                    "realized_pnl": t.realized_pnl,
                    "total_fees": t.total_fees,
                    "net_pnl": t.net_pnl,
                    "exit_reason": t.exit_reason,
                    "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                    "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                })
            return records

    def _compute_metrics_from_records(
        self,
        records: List[Dict[str, Any]],
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        source: str = "postgresql",
    ) -> Dict[str, Any]:
        """Compute exact performance, streak, drawdown, daily and monthly aggregates using Decimal arithmetic."""
        trade_count = len(records)
        if trade_count == 0:
            return {
                "status": "ok",
                "source": source,
                "period": {"from": from_date, "to": to_date},
                "summary": {
                    "trade_count": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "breakeven_trades": 0,
                    "win_rate_pct": 0.0,
                    "gross_profit": "0.0000",
                    "gross_loss": "0.0000",
                    "total_realized_pnl": "0.0000",
                    "total_fees": "0.0000",
                    "net_pnl": "0.0000",
                    "profit_factor": 0.0,
                    "average_trade_pnl": "0.0000",
                    "average_winning_trade": "0.0000",
                    "average_losing_trade": "0.0000",
                    "largest_winning_trade": "0.0000",
                    "largest_losing_trade": "0.0000",
                    "max_consecutive_wins": 0,
                    "max_consecutive_losses": 0,
                },
                "drawdown": {
                    "current_cumulative_pnl": "0.0000",
                    "peak_cumulative_pnl": "0.0000",
                    "current_drawdown": "0.0000",
                    "max_drawdown": "0.0000",
                },
                "daily": [],
                "monthly": [],
            }

        # Aggregators using Decimal
        gross_profit = Decimal("0.0000")
        gross_loss = Decimal("0.0000")
        total_realized = Decimal("0.0000")
        total_fees = Decimal("0.0000")
        total_net = Decimal("0.0000")

        wins = 0
        losses = 0
        breakevens = 0

        largest_win = Decimal("0.0000")
        largest_loss = Decimal("0.0000")

        # Streak trackers
        current_win_streak = 0
        max_win_streak = 0
        current_loss_streak = 0
        max_loss_streak = 0

        # Drawdown trackers
        cum_pnl = Decimal("0.0000")
        peak_pnl = Decimal("0.0000")
        max_dd = Decimal("0.0000")

        # Grouping maps
        daily_map = defaultdict(lambda: {
            "trade_count": 0,
            "wins": 0,
            "losses": 0,
            "gross_profit": Decimal("0.0000"),
            "gross_loss": Decimal("0.0000"),
            "fees": Decimal("0.0000"),
            "net_pnl": Decimal("0.0000"),
        })

        monthly_map = defaultdict(lambda: {
            "trade_count": 0,
            "wins": 0,
            "losses": 0,
            "fees": Decimal("0.0000"),
            "net_pnl": Decimal("0.0000"),
        })

        for r in records:
            net_pnl = Decimal(str(r["net_pnl"]))
            realized_pnl = Decimal(str(r["realized_pnl"]))
            fees = Decimal(str(r["total_fees"]))
            d_str = r["trade_date"]
            m_str = d_str[:7] if len(d_str) >= 7 else "UNKNOWN"

            total_realized += realized_pnl
            total_fees += fees
            total_net += net_pnl

            # Daily & Monthly Bucketing
            daily_map[d_str]["trade_count"] += 1
            daily_map[d_str]["fees"] += fees
            daily_map[d_str]["net_pnl"] += net_pnl

            monthly_map[m_str]["trade_count"] += 1
            monthly_map[m_str]["fees"] += fees
            monthly_map[m_str]["net_pnl"] += net_pnl

            # Win/Loss Evaluation
            if net_pnl > 0:
                wins += 1
                gross_profit += net_pnl
                daily_map[d_str]["wins"] += 1
                daily_map[d_str]["gross_profit"] += net_pnl
                monthly_map[m_str]["wins"] += 1

                if net_pnl > largest_win:
                    largest_win = net_pnl

                current_win_streak += 1
                current_loss_streak = 0
                if current_win_streak > max_win_streak:
                    max_win_streak = current_win_streak

            elif net_pnl < 0:
                losses += 1
                abs_loss = abs(net_pnl)
                gross_loss += abs_loss
                daily_map[d_str]["losses"] += 1
                daily_map[d_str]["gross_loss"] += abs_loss
                monthly_map[m_str]["losses"] += 1

                if net_pnl < largest_loss:
                    largest_loss = net_pnl

                current_loss_streak += 1
                current_win_streak = 0
                if current_loss_streak > max_loss_streak:
                    max_loss_streak = current_loss_streak

            else:
                breakevens += 1
                current_win_streak = 0
                current_loss_streak = 0

            # Drawdown Progression
            cum_pnl += net_pnl
            if cum_pnl > peak_pnl:
                peak_pnl = cum_pnl
            current_dd = peak_pnl - cum_pnl
            if current_dd > max_dd:
                max_dd = current_dd

        # Derived Ratios
        win_rate_pct = round((wins / trade_count) * 100.0, 2) if trade_count > 0 else 0.0
        
        if gross_loss > 0:
            profit_factor = round(float(gross_profit / gross_loss), 4)
        elif gross_profit > 0:
            profit_factor = round(float(gross_profit), 4)
        else:
            profit_factor = 0.0

        avg_trade_pnl = total_net / trade_count if trade_count > 0 else Decimal("0.0000")
        avg_win = gross_profit / wins if wins > 0 else Decimal("0.0000")
        avg_loss = -gross_loss / losses if losses > 0 else Decimal("0.0000")

        # Format Daily Array
        daily_list = []
        for d in sorted(daily_map.keys()):
            st = daily_map[d]
            daily_list.append({
                "date": d,
                "trade_count": st["trade_count"],
                "wins": st["wins"],
                "losses": st["losses"],
                "gross_profit": f"{st['gross_profit']:.4f}",
                "gross_loss": f"{st['gross_loss']:.4f}",
                "fees": f"{st['fees']:.4f}",
                "net_pnl": f"{st['net_pnl']:.4f}",
            })

        # Format Monthly Array
        monthly_list = []
        for m in sorted(monthly_map.keys()):
            st = monthly_map[m]
            m_win_rate = round((st["wins"] / st["trade_count"]) * 100.0, 2) if st["trade_count"] > 0 else 0.0
            monthly_list.append({
                "month": m,
                "trade_count": st["trade_count"],
                "wins": st["wins"],
                "losses": st["losses"],
                "fees": f"{st['fees']:.4f}",
                "net_pnl": f"{st['net_pnl']:.4f}",
                "win_rate_pct": f"{m_win_rate:.2f}%",
            })

        return {
            "status": "ok",
            "source": source,
            "period": {"from": from_date, "to": to_date},
            "summary": {
                "trade_count": trade_count,
                "winning_trades": wins,
                "losing_trades": losses,
                "breakeven_trades": breakevens,
                "win_rate_pct": f"{win_rate_pct:.2f}%",
                "gross_profit": f"{gross_profit:.4f}",
                "gross_loss": f"{gross_loss:.4f}",
                "total_realized_pnl": f"{total_realized:.4f}",
                "total_fees": f"{total_fees:.4f}",
                "net_pnl": f"{total_net:.4f}",
                "profit_factor": f"{profit_factor:.4f}",
                "average_trade_pnl": f"{avg_trade_pnl:.4f}",
                "average_winning_trade": f"{avg_win:.4f}",
                "average_losing_trade": f"{avg_loss:.4f}",
                "largest_winning_trade": f"{largest_win:.4f}",
                "largest_losing_trade": f"{largest_loss:.4f}",
                "max_consecutive_wins": max_win_streak,
                "max_consecutive_losses": max_loss_streak,
            },
            "drawdown": {
                "current_cumulative_pnl": f"{cum_pnl:.4f}",
                "peak_cumulative_pnl": f"{peak_pnl:.4f}",
                "current_drawdown": f"{(peak_pnl - cum_pnl):.4f}",
                "max_drawdown": f"{max_dd:.4f}",
            },
            "daily": daily_list,
            "monthly": monthly_list,
        }

    def _compute_fallback_metrics(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        strategy_name: Optional[str] = None,
        fallback_history: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Fallback to parsing trades.jsonl and history when PostgreSQL is unavailable."""
        analytics = TradeLedgerAnalytics(trades_log_path=self.jsonl_path, logger=self.logger)
        raw_trades = analytics.load_completed_trades(fallback_history=fallback_history)

        filtered_records = []
        for t in raw_trades:
            t_strat = t.get("strategy_name", "short_strangle")
            if strategy_name and t_strat != strategy_name:
                continue

            t_date_str = t.get("trade_date") or str(t.get("created_at", ""))[:10]
            if from_date and t_date_str < from_date:
                continue
            if to_date and t_date_str > to_date:
                continue

            realized = Decimal(str(t.get("total_realized_pnl", 0.0)))
            fees = Decimal(str(t.get("total_fees", 0.0)))
            net = realized - fees

            filtered_records.append({
                "trade_id": t.get("strategy_trade_id", "UNKNOWN"),
                "strategy_name": t_strat,
                "exchange": "delta_india",
                "trade_date": t_date_str,
                "status": "COMPLETED",
                "realized_pnl": realized,
                "total_fees": fees,
                "net_pnl": net,
                "exit_reason": t.get("exit_reason"),
            })

        return self._compute_metrics_from_records(
            records=filtered_records,
            from_date=from_date,
            to_date=to_date,
            source="jsonl_fallback",
        )
