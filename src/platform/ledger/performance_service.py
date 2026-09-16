"""User-scoped platform performance aggregation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from src.platform.ledger.pnl import (
    compute_realized_from_trades,
    compute_strategy_unrealized,
    curve_metrics,
    merge_equity_curves,
)
from src.platform.ledger.repository import PlatformLedgerRepository
from src.platform.repositories.platform_repository import PlatformRepository
from src.platform.repositories.sync_repository import SyncRepository


class PlatformPerformanceService:
    """
    Combined portfolio uses account-level equity as source of truth (no double counting).
    Strategy metrics use attributed trades only (user_id + strategy_account_id NOT NULL).
    """

    def __init__(
        self,
        ledger: PlatformLedgerRepository,
        platform_repo: PlatformRepository,
        sync_repo: SyncRepository,
    ):
        self.ledger = ledger
        self.platform_repo = platform_repo
        self.sync_repo = sync_repo

    @staticmethod
    def _range_start(range_key: str) -> Optional[datetime]:
        now = datetime.now(timezone.utc)
        delta = {
            "1D": timedelta(days=1),
            "1W": timedelta(days=7),
            "1M": timedelta(days=30),
            "3M": timedelta(days=90),
        }.get(range_key.upper())
        return None if range_key.upper() == "ALL" or delta is None else now - delta

    async def get_user_strategy_performance(
        self,
        user_id: uuid.UUID,
        strategy_code: str,
        *,
        range_key: str = "1M",
    ) -> Dict[str, Any]:
        subs = await self.platform_repo.list_user_subscriptions(user_id)
        links = await self.platform_repo.list_strategy_accounts_for_user(user_id)
        sa_ids = [
            link.id
            for link in links
            if any(s.id == link.subscription_id and s.strategy and s.strategy.code == strategy_code for s in subs)
        ]
        if not sa_ids:
            return {
                "strategy_code": strategy_code,
                "available": False,
                "reason": "no_subscribed_strategy_accounts",
                "user_scoped": True,
            }

        trades = await self.ledger.get_trades_for_strategy_accounts(
            user_id,
            sa_ids,
            from_date=self._range_start(range_key),
        )
        realized = compute_realized_from_trades(trades)

        strategy_rows = []
        for sa_id in sa_ids:
            sa_trades = [t for t in trades if t.get("strategy_account_id") == str(sa_id)]
            sa_realized = compute_realized_from_trades(sa_trades)
            link = next(l for l in links if l.id == sa_id)
            owners = await self.ledger.build_symbol_ownership_map(user_id, link.exchange_account_id)
            open_legs = await self.ledger.get_open_legs_for_strategy_accounts(user_id, [sa_id])
            marks = await self.ledger.get_account_mark_prices(user_id, link.exchange_account_id)
            unreal = compute_strategy_unrealized(open_legs, marks, owners, str(sa_id))
            curve = await self.ledger.get_strategy_equity_curve(user_id, sa_id)
            strategy_rows.append(
                {
                    "strategy_account_id": str(sa_id),
                    "realized": sa_realized,
                    "unrealized": unreal,
                    "equity_curve": curve,
                    "curve_metrics": curve_metrics(curve),
                }
            )

        combined_curve: List[Dict[str, Any]] = []
        for row in strategy_rows:
            combined_curve.extend(row["equity_curve"])
        combined_curve.sort(key=lambda p: p["timestamp"])

        return {
            "strategy_code": strategy_code,
            "available": realized["available"],
            "user_scoped": True,
            "summary": realized,
            "strategy_accounts": strategy_rows,
            "equity_curve": combined_curve,
            "curve_metrics": curve_metrics(combined_curve),
            "benchmark": None,
        }

    async def get_portfolio_performance(
        self,
        user_id: uuid.UUID,
        *,
        range_key: str = "1M",
        strategy_code: Optional[str] = None,
        account_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        accounts = await self.platform_repo.list_exchange_accounts(user_id)
        if account_id:
            accounts = [a for a in accounts if a.id == account_id]

        account_curves: List[List[Dict[str, Any]]] = []
        account_rows = []
        total_unrealized = 0.0
        for account in accounts:
            curve = await self.sync_repo.get_equity_curve(
                user_id=user_id,
                account_id=account.id,
                range_key=range_key,
            )
            account_curves.append(curve)
            total_unrealized += float(account.unrealized_pnl or 0)
            account_rows.append(
                {
                    "account_id": str(account.id),
                    "label": account.label,
                    "exchange": account.exchange,
                    "equity": float(account.equity or 0),
                    "unrealized_pnl": float(account.unrealized_pnl or 0),
                    "realized_pnl": float(account.realized_pnl or 0),
                    "equity_curve": curve,
                    "curve_metrics": curve_metrics(curve),
                }
            )

        combined_account_curve = merge_equity_curves(account_curves)

        links = await self.platform_repo.list_strategy_accounts_for_user(user_id)
        subs = await self.platform_repo.list_user_subscriptions(user_id)
        if strategy_code:
            sub_ids = {s.id for s in subs if s.strategy and s.strategy.code == strategy_code}
            links = [l for l in links if l.subscription_id in sub_ids]
        if account_id:
            links = [l for l in links if l.exchange_account_id == account_id]

        sa_ids = [l.id for l in links]
        trades = await self.ledger.get_trades_for_strategy_accounts(
            user_id,
            sa_ids,
            from_date=self._range_start(range_key),
        )
        portfolio_realized = compute_realized_from_trades(trades)

        strategy_rows = []
        for link in links:
            sub = next((s for s in subs if s.id == link.subscription_id), None)
            strategy = sub.strategy if sub else None
            if not strategy:
                continue
            sa_trades = [t for t in trades if t.get("strategy_account_id") == str(link.id)]
            sa_realized = compute_realized_from_trades(sa_trades)
            open_legs = await self.ledger.get_open_legs_for_strategy_accounts(user_id, [link.id])
            owners = await self.ledger.build_symbol_ownership_map(user_id, link.exchange_account_id)
            marks = await self.ledger.get_account_mark_prices(user_id, link.exchange_account_id)
            unreal = compute_strategy_unrealized(open_legs, marks, owners, str(link.id))
            curve = await self.ledger.get_strategy_equity_curve(user_id, link.id)
            strategy_rows.append(
                {
                    "strategy_account_id": str(link.id),
                    "strategy_code": strategy.code,
                    "strategy_name": strategy.name,
                    "exchange_account_id": str(link.exchange_account_id),
                    "realized": sa_realized,
                    "unrealized": unreal,
                    "equity_curve": curve,
                }
            )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "range": range_key.upper(),
            "architecture": {
                "combined_equity_source": "account_level",
                "strategy_pnl_source": "attributed_trades",
                "double_counting_prevention": "account equity summed once; strategy realized from attributed trades only",
            },
            "combined": {
                "total_equity": sum(float(a.equity or 0) for a in accounts),
                "total_unrealized_pnl": total_unrealized,
                "realized": portfolio_realized,
                "equity_curve": combined_account_curve,
                "curve_metrics": curve_metrics(combined_account_curve),
            },
            "accounts": account_rows,
            "strategies": strategy_rows,
        }
