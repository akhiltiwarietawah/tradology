"""FastAPI Application Factory with lifespan lifecycle and production security hardening."""

from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import create_router
from src.api.security import SecurityHeadersMiddleware, RateLimitMiddleware
from src.engine import TradingEngine
from src.platform.sync.account_sync_service import AccountSyncService
from src.platform.sync.event_hub import PlatformEventHub
from src.platform.sync.scheduler import AccountSyncScheduler
from src.platform.runtime.manager import StrategyRuntimeManager


def create_app(engine: Optional[TradingEngine] = None) -> FastAPI:
    trading_engine = engine or TradingEngine()
    settings = trading_engine.settings

    event_hub = PlatformEventHub()
    account_sync_service = AccountSyncService(trading_engine.db_manager, event_hub)
    runtime_manager = StrategyRuntimeManager(
        trading_engine.db_manager,
        settings,
        event_hub=event_hub,
        legacy_engine=trading_engine,
    )
    sync_scheduler = AccountSyncScheduler(
        account_sync_service,
        interval_seconds=getattr(settings, "platform_sync_interval_seconds", 60),
    )
    trading_engine.account_sync_service = account_sync_service
    trading_engine.platform_event_hub = event_hub
    trading_engine.runtime_manager = runtime_manager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        await trading_engine.start()
        await sync_scheduler.start()
        await runtime_manager.recover_on_startup()
        yield
        # Shutdown
        await runtime_manager.shutdown_all()
        await sync_scheduler.stop()
        await trading_engine.stop()

    app = FastAPI(
        title="Tradology BTC Options Engine",
        description="Production-grade 0DTE Options Algorithmic Trading Engine for Delta Exchange India",
        version="1.0.0",
        lifespan=lifespan,
    )

    # 1. Security Headers Middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # 2. Rate Limiting Middleware (in-memory, sliding-window)
    rate_limit = getattr(settings, "rate_limit_per_minute", 120)
    app.add_middleware(
        RateLimitMiddleware,
        rate_limit_per_minute=rate_limit,
        exempt_paths=["/health", "/ready", "/api/v1/health", "/api/v1/ready", "/docs", "/openapi.json"],
    )

    # 3. CORS Configuration (Restricted to dashboard origins)
    cors_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    if not cors_origins:
        cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "Authorization", "X-User-Email"],
    )

    # 4. Public Health & Readiness Endpoints
    @app.get("/health", tags=["Monitoring"])
    async def health() -> dict:
        """Lightweight process liveness check."""
        return {"status": "ok"}

    @app.get("/ready", tags=["Monitoring"])
    async def ready() -> dict:
        """Readiness check indicating whether trading engine is operational."""
        return trading_engine.get_readiness()

    # 5. Core REST Router
    router = create_router(trading_engine)
    app.include_router(router)
    app.state.engine = trading_engine
    app.state.account_sync_service = account_sync_service
    app.state.platform_event_hub = event_hub
    app.state.runtime_manager = runtime_manager

    return app
