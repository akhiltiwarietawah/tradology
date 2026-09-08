"""Unit and integration tests for PerformanceService analytics, metrics, drawdown, and filters."""

import pytest
from decimal import Decimal
from datetime import datetime, date, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import text

from src.persistence.db import DatabaseManager
from src.persistence.trade_repository import TradeRepository
from src.analytics.performance import PerformanceService
from src.core.models.trade import StrategyTrade, StrategyLeg, StrategyState, LegStatus
from src.core.models.instrument import OptionType


async def insert_completed_trade(
    db_mgr: DatabaseManager,
    trade_id: str,
    trade_date: str,
    realized_pnl: float,
    fees: float = 0.0,
    strategy_name: str = "short_strangle",
    exchange: str = "delta_india",
    status: str = "COMPLETED",
    exit_time: Optional[datetime] = None,
):
    """Helper to insert a synthetic trade record for performance testing."""
    repo = TradeRepository(db_manager=db_mgr)
    trade = StrategyTrade(
        strategy_trade_id=trade_id,
        strategy_name=strategy_name,
        trade_date=trade_date,
        state=StrategyState.COMPLETED if status == "COMPLETED" else StrategyState.ACTIVE,
        ce_leg=StrategyLeg(
            leg_id=f"{trade_id}_CE",
            option_type=OptionType.CALL,
            instrument_id="150401",
            symbol="C-BTC-98000-010926",
            strike=98000.0,
            expiry_date=trade_date,
            quantity=1.0,
            intended_premium=100.0,
            entry_timestamp=datetime.now(timezone.utc).isoformat(),
            entry_fill_price=100.0,
            exit_price=100.0 - realized_pnl,
            exit_timestamp=(exit_time or datetime.now(timezone.utc)).isoformat(),
            fees=fees,
            realized_pnl=realized_pnl,
            status=LegStatus.FORCE_CLOSED if status == "COMPLETED" else LegStatus.OPEN,
        ),
    )
    trade.total_realized_pnl = realized_pnl
    trade.state = StrategyState(status)
    await repo.upsert_trade(trade, exchange=exchange)



@pytest.mark.asyncio
async def test_empty_database_metrics(perf_db):
    """Verify that an empty database returns clean zeros and empty arrays."""
    service, _ = perf_db
    res = await service.get_performance()

    assert res["status"] == "ok"
    assert res["source"] == "postgresql"
    assert res["summary"]["trade_count"] == 0
    assert res["summary"]["winning_trades"] == 0
    assert res["summary"]["win_rate_pct"] == 0.0
    assert res["summary"]["net_pnl"] == "0.0000"
    assert res["drawdown"]["max_drawdown"] == "0.0000"
    assert res["daily"] == []
    assert res["monthly"] == []


@pytest.mark.asyncio
async def test_single_winning_trade(perf_db):
    """Verify metrics for a single winning trade."""
    service, db_mgr = perf_db
    await insert_completed_trade(db_mgr, "T_WIN", "2026-09-01", realized_pnl=100.0, fees=5.0)

    res = await service.get_performance()
    summary = res["summary"]
    assert summary["trade_count"] == 1
    assert summary["winning_trades"] == 1
    assert summary["losing_trades"] == 0
    assert summary["win_rate_pct"] == "100.00%"
    assert summary["gross_profit"] == "95.0000"
    assert summary["gross_loss"] == "0.0000"
    assert summary["total_fees"] == "5.0000"
    assert summary["net_pnl"] == "95.0000"
    assert summary["profit_factor"] == "95.0000"
    assert res["drawdown"]["max_drawdown"] == "0.0000"


@pytest.mark.asyncio
async def test_single_losing_trade(perf_db):
    """Verify metrics for a single losing trade."""
    service, db_mgr = perf_db
    await insert_completed_trade(db_mgr, "T_LOSS", "2026-09-01", realized_pnl=-100.0, fees=5.0)

    res = await service.get_performance()
    summary = res["summary"]
    assert summary["trade_count"] == 1
    assert summary["winning_trades"] == 0
    assert summary["losing_trades"] == 1
    assert summary["win_rate_pct"] == "0.00%"
    assert summary["gross_profit"] == "0.0000"
    assert summary["gross_loss"] == "105.0000"
    assert summary["total_fees"] == "5.0000"
    assert summary["net_pnl"] == "-105.0000"
    assert summary["profit_factor"] == "0.0000"
    assert res["drawdown"]["max_drawdown"] == "105.0000"


@pytest.mark.asyncio
async def test_mixed_trades_profit_factor_and_drawdown(perf_db):
    """
    Verify complete calculations on a sequence of trades:
    P&L sequence: +100, +50, -80, -120, +200 (fees = 0 for simplicity)
    Cumulative curve: 100 -> 150 (peak) -> 70 (dd 80) -> -50 (dd 200) -> 150 (dd 0)
    """
    service, db_mgr = perf_db
    trades = [
        ("T1", "2026-09-01", 100.0),
        ("T2", "2026-09-02", 50.0),
        ("T3", "2026-09-03", -80.0),
        ("T4", "2026-09-04", -120.0),
        ("T5", "2026-09-05", 200.0),
    ]
    for tid, dt, pnl in trades:
        await insert_completed_trade(db_mgr, tid, dt, realized_pnl=pnl, fees=0.0)

    res = await service.get_performance()
    summary = res["summary"]
    dd = res["drawdown"]

    assert summary["trade_count"] == 5
    assert summary["winning_trades"] == 3
    assert summary["losing_trades"] == 2
    assert summary["win_rate_pct"] == "60.00%"
    assert summary["gross_profit"] == "350.0000"
    assert summary["gross_loss"] == "200.0000"
    assert summary["net_pnl"] == "150.0000"
    assert summary["profit_factor"] == "1.7500"  # 350 / 200 = 1.75
    assert summary["average_winning_trade"] == "116.6667"  # 350 / 3
    assert summary["average_losing_trade"] == "-100.0000"  # -200 / 2
    assert summary["max_consecutive_wins"] == 2
    assert summary["max_consecutive_losses"] == 2

    # Drawdown verification
    assert dd["peak_cumulative_pnl"] == "150.0000"
    assert dd["current_cumulative_pnl"] == "150.0000"
    assert dd["current_drawdown"] == "0.0000"
    assert dd["max_drawdown"] == "200.0000"  # Peak was 150, dropped to -50 -> decline = 200


@pytest.mark.asyncio
async def test_daily_and_monthly_aggregations(perf_db):
    """Verify daily and monthly bucket aggregations."""
    service, db_mgr = perf_db
    # Aug 2026
    await insert_completed_trade(db_mgr, "T_AUG_1", "2026-08-30", realized_pnl=50.0, fees=2.0)
    await insert_completed_trade(db_mgr, "T_AUG_2", "2026-08-31", realized_pnl=50.0, fees=2.0)
    # Sep 2026
    await insert_completed_trade(db_mgr, "T_SEP_1", "2026-09-01", realized_pnl=100.0, fees=5.0)
    await insert_completed_trade(db_mgr, "T_SEP_2", "2026-09-01", realized_pnl=-50.0, fees=5.0)

    res = await service.get_performance()
    daily = res["daily"]
    monthly = res["monthly"]

    # 3 unique days
    assert len(daily) == 3
    sep1 = next(d for d in daily if d["date"] == "2026-09-01")
    assert sep1["trade_count"] == 2
    assert sep1["wins"] == 1
    assert sep1["losses"] == 1
    assert sep1["net_pnl"] == "40.0000"  # (100 - 5) + (-50 - 5) = 95 - 55 = 40.0000

    # 2 unique months
    assert len(monthly) == 2
    aug_m = next(m for m in monthly if m["month"] == "2026-08")
    assert aug_m["trade_count"] == 2
    assert aug_m["win_rate_pct"] == "100.00%"
    assert aug_m["net_pnl"] == "96.0000"  # (50-2) + (50-2)


@pytest.mark.asyncio
async def test_filters_date_strategy_and_exchange(perf_db):
    """Verify filtering by from_date, to_date, strategy_name, and exchange."""
    service, db_mgr = perf_db
    await insert_completed_trade(db_mgr, "T_1", "2026-09-01", realized_pnl=100.0, strategy_name="short_strangle", exchange="delta_india")
    await insert_completed_trade(db_mgr, "T_2", "2026-09-05", realized_pnl=200.0, strategy_name="short_strangle", exchange="delta_india")
    await insert_completed_trade(db_mgr, "T_3", "2026-09-10", realized_pnl=300.0, strategy_name="iron_condor", exchange="delta_india")
    await insert_completed_trade(db_mgr, "T_4", "2026-09-15", realized_pnl=400.0, strategy_name="short_strangle", exchange="binance")

    # Date filter: 2026-09-02 to 2026-09-12
    res_date = await service.get_performance(from_date="2026-09-02", to_date="2026-09-12")
    assert res_date["summary"]["trade_count"] == 2  # T_2 and T_3

    # Strategy filter: short_strangle
    res_strat = await service.get_performance(strategy_name="short_strangle")
    assert res_strat["summary"]["trade_count"] == 3  # T_1, T_2, T_4

    # Exchange filter: delta_india
    res_ex = await service.get_performance(exchange="delta_india")
    assert res_ex["summary"]["trade_count"] == 3  # T_1, T_2, T_3


@pytest.mark.asyncio
async def test_active_incomplete_trades_excluded_from_performance(perf_db):
    """Verify ACTIVE or incomplete trades are not included in completed performance analytics."""
    service, db_mgr = perf_db
    # 1 completed trade
    await insert_completed_trade(db_mgr, "T_DONE", "2026-09-01", realized_pnl=100.0, status="COMPLETED")
    # 1 active open trade
    await insert_completed_trade(db_mgr, "T_ACTIVE", "2026-09-01", realized_pnl=500.0, status="ACTIVE")

    res = await service.get_performance()
    assert res["summary"]["trade_count"] == 1
    assert res["summary"]["net_pnl"] == "100.0000"


@pytest.mark.asyncio
async def test_db_unavailable_graceful_fallback(test_settings):
    """Verify PerformanceService gracefully handles unavailable PostgreSQL."""
    offline_settings = test_settings.model_copy(
        update={
            "postgres_host": "127.0.0.1",
            "postgres_port": 59998,
            "db_timeout_seconds": 0.5,
        }
    )
    db_mgr = DatabaseManager(settings=offline_settings)
    service = PerformanceService(db_manager=db_mgr, jsonl_path="nonexistent_trades.jsonl")

    res = await service.get_performance()
    assert res["status"] == "ok"
    assert res["source"] == "jsonl_fallback"
    assert res["summary"]["trade_count"] == 0
