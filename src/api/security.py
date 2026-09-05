"""Production API Security: Authentication, Rate Limiting, and Security Headers."""

import time
import hmac
import logging
from typing import Dict, List, Optional
from collections import defaultdict
import threading

from fastapi import Request, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("api_security")

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_client_ip(request: Request) -> str:
    """Extract client IP handling reverse proxy headers safely."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def verify_api_key_dependency(engine):
    """Factory returning FastAPI dependency for API Key verification."""

    async def _verify(request: Request):
        settings = getattr(engine, "settings", None)
        if not settings:
            return True

        # Check if auth is configured or explicitly enabled
        expected_key = getattr(settings, "dashboard_api_key", None)
        auth_enabled = getattr(settings, "api_auth_enabled", False)

        if not auth_enabled and not expected_key:
            # Auth not configured (e.g. dev mode)
            return True

        # Extract API key from X-API-Key header or Authorization Bearer header
        provided_key = request.headers.get("X-API-Key")
        if not provided_key:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                provided_key = auth_header[7:].strip()

        client_ip = get_client_ip(request)
        path = request.url.path

        if not provided_key:
            logger.warning(f"⚠️ Unauthorized access attempt (missing API key) from {client_ip} to {path}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Missing API key (X-API-Key header or Bearer token required)",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        if not expected_key or not hmac.compare_digest(provided_key, expected_key):
            logger.warning(f"⚠️ Unauthorized access attempt (invalid API key) from {client_ip} to {path}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Invalid API key",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        return True

    return _verify


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects standard production security headers into every HTTP response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        
        # Standard security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), payment=()"
        
        # HSTS header if connection is HTTPS or behind HTTPS reverse proxy
        proto = request.headers.get("X-Forwarded-Proto", request.url.scheme)
        if proto == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Lightweight, in-memory sliding-window rate limiter per client IP.
    
    Zero Redis/external dependency requirement. Protects API from denial of service.
    """

    def __init__(self, app, rate_limit_per_minute: int = 120, exempt_paths: Optional[List[str]] = None):
        super().__init__(app)
        self.rate_limit = rate_limit_per_minute
        self.exempt_paths = set(exempt_paths or ["/health", "/ready", "/docs", "/openapi.json"])
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in self.exempt_paths:
            return await call_next(request)

        client_ip = get_client_ip(request)
        now = time.time()
        window_start = now - 60.0

        with self._lock:
            # Filter timestamps within current 60s sliding window
            timestamps = [t for t in self._requests[client_ip] if t > window_start]
            if len(timestamps) >= self.rate_limit:
                logger.warning(f"🛑 Rate limit exceeded for IP {client_ip} on {path} ({len(timestamps)} reqs/min)")
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Too many requests. Please slow down and try again later."},
                    headers={"Retry-After": "60"},
                )
            timestamps.append(now)
            self._requests[client_ip] = timestamps

            # Periodic cleanup if registry grows large
            if len(self._requests) > 5000:
                for ip in list(self._requests.keys()):
                    valid = [t for t in self._requests[ip] if t > window_start]
                    if not valid:
                        del self._requests[ip]
                    else:
                        self._requests[ip] = valid

        return await call_next(request)
