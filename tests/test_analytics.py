"""Tests for TradeLedgerAnalytics daily, monthly P&L and win/loss statistics."""

import pytest
from src.analytics.ledger import TradeLedgerAnalytics


def test_trade_ledger_daily_and_monthly_pnl():
    sample_trades = [
        {
            "strategy_trade_id": "STR_1",
            "trade_date": "2026-09-01",
            "total_realized_pnl": 150.0,
            "total_fees": 1.5,
        },
        {
            "strategy_trade_id": "STR_2",
            "trade_date": "2026-09-01",
            "total_realized_pnl": -50.0,
            "total_fees": 1.5,
        },
        {
            "strategy_trade_id": "STR_3",
            "trade_date": "2026-09-02",
            "total_realized_pnl": 100.0,
            "total_fees": 1.0,
        },
        {
            "strategy_trade_id": "STR_4",
            "trade_date": "2026-10-01",
            "total_realized_pnl": 200.0,
            "total_fees": 2.0,
        },
    ]

    analytics = TradeLedgerAnalytics(trades_log_path="non_existent.jsonl")

    # 1. Daily PnL
    daily = analytics.compute_daily_pnl(sample_trades)
    assert len(daily) == 3

    d1 = [d for d in daily if d["date"] == "2026-09-01"][0]
    assert d1["realized_pnl"] == 100.0
    assert d1["fees"] == 3.0
    assert d1["net_pnl"] == 97.0
    assert d1["trades_count"] == 2
    assert d1["wins"] == 1
    assert d1["losses"] == 1

    d2 = [d for d in daily if d["date"] == "2026-09-02"][0]
    assert d2["realized_pnl"] == 100.0
    assert d2["net_pnl"] == 99.0

    # 2. Monthly PnL
    monthly = analytics.compute_monthly_pnl(sample_trades)
    assert len(monthly) == 2

    m_sep = [m for m in monthly if m["month"] == "2026-09"][0]
    assert m_sep["realized_pnl"] == 200.0
    assert m_sep["fees"] == 4.0
    assert m_sep["net_pnl"] == 196.0
    assert m_sep["trades_count"] == 3
    assert m_sep["wins"] == 2
    assert m_sep["losses"] == 1
    assert m_sep["win_rate_pct"] == 66.67

    m_oct = [m for m in monthly if m["month"] == "2026-10"][0]
    assert m_oct["net_pnl"] == 198.0
    assert m_oct["win_rate_pct"] == 100.0

    # 3. Summary Stats
    summary = analytics.compute_summary_statistics(sample_trades)
    assert summary["total_trades"] == 4
    assert summary["winning_trades"] == 3
    assert summary["losing_trades"] == 1
    assert summary["win_rate_pct"] == 75.0
    assert summary["total_realized_pnl"] == 400.0
    assert summary["total_fees"] == 6.0
    assert summary["net_pnl"] == 394.0
    assert summary["gross_profit"] == 450.0
    assert summary["gross_loss"] == 50.0
    assert summary["profit_factor"] == 9.0
