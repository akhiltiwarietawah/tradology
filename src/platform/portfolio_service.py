"""User-scoped portfolio performance aggregation for the Tradology platform UI."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.analytics.performance import PerformanceService
from src.platform.repositories.platform_repository import PlatformRepository
from src.platform.repositories.sync_repository import SyncRepository


class PortfolioService:
    """Builds combined and strategy-wise portfolio views from real synced account data."""

    def __init__(
        self,
        platform_repo: PlatformRepository,
        sync_repo: SyncRepository,
        performance: Optional[PerformanceService] = None,
    ):
        self.platform_repo = platform_repo
        self.sync_repo = sync_repo
        self.performance = performance or PerformanceService(db_manager=platform_repo.db)

    @staticmethod
    def _merge_equity_curves(curves: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        buckets: Dict[str, float] = defaultdict(float)
        meta: Dict[str, Dict[str, float]] = defaultdict(dict)
        for curve in curves:
            for point in curve:
                ts = point.get("timestamp")
                if not ts:
                    continue
                buckets[ts] += float(point.get("equity") or 0)
                if point.get("unrealized_pnl") is not None:
                    meta[ts]["unrealized_pnl"] = meta[ts].get("unrealized_pnl", 0) + float(point["unrealized_pnl"])
        return [
            {
                "timestamp": ts,
                "equity": equity,
                **({"unrealized_pnl": meta[ts]["unrealized_pnl"]} if ts in meta else {}),
            }
            for ts, equity in sorted(buckets.items(), key=lambda item: item[0])
        ]

    @staticmethod
    def _curve_metrics(points: List[Dict[str, Any]]) -> Dict[str, Any]:
        if len(points) < 2:
            return {"available": False}
        start = float(points[0].get("equity") or 0)
        end = float(points[-1].get("equity") or 0)
        peak = start
        max_dd = 0.0
        for p in points:
            eq = float(p.get("equity") or 0)
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak
                max_dd = max(max_dd, dd)
        ret = ((end - start) / start) if start else None
        return {
            "available": True,
            "start_equity": start,
            "end_equity": end,
            "return_pct": ret,
            "max_drawdown_pct": max_dd,
            "pnl": end - start,
        }

    async def get_portfolio_performance(
        self,
        user_id: uuid.UUID,
        *,
        range_key: str = "1M",
        strategy_code: Optional[str] = None,
        account_id: Optional[uuid.UUID] = None,
        fallback_history: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        accounts = await self.platform_repo.list_exchange_accounts(user_id)
        if account_id:
            accounts = [a for a in accounts if a.id == account_id]

        account_curves: List[List[Dict[str, Any]]] = []
        account_rows: List[Dict[str, Any]] = []
        for account in accounts:
            curve = await self.sync_repo.get_equity_curve(
                user_id=user_id,
                account_id=account.id,
                range_key=range_key,
            )
            account_curves.append(curve)
            account_rows.append(
                {
                    "account_id": str(account.id),
                    "label": account.label,
                    "exchange": account.exchange,
                    "equity": float(account.equity or 0),
                    "available_balance": float(account.available_balance or 0),
                    "unrealized_pnl": float(account.unrealized_pnl or 0),
                    "realized_pnl": float(account.realized_pnl or 0),
                    "health_status": account.health_status,
                    "equity_curve": curve,
                    "curve_metrics": self._curve_metrics(curve),
                }
            )

        combined_curve = self._merge_equity_curves(account_curves)
        combined = {
            "total_equity": sum(float(a.equity or 0) for a in accounts),
            "total_available_balance": sum(float(a.available_balance or 0) for a in accounts),
            "total_unrealized_pnl": sum(float(a.unrealized_pnl or 0) for a in accounts),
            "total_realized_pnl": sum(float(a.realized_pnl or 0) for a in accounts),
            "equity_curve": combined_curve,
            "curve_metrics": self._curve_metrics(combined_curve),
        }

        subs = await self.platform_repo.list_user_subscriptions(user_id)
        links = await self.platform_repo.list_strategy_accounts_for_user(user_id)
        link_by_id = {link.id: link for link in links}
        account_by_id = {a.id: a for a in accounts}

        strategy_rows: List[Dict[str, Any]] = []
        for sub in subs:
            strategy = sub.strategy
            if not strategy:
                continue
            if strategy_code and strategy.code != strategy_code:
                continue
            sub_links = [link for link in links if link.subscription_id == sub.id]
            for link in sub_links:
                if account_id and link.exchange_account_id != account_id:
                    continue
                acct = account_by_id.get(link.exchange_account_id)
                benchmark = await self.performance.get_performance(
                    strategy_name=strategy.code,
                    fallback_history=fallback_history,
                )
                summary = benchmark.get("summary") or {}
                strategy_rows.append(
                    {
                        "strategy_account_id": str(link.id),
                        "subscription_id": str(sub.id),
                        "strategy_code": strategy.code,
                        "strategy_name": strategy.name,
                        "exchange_account_id": str(link.exchange_account_id),
                        "exchange_account_label": acct.label if acct else None,
                        "exchange": acct.exchange if acct else None,
                        "execution_mode": link.execution_mode,
                        "runtime_status": link.runtime_status,
                        "trading_enabled": bool(link.trading_enabled),
                        "status": link.status,
                        "account_equity": float(acct.equity or 0) if acct else None,
                        "benchmark_performance": {
                            "available": bool(summary),
                            "source": benchmark.get("source"),
                            "summary": summary,
                            "drawdown": benchmark.get("drawdown"),
                        },
                    }
                )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "range": range_key.upper(),
            "combined": combined,
            "accounts": account_rows,
            "strategies": strategy_rows,
            "data_notes": {
                "combined_trade_pnl": "Derived from account equity snapshots — not strategy-attributed trade ledger",
                "benchmark_performance": "Global strategy benchmark from engine trade history — not your personal subscription P&L",
            },
        }

    async def list_account_strategies(
        self,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> List[Dict[str, Any]]:
        account = await self.platform_repo.get_exchange_account(user_id, account_id)
        if not account:
            return []

        subs = await self.platform_repo.list_user_subscriptions(user_id)
        sub_by_id = {sub.id: sub for sub in subs}
        links = await self.platform_repo.list_strategy_accounts_for_user(user_id)
        rows: List[Dict[str, Any]] = []
        for link in links:
            if link.exchange_account_id != account_id:
                continue
            sub = sub_by_id.get(link.subscription_id)
            strategy = sub.strategy if sub else None
            rows.append(
                {
                    "strategy_account_id": str(link.id),
                    "subscription_id": str(link.subscription_id),
                    "strategy_code": strategy.code if strategy else None,
                    "strategy_name": strategy.name if strategy else None,
                    "subscription_status": sub.status if sub else None,
                    "execution_mode": link.execution_mode,
                    "runtime_status": link.runtime_status,
                    "trading_enabled": bool(link.trading_enabled),
                    "status": link.status,
                    "allocation_pct": float(link.allocation_pct or 100),
                }
            )
        return rows
