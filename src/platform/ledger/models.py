"""Platform ledger attribution models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PlatformAttribution:
    """Tenant context for platform-originated ledger writes."""

    user_id: uuid.UUID
    subscription_id: uuid.UUID
    strategy_account_id: uuid.UUID
    exchange_account_id: uuid.UUID
    strategy_code: str
    strategy_order_intent_id: Optional[uuid.UUID] = None

    def with_intent(self, intent_id: Optional[uuid.UUID]) -> "PlatformAttribution":
        if intent_id is None or intent_id == self.strategy_order_intent_id:
            return self
        return PlatformAttribution(
            user_id=self.user_id,
            subscription_id=self.subscription_id,
            strategy_account_id=self.strategy_account_id,
            exchange_account_id=self.exchange_account_id,
            strategy_code=self.strategy_code,
            strategy_order_intent_id=intent_id,
        )
