"""Prevent duplicate execution ownership between legacy engine and platform runtime."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.config.settings import Settings
from src.platform.runtime.models import RuntimeContext


class ExecutionOwnershipGuard:
    """Blocks platform LIVE start when legacy TradingEngine is active on same environment."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("execution_ownership_guard")

    def check_platform_live_start(
        self,
        ctx: RuntimeContext,
        settings: Settings,
        *,
        legacy_engine_running: bool = False,
    ) -> Dict[str, Any]:
        if not legacy_engine_running:
            return {"allowed": True, "owner": "PLATFORM_RUNTIME"}

        if settings.existing_strategy_enabled and ctx.exchange == "delta_india":
            self.logger.warning(
                "Platform runtime blocked: legacy TradingEngine is RUNNING for delta_india"
            )
            return {
                "allowed": False,
                "owner": "LEGACY_ENGINE",
                "reason": (
                    "Legacy TradingEngine is active. Stop the global engine before starting "
                    "platform LIVE runtime on Delta to prevent duplicate execution."
                ),
            }
        return {"allowed": True, "owner": "PLATFORM_RUNTIME"}
