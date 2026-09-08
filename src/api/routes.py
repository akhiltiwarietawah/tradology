"""FastAPI REST routes for engine monitoring and control with role-based auth protection."""

from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException

from src.api.security import verify_api_key_dependency


def create_router(engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Trading Engine"])
    verify_auth = verify_api_key_dependency(engine)

    # --------------------------------------------------------------------------
    # Public Liveness & Readiness Endpoints (Zero credentials / zero account secrets)
    # --------------------------------------------------------------------------
    @router.get("/health")
    async def get_health() -> Dict[str, Any]:
        """Lightweight process liveness check (Public)."""
        return {"status": "ok"}

    @router.get("/ready")
    async def get_ready() -> Dict[str, Any]:
        """Readiness check indicating whether trading engine is operational (Public)."""
        return engine.get_readiness()

    # --------------------------------------------------------------------------
    # Protected Operational & Analytics Endpoints (Requires X-API-Key when configured)
    # --------------------------------------------------------------------------
    @router.get("/status", dependencies=[Depends(verify_auth)])
    async def get_status() -> Dict[str, Any]:
        """Get live trading engine health, environment, and trade snapshot."""
        return engine.get_status()

    @router.get("/trades", dependencies=[Depends(verify_auth)])
    async def get_trades() -> Dict[str, Any]:
        """Get current trade and archived history."""
        trade = engine.strategy.current_trade
        history = engine.state_store.get_historical_trades()
        return {
            "current_trade": trade.to_dict() if trade else None,
            "history_count": len(history),
            "history": [t.to_dict() for t in history],
        }

    @router.get("/performance", dependencies=[Depends(verify_auth)])
    async def get_performance(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        strategy_name: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get performance analytics, drawdown curve, daily and monthly aggregates with optional filtering."""
        from src.analytics.performance import PerformanceService

        history = engine.state_store.get_historical_trades()
        perf_service = PerformanceService(
            db_manager=getattr(engine, "db_manager", None),
            jsonl_path=f"{engine.settings.logs_dir}/trades.jsonl",
            logger=engine.logger,
        )
        res = await perf_service.get_performance(
            from_date=from_date,
            to_date=to_date,
            strategy_name=strategy_name,
            exchange=exchange,
            fallback_history=history,
        )
        # Backward compatibility aliases
        res["daily_pnl"] = res["daily"]
        res["monthly_pnl"] = res["monthly"]
        return res

    @router.get("/account/balances", dependencies=[Depends(verify_auth)])
    async def get_account_balances() -> Dict[str, Any]:
        """Fetch real-time wallet and available balances from the exchange."""
        try:
            acc_bal = await engine.get_account_balances()
            return acc_bal.to_dict()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/reconcile", dependencies=[Depends(verify_auth)])
    async def trigger_reconciliation() -> Dict[str, Any]:
        """Manually trigger state reconciliation against exchange."""
        res = await engine.reconcile_state()
        return {
            "is_synchronized": res.is_synchronized,
            "status": res.status,
            "details": res.details,
        }

    @router.post("/kill-switch", dependencies=[Depends(verify_auth)])
    async def activate_kill_switch() -> Dict[str, Any]:
        """Engage emergency kill switch to halt all trading."""
        engine.risk_manager.activate_kill_switch()
        return {"status": "KILL_SWITCH_ACTIVATED", "message": "All trading halted."}

    return router
