"""FastAPI Application Factory with lifespan lifecycle and production security hardening."""

from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import create_router
from src.api.security import SecurityHeadersMiddleware, RateLimitMiddleware
from src.engine import TradingEngine


def create_app(engine: Optional[TradingEngine] = None) -> FastAPI:
    trading_engine = engine or TradingEngine()
    settings = trading_engine.settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        await trading_engine.start()
        yield
        # Shutdown
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
        allow_headers=["Content-Type", "X-API-Key", "Authorization"],
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

    return app
