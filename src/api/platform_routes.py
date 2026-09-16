"""Platform API routes — users, strategies, subscriptions, exchange accounts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.platform_auth import (
    exchange_account_to_dict,
    get_platform_user,
    strategy_to_dict,
    subscription_to_dict,
)
from src.api.security import verify_api_key_dependency
from src.exchanges.registry import get_exchange_definition, list_supported_exchanges
from src.persistence.platform_models import UserModel
from src.platform.repositories.platform_repository import PlatformRepository
from src.platform.sync.account_sync_service import AccountSyncService
from src.analytics.performance import PerformanceService


class SyncUserRequest(BaseModel):
    email: str
    google_id: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None


class ConnectExchangeRequest(BaseModel):
    exchange: str = Field(..., description="Exchange code e.g. binance, bybit, okx, delta_india")
    label: str = Field(..., min_length=1, max_length=128)
    api_key: str = Field(..., min_length=8)
    api_secret: str = Field(..., min_length=8)
    passphrase: Optional[str] = None
    is_testnet: bool = False


class SubscribeStrategyRequest(BaseModel):
    strategy_code: str


class LinkStrategyAccountRequest(BaseModel):
    exchange_account_id: str
    status: str = "paused"
    execution_mode: str = Field(default="PAPER", pattern="^(PAPER|LIVE|LIVE_DRY_RUN)$")
    allocation_pct: float = Field(default=100.0, ge=0, le=100)
    risk_overrides: Dict[str, Any] = Field(default_factory=dict)
    confirm_live: bool = False


class RuntimeControlRequest(BaseModel):
    confirm_live: bool = False


class ExecutionModeRequest(BaseModel):
    mode: str = Field(..., pattern="^(PAPER|LIVE|LIVE_DRY_RUN)$")
    confirm_live: bool = False


class InternalKillSwitchRequest(BaseModel):
    enabled: bool


def create_platform_router(engine, sync_service: AccountSyncService | None = None, runtime_manager=None):
    router = APIRouter(prefix="/platform", tags=["Platform"])
    verify_auth = verify_api_key_dependency(engine)

    def repo() -> PlatformRepository:
        return PlatformRepository(engine.db_manager)

    @router.post("/me/sync", dependencies=[Depends(verify_auth)])
    async def sync_user(payload: SyncUserRequest, request: Request) -> Dict[str, Any]:
        """Create or update user profile after Google OAuth (called by dashboard BFF)."""
        if not engine.db_manager.is_connected:
            raise HTTPException(status_code=503, detail="Database unavailable")

        header_email = (request.headers.get("X-User-Email") or "").strip().lower()
        email = payload.email.strip().lower()
        if header_email and header_email != email:
            raise HTTPException(status_code=403, detail="Email mismatch with authenticated session")

        platform_repo = repo()
        user = await platform_repo.upsert_user(
            email=email,
            google_id=payload.google_id,
            name=payload.name,
            avatar_url=payload.avatar_url,
        )
        await platform_repo.record_audit(
            user_id=user.id,
            event_type="user.sync",
            resource_type="user",
            resource_id=str(user.id),
        )
        return {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "avatar_url": user.avatar_url,
        }

    @router.get("/me", dependencies=[Depends(verify_auth)])
    async def get_me(user: UserModel = Depends(get_platform_user)) -> Dict[str, Any]:
        return {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "is_active": user.is_active,
        }

    @router.get("/exchanges/supported", dependencies=[Depends(verify_auth)])
    async def get_supported_exchanges() -> Dict[str, Any]:
        return {
            "exchanges": [
                {
                    "code": ex.code,
                    "name": ex.name,
                    "status": ex.status,
                    "supports_spot": ex.supports_spot,
                    "supports_perpetual": ex.supports_perpetual,
                    "supports_options": ex.supports_options,
                    "requires_passphrase": ex.requires_passphrase,
                    "credential_fields": list(ex.credential_fields),
                }
                for ex in list_supported_exchanges()
            ]
        }

    @router.get("/strategies", dependencies=[Depends(verify_auth)])
    async def list_strategies_catalog() -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            return {"connected": False, "strategies": []}
        strategies = await repo().list_strategies()
        return {
            "connected": True,
            "strategies": [strategy_to_dict(s) for s in strategies],
        }

    @router.get("/strategies/{code}", dependencies=[Depends(verify_auth)])
    async def get_strategy_detail(code: str) -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            raise HTTPException(status_code=503, detail="Database unavailable")
        strategy = await repo().get_strategy_by_code(code)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return strategy_to_dict(strategy)

    @router.post("/subscriptions", dependencies=[Depends(verify_auth)])
    async def subscribe_to_strategy(
        payload: SubscribeStrategyRequest,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            raise HTTPException(status_code=503, detail="Database unavailable")

        platform_repo = repo()
        strategy = await platform_repo.get_strategy_by_code(payload.strategy_code)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")

        sub = await platform_repo.create_subscription(user.id, strategy.id)
        await platform_repo.record_audit(
            user_id=user.id,
            event_type="subscription.created",
            resource_type="subscription",
            resource_id=str(sub.id),
            payload={"strategy_code": strategy.code},
        )
        return subscription_to_dict(sub, strategy=strategy)

    @router.get("/subscriptions", dependencies=[Depends(verify_auth)])
    async def list_my_subscriptions(user: UserModel = Depends(get_platform_user)) -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            return {"connected": False, "subscriptions": []}

        platform_repo = repo()
        subs = await platform_repo.list_user_subscriptions(user.id)
        links = await platform_repo.list_strategy_accounts_for_user(user.id)
        link_map: Dict[str, List[dict]] = {}
        for link in links:
            link_map.setdefault(str(link.subscription_id), []).append(
                {
                    "id": str(link.id),
                    "exchange_account_id": str(link.exchange_account_id),
                    "status": link.status,
                    "allocation_pct": float(link.allocation_pct or 100),
                    "execution_mode": link.execution_mode,
                    "trading_enabled": bool(link.trading_enabled),
                    "runtime_status": link.runtime_status,
                }
            )

        result = []
        runtime_rows = []
        if runtime_manager is not None:
            runtime_rows = await runtime_manager.list_runtimes(user.id)
        runtime_by_sa = {r.strategy_account_id: r for r in runtime_rows}

        for sub in subs:
            strategy = sub.strategy
            linked = link_map.get(str(sub.id), [])
            enriched_links = []
            for link in linked:
                snap = runtime_by_sa.get(link["id"])
                enriched = dict(link)
                if snap:
                    enriched.update(
                        {
                            "runtime_status": snap.status,
                            "execution_mode": snap.execution_mode,
                            "trading_enabled": snap.trading_enabled,
                            "last_heartbeat_at": snap.last_heartbeat_at,
                        }
                    )
                enriched_links.append(enriched)
            result.append(subscription_to_dict(sub, strategy=strategy, strategy_accounts=enriched_links))

        return {"connected": True, "subscriptions": result}

    def runtime_mgr():
        if runtime_manager is None:
            raise HTTPException(status_code=503, detail="Strategy runtime manager unavailable")
        return runtime_manager

    @router.get("/strategy-accounts/runtimes", dependencies=[Depends(verify_auth)])
    async def list_strategy_runtimes(user: UserModel = Depends(get_platform_user)) -> Dict[str, Any]:
        snapshots = await runtime_mgr().list_runtimes(user.id)
        return {
            "connected": True,
            "runtimes": [runtime_mgr().runtime_to_dict(s) for s in snapshots],
        }

    @router.post("/strategy-accounts/{strategy_account_id}/start", dependencies=[Depends(verify_auth)])
    async def start_strategy_runtime(
        strategy_account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            sa_uuid = uuid.UUID(strategy_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
        try:
            snapshot = await runtime_mgr().start_runtime(user.id, sa_uuid)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return runtime_mgr().runtime_to_dict(snapshot)

    @router.post("/strategy-accounts/{strategy_account_id}/stop", dependencies=[Depends(verify_auth)])
    async def stop_strategy_runtime(
        strategy_account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            sa_uuid = uuid.UUID(strategy_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
        try:
            snapshot = await runtime_mgr().stop_runtime(user.id, sa_uuid)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return runtime_mgr().runtime_to_dict(snapshot)

    @router.post("/strategy-accounts/{strategy_account_id}/pause", dependencies=[Depends(verify_auth)])
    async def pause_strategy_runtime(
        strategy_account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            sa_uuid = uuid.UUID(strategy_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
        try:
            snapshot = await runtime_mgr().pause_runtime(user.id, sa_uuid)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return runtime_mgr().runtime_to_dict(snapshot)

    @router.post("/strategy-accounts/{strategy_account_id}/resume", dependencies=[Depends(verify_auth)])
    async def resume_strategy_runtime(
        strategy_account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            sa_uuid = uuid.UUID(strategy_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
        try:
            snapshot = await runtime_mgr().resume_runtime(user.id, sa_uuid)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return runtime_mgr().runtime_to_dict(snapshot)

    @router.get("/strategy-accounts/{strategy_account_id}/validation", dependencies=[Depends(verify_auth)])
    async def get_strategy_validation_report(
        strategy_account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            sa_uuid = uuid.UUID(strategy_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
        try:
            return await runtime_mgr().get_validation_report(user.id, sa_uuid)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/strategy-accounts/{strategy_account_id}/execution-history", dependencies=[Depends(verify_auth)])
    async def get_execution_history(
        strategy_account_id: str,
        user: UserModel = Depends(get_platform_user),
        status: Optional[str] = Query(None),
        limit: int = Query(100, ge=1, le=500),
    ) -> Dict[str, Any]:
        try:
            sa_uuid = uuid.UUID(strategy_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
        try:
            orders = await runtime_mgr().get_execution_history(user.id, sa_uuid, limit=limit, status=status)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"strategy_account_id": strategy_account_id, "orders": orders}

    @router.post("/strategy-accounts/{strategy_account_id}/recover", dependencies=[Depends(verify_auth)])
    async def recover_strategy_runtime(
        strategy_account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            sa_uuid = uuid.UUID(strategy_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
        try:
            return await runtime_mgr().recover_runtime(user.id, sa_uuid)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/strategy-accounts/{strategy_account_id}/enable-trading", dependencies=[Depends(verify_auth)])
    async def enable_strategy_trading(
        strategy_account_id: str,
        payload: RuntimeControlRequest,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            sa_uuid = uuid.UUID(strategy_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
        try:
            return await runtime_mgr().enable_trading(user.id, sa_uuid, confirm_live=payload.confirm_live)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/strategy-accounts/{strategy_account_id}/disable-trading", dependencies=[Depends(verify_auth)])
    async def disable_strategy_trading(
        strategy_account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            sa_uuid = uuid.UUID(strategy_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
        try:
            return await runtime_mgr().disable_trading(user.id, sa_uuid)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/strategy-accounts/{strategy_account_id}/execution-mode", dependencies=[Depends(verify_auth)])
    async def set_strategy_execution_mode(
        strategy_account_id: str,
        payload: ExecutionModeRequest,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            sa_uuid = uuid.UUID(strategy_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
        try:
            return await runtime_mgr().set_execution_mode(
                user.id,
                sa_uuid,
                payload.mode,
                confirm_live=payload.confirm_live,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/subscriptions/{subscription_id}/accounts", dependencies=[Depends(verify_auth)])
    async def link_account_to_subscription(
        subscription_id: str,
        payload: LinkStrategyAccountRequest,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            raise HTTPException(status_code=503, detail="Database unavailable")

        platform_repo = repo()
        try:
            sub_uuid = uuid.UUID(subscription_id)
            acct_uuid = uuid.UUID(payload.exchange_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid UUID") from exc

        subs = await platform_repo.list_user_subscriptions(user.id)
        if not any(s.id == sub_uuid for s in subs):
            raise HTTPException(status_code=404, detail="Subscription not found")

        account = await platform_repo.get_exchange_account(user.id, acct_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="Exchange account not found")

        if payload.execution_mode in {"LIVE", "LIVE_DRY_RUN"} and not payload.confirm_live:
            raise HTTPException(
                status_code=400,
                detail="Live execution requires explicit confirmation — set confirm_live=true after reviewing risks",
            )

        sub = next(s for s in subs if s.id == sub_uuid)
        strategy = sub.strategy
        if strategy and account.exchange not in (strategy.supported_exchanges or []):
            supported = ", ".join(strategy.supported_exchanges or [])
            raise HTTPException(
                status_code=400,
                detail=f"Exchange {account.exchange} is not supported for strategy {strategy.code}. Supported: {supported}",
            )

        link = await platform_repo.link_strategy_account(
            subscription_id=sub_uuid,
            exchange_account_id=acct_uuid,
            status=payload.status,
            execution_mode=payload.execution_mode,
            allocation_pct=payload.allocation_pct,
            risk_overrides=payload.risk_overrides or {},
        )
        await platform_repo.record_audit(
            user_id=user.id,
            event_type="strategy_account.linked",
            resource_type="strategy_account",
            resource_id=str(link.id),
            payload={
                "subscription_id": str(sub_uuid),
                "exchange_account_id": str(acct_uuid),
                "execution_mode": link.execution_mode,
            },
        )
        return {
            "id": str(link.id),
            "subscription_id": str(link.subscription_id),
            "exchange_account_id": str(link.exchange_account_id),
            "status": link.status,
            "execution_mode": link.execution_mode,
            "trading_enabled": bool(link.trading_enabled),
            "runtime_status": link.runtime_status,
            "allocation_pct": float(link.allocation_pct or 100),
            "risk_overrides": link.risk_overrides or {},
        }

    @router.get("/accounts/{account_id}/strategies", dependencies=[Depends(verify_auth)])
    async def list_account_strategies(
        account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            return {"connected": False, "strategies": []}
        try:
            acct_uuid = uuid.UUID(account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid account id") from exc
        from src.platform.portfolio_service import PortfolioService
        from src.platform.repositories.sync_repository import SyncRepository

        service = PortfolioService(repo(), SyncRepository(engine.db_manager))
        strategies = await service.list_account_strategies(user.id, acct_uuid)
        if strategies is None:
            raise HTTPException(status_code=404, detail="Exchange account not found")
        account = await repo().get_exchange_account(user.id, acct_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="Exchange account not found")
        return {"connected": True, "account_id": account_id, "strategies": strategies}

    @router.get("/portfolio/performance", dependencies=[Depends(verify_auth)])
    async def get_portfolio_performance(
        user: UserModel = Depends(get_platform_user),
        range: str = Query("1M", pattern="^(1D|1W|1M|3M|ALL)$"),
        strategy: Optional[str] = Query(None),
        account_id: Optional[str] = Query(None),
    ) -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            return {"connected": False, "combined": {}, "accounts": [], "strategies": []}
        from src.platform.ledger.performance_service import PlatformPerformanceService
        from src.platform.ledger.repository import PlatformLedgerRepository
        from src.platform.repositories.sync_repository import SyncRepository

        acct_uuid = None
        if account_id:
            try:
                acct_uuid = uuid.UUID(account_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid account id") from exc
            if not await repo().get_exchange_account(user.id, acct_uuid):
                raise HTTPException(status_code=404, detail="Exchange account not found")

        service = PlatformPerformanceService(
            PlatformLedgerRepository(engine.db_manager),
            repo(),
            SyncRepository(engine.db_manager),
        )
        payload = await service.get_portfolio_performance(
            user.id,
            range_key=range,
            strategy_code=strategy,
            account_id=acct_uuid,
        )
        return {"connected": True, "user_scoped": True, **payload}

    @router.get("/trades", dependencies=[Depends(verify_auth)])
    async def list_platform_trades(
        user: UserModel = Depends(get_platform_user),
        strategy: Optional[str] = Query(None),
        strategy_account_id: Optional[str] = Query(None),
        account_id: Optional[str] = Query(None),
        status: Optional[str] = Query(None),
        from_date: Optional[str] = Query(None, alias="from"),
        to_date: Optional[str] = Query(None, alias="to"),
        limit: int = Query(100, ge=1, le=500),
    ) -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            return {"connected": False, "trades": [], "user_scoped": True}
        from src.platform.ledger.repository import PlatformLedgerRepository

        ledger = PlatformLedgerRepository(engine.db_manager)
        sa_uuid = None
        acct_uuid = None
        if strategy_account_id:
            try:
                sa_uuid = uuid.UUID(strategy_account_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
            if not await ledger.verify_strategy_account_access(user.id, sa_uuid):
                raise HTTPException(status_code=404, detail="Strategy account not found")
        if account_id:
            try:
                acct_uuid = uuid.UUID(account_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid account id") from exc
            if not await ledger.verify_exchange_account_access(user.id, acct_uuid):
                raise HTTPException(status_code=404, detail="Exchange account not found")

        parsed_from = None
        parsed_to = None
        if from_date:
            try:
                parsed_from = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid from date") from exc
        if to_date:
            try:
                parsed_to = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid to date") from exc

        trades = await ledger.list_user_trades(
            user.id,
            strategy_code=strategy,
            strategy_account_id=sa_uuid,
            exchange_account_id=acct_uuid,
            status=status,
            from_date=parsed_from,
            to_date=parsed_to,
            limit=limit,
        )
        return {
            "connected": True,
            "user_scoped": True,
            "count": len(trades),
            "trades": trades,
        }

    @router.get("/strategy-accounts/{strategy_account_id}", dependencies=[Depends(verify_auth)])
    async def get_strategy_account_detail(
        strategy_account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            sa_uuid = uuid.UUID(strategy_account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid strategy account id") from exc
        platform_repo = repo()
        link = await platform_repo.get_strategy_account(user.id, sa_uuid)
        if not link:
            raise HTTPException(status_code=404, detail="Strategy account not found")
        sub = next((s for s in await platform_repo.list_user_subscriptions(user.id) if s.id == link.subscription_id), None)
        account = await platform_repo.get_exchange_account(user.id, link.exchange_account_id)
        runtime = None
        if runtime_manager is not None:
            for snap in await runtime_manager.list_runtimes(user.id):
                if snap.strategy_account_id == str(link.id):
                    runtime = runtime_mgr().runtime_to_dict(snap)
                    break
        return {
            "id": str(link.id),
            "subscription_id": str(link.subscription_id),
            "exchange_account_id": str(link.exchange_account_id),
            "status": link.status,
            "execution_mode": link.execution_mode,
            "trading_enabled": bool(link.trading_enabled),
            "runtime_status": link.runtime_status,
            "allocation_pct": float(link.allocation_pct or 100),
            "risk_overrides": link.risk_overrides or {},
            "strategy": strategy_to_dict(sub.strategy) if sub and sub.strategy else None,
            "subscription_status": sub.status if sub else None,
            "exchange_account": exchange_account_to_dict(account) if account else None,
            "runtime": runtime,
        }

    @router.get("/accounts", dependencies=[Depends(verify_auth)])
    async def list_exchange_accounts(user: UserModel = Depends(get_platform_user)) -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            return {"connected": False, "accounts": []}
        accounts = await repo().list_exchange_accounts(user.id)
        return {
            "connected": True,
            "accounts": [exchange_account_to_dict(a) for a in accounts],
        }

    def sync() -> AccountSyncService:
        if sync_service is None:
            raise HTTPException(status_code=503, detail="Account sync service unavailable")
        return sync_service

    @router.post("/accounts/test-connection", dependencies=[Depends(verify_auth)])
    async def test_exchange_connection(payload: ConnectExchangeRequest) -> Dict[str, Any]:
        definition = get_exchange_definition(payload.exchange)
        if not definition:
            raise HTTPException(status_code=400, detail=f"Unsupported exchange: {payload.exchange}")
        if definition.requires_passphrase and not payload.passphrase:
            raise HTTPException(status_code=400, detail="Passphrase required for this exchange")
        if sync_service is None:
            raise HTTPException(status_code=503, detail="Sync service unavailable")
        result = await sync_service.test_connection(
            exchange=payload.exchange,
            api_key=payload.api_key,
            api_secret=payload.api_secret,
            passphrase=payload.passphrase,
            is_testnet=payload.is_testnet,
        )
        if not result.success:
            raise HTTPException(status_code=400, detail=result.message)
        return {"success": True, "message": result.message}

    @router.post("/accounts", dependencies=[Depends(verify_auth)])
    async def connect_exchange_account(
        payload: ConnectExchangeRequest,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            raise HTTPException(status_code=503, detail="Database unavailable")

        definition = get_exchange_definition(payload.exchange)
        if not definition:
            raise HTTPException(status_code=400, detail=f"Unsupported exchange: {payload.exchange}")

        if definition.requires_passphrase and not payload.passphrase:
            raise HTTPException(status_code=400, detail="Passphrase required for this exchange")

        if sync_service is None:
            raise HTTPException(status_code=503, detail="Sync service unavailable")

        test = await sync_service.test_connection(
            exchange=payload.exchange,
            api_key=payload.api_key,
            api_secret=payload.api_secret,
            passphrase=payload.passphrase,
            is_testnet=payload.is_testnet,
        )
        if not test.success:
            raise HTTPException(status_code=400, detail=test.message)

        platform_repo = repo()
        account = await platform_repo.create_exchange_account(
            user_id=user.id,
            exchange=payload.exchange,
            label=payload.label,
            api_key=payload.api_key,
            api_secret=payload.api_secret,
            passphrase=payload.passphrase,
            is_testnet=payload.is_testnet,
        )

        await platform_repo.record_audit(
            user_id=user.id,
            event_type="exchange_account.connected",
            resource_type="exchange_account",
            resource_id=str(account.id),
            payload={"exchange": account.exchange, "label": account.label},
        )

        try:
            account = await sync_service.sync_account(account.id, user.id)
        except Exception:
            pass

        return exchange_account_to_dict(account)

    @router.post("/accounts/{account_id}/sync", dependencies=[Depends(verify_auth)])
    async def sync_exchange_account(
        account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            acct_uuid = uuid.UUID(account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid account id") from exc
        try:
            account = await sync().sync_account(acct_uuid, user.id)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Account synchronization failed") from exc
        return exchange_account_to_dict(account)

    @router.get("/accounts/{account_id}/detail", dependencies=[Depends(verify_auth)])
    async def get_account_full_detail(
        account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            acct_uuid = uuid.UUID(account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid account id") from exc
        try:
            return await sync().get_account_detail(user.id, acct_uuid)
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/accounts/{account_id}/equity", dependencies=[Depends(verify_auth)])
    async def get_account_equity_curve(
        account_id: str,
        range: str = Query("1M", pattern="^(1D|1W|1M|3M|ALL)$"),
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        try:
            acct_uuid = uuid.UUID(account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid account id") from exc
        account = await repo().get_exchange_account(user.id, acct_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="Exchange account not found")
        from src.platform.repositories.sync_repository import SyncRepository

        points = await SyncRepository(engine.db_manager).get_equity_curve(
            user_id=user.id,
            account_id=acct_uuid,
            range_key=range,
        )
        return {
            "account_id": str(acct_uuid),
            "currency": account.currency or "USD",
            "range": range.upper(),
            "points": points,
        }

    @router.get("/accounts/{account_id}", dependencies=[Depends(verify_auth)])
    async def get_exchange_account_detail(
        account_id: str,
        user: UserModel = Depends(get_platform_user),
    ) -> Dict[str, Any]:
        if not engine.db_manager.is_connected:
            raise HTTPException(status_code=503, detail="Database unavailable")

        try:
            acct_uuid = uuid.UUID(account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid account id") from exc

        account = await repo().get_exchange_account(user.id, acct_uuid)
        if not account:
            raise HTTPException(status_code=404, detail="Exchange account not found")
        return exchange_account_to_dict(account)

    @router.get("/dashboard/summary", dependencies=[Depends(verify_auth)])
    async def get_dashboard_summary(user: UserModel = Depends(get_platform_user)) -> Dict[str, Any]:
        """User-scoped portfolio summary. Engine metrics merged when available."""
        platform_repo = repo()
        accounts: List[dict] = []
        subscriptions: List[dict] = []

        if engine.db_manager.is_connected:
            accounts = [exchange_account_to_dict(a) for a in await platform_repo.list_exchange_accounts(user.id)]
            subs = await platform_repo.list_user_subscriptions(user.id)
            subscriptions = [subscription_to_dict(s, strategy=s.strategy) for s in subs]

        engine_status = engine.get_status() if hasattr(engine, "get_status") else {}
        total_equity = sum(float(a.get("equity") or 0) for a in accounts)
        total_available = sum(float(a.get("available_balance") or 0) for a in accounts)
        total_unrealized = sum(float(a.get("unrealized_pnl") or 0) for a in accounts)

        equity_curve = []
        if engine.db_manager.is_connected and accounts:
            from src.platform.repositories.sync_repository import SyncRepository

            sync_repo = SyncRepository(engine.db_manager)
            for acct in accounts[:5]:
                points = await sync_repo.get_equity_curve(
                    user_id=user.id,
                    account_id=uuid.UUID(acct["id"]),
                    range_key="1M",
                )
                equity_curve.extend(points)

        return {
            "user": {"id": str(user.id), "email": user.email, "name": user.name},
            "connected_accounts_count": len(accounts),
            "active_subscriptions_count": sum(1 for s in subscriptions if s.get("status") == "ACTIVE"),
            "total_equity": total_equity,
            "total_available_balance": total_available,
            "total_unrealized_pnl": total_unrealized,
            "accounts": accounts,
            "subscriptions": subscriptions,
            "engine": {
                "status": engine_status.get("engine", {}).get("status"),
                "environment": engine_status.get("engine", {}).get("environment"),
            },
            "equity_curve": equity_curve,
        }

    @router.get("/performance", dependencies=[Depends(verify_auth)])
    async def get_user_performance(
        user: UserModel = Depends(get_platform_user),
        strategy: Optional[str] = Query(None),
        account_id: Optional[str] = Query(None),
        from_date: Optional[str] = Query(None, alias="from"),
        to_date: Optional[str] = Query(None, alias="to"),
    ) -> Dict[str, Any]:
        perf = PerformanceService(db_manager=engine.db_manager, logger=getattr(engine, "logger", None))
        exchange_filter = None
        if account_id:
            try:
                acct_uuid = uuid.UUID(account_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid account id") from exc
            account = await repo().get_exchange_account(user.id, acct_uuid)
            if not account:
                raise HTTPException(status_code=404, detail="Exchange account not found")
            exchange_filter = account.exchange
        history = engine.state_store.get_historical_trades() if hasattr(engine, "state_store") else []
        return await perf.get_performance(
            from_date=from_date,
            to_date=to_date,
            strategy_name=strategy,
            exchange=exchange_filter,
            fallback_history=history,
        )

    @router.post("/internal/global-kill-switch", dependencies=[Depends(verify_auth)])
    async def set_global_kill_switch(payload: InternalKillSwitchRequest) -> Dict[str, Any]:
        """Internal-only endpoint — requires API key auth, not exposed to normal users."""
        engine.settings.platform_live_trading_enabled = payload.enabled
        return {
            "success": True,
            "platform_live_trading_enabled": engine.settings.platform_live_trading_enabled,
        }

    @router.get("/strategies/{code}/performance", dependencies=[Depends(verify_auth)])
    async def get_strategy_performance(
        code: str,
        user: UserModel = Depends(get_platform_user),
        range: str = Query("1M", pattern="^(1D|1W|1M|3M|ALL)$"),
        benchmark: bool = Query(False, description="Include legacy global engine benchmark"),
    ) -> Dict[str, Any]:
        strategy = await repo().get_strategy_by_code(code)
        if not strategy:
            raise HTTPException(status_code=404, detail="Strategy not found")
        if not engine.db_manager.is_connected:
            return {"connected": False, "strategy_code": code, "available": False, "user_scoped": True}

        from src.platform.ledger.performance_service import PlatformPerformanceService
        from src.platform.ledger.repository import PlatformLedgerRepository
        from src.platform.repositories.sync_repository import SyncRepository

        service = PlatformPerformanceService(
            PlatformLedgerRepository(engine.db_manager),
            repo(),
            SyncRepository(engine.db_manager),
        )
        payload = await service.get_user_strategy_performance(user.id, code, range_key=range)
        payload["connected"] = True
        if benchmark:
            perf = PerformanceService(db_manager=engine.db_manager, logger=getattr(engine, "logger", None))
            history = engine.state_store.get_historical_trades() if hasattr(engine, "state_store") else []
            payload["benchmark"] = await perf.get_performance(strategy_name=code, fallback_history=history)
        return payload

    @router.get("/events/stream", dependencies=[Depends(verify_auth)])
    async def stream_platform_events(user: UserModel = Depends(get_platform_user)):
        if sync_service is None:
            raise HTTPException(status_code=503, detail="Event stream unavailable")

        async def event_generator():
            async for chunk in sync_service.event_hub.subscribe(str(user.id)):
                yield chunk

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return router
