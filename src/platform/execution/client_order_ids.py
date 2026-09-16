"""Deterministic client order ID generation for platform execution."""

from __future__ import annotations

import uuid


def build_client_order_id(
    *,
    strategy_account_id: uuid.UUID,
    signal_key: str,
    leg_role: str,
    action: str = "entry",
) -> str:
    """Produce a stable, unique client order ID for a leg within a signal."""
    sa_short = str(strategy_account_id).replace("-", "")[:12]
    sig_short = signal_key.replace(" ", "_").replace("/", "_")[:40]
    role = leg_role.upper()[:8]
    act = action.upper()[:8]
    client_id = f"PLT_{sa_short}_{sig_short}_{role}_{act}"
    return client_id[:128]
