"""User context for platform API routes (trusted BFF boundary)."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request, status

from src.persistence.platform_models import UserModel
from src.platform.repositories.platform_repository import PlatformRepository


async def get_platform_user(request: Request) -> UserModel:
    """
    Resolve authenticated user from X-User-Email header injected by Next.js BFF.
    The dashboard proxy must only set this header after NextAuth session validation.
    """
    email = (request.headers.get("X-User-Email") or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing user context. Sign in via the dashboard.",
        )

    engine = request.app.state.engine
    repo = PlatformRepository(engine.db_manager)

    user = await repo.get_user_by_email(email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found. Call POST /api/v1/platform/me/sync first.",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account inactive")
    return user


def strategy_to_dict(strategy) -> dict:
    return {
        "id": str(strategy.id),
        "code": strategy.code,
        "name": strategy.name,
        "description": strategy.description,
        "supported_exchanges": strategy.supported_exchanges or [],
        "markets": strategy.markets or [],
        "timeframe": strategy.timeframe,
        "risk_profile": strategy.risk_profile,
        "metadata": strategy.metadata_json or {},
    }


def exchange_account_to_dict(account) -> dict:
    from src.platform.sync.account_sync_service import AccountSyncService

    return AccountSyncService.account_to_safe_dict(account)


def subscription_to_dict(sub, strategy=None, strategy_accounts=None) -> dict:
    payload = {
        "id": str(sub.id),
        "status": sub.status,
        "billing_plan": sub.billing_plan,
        "risk_settings": sub.risk_settings or {},
        "subscribed_at": sub.subscribed_at.isoformat() if sub.subscribed_at else None,
        "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
    }
    if strategy:
        payload["strategy"] = strategy_to_dict(strategy)
    if strategy_accounts is not None:
        payload["linked_accounts"] = strategy_accounts
    return payload
