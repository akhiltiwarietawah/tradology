"""Account and wallet balance data models."""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any


@dataclass
class AssetBalance:
    asset_symbol: str
    balance: float
    available_balance: float
    blocked_margin: float = 0.0
    balance_inr: Optional[float] = None
    available_balance_inr: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_symbol": self.asset_symbol,
            "balance": self.balance,
            "available_balance": self.available_balance,
            "blocked_margin": self.blocked_margin,
            "balance_inr": self.balance_inr,
            "available_balance_inr": self.available_balance_inr,
        }


@dataclass
class AccountBalance:
    balances: Dict[str, AssetBalance] = field(default_factory=dict)
    net_equity: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "net_equity": self.net_equity,
            "balances": {sym: b.to_dict() for sym, b in self.balances.items()},
        }
