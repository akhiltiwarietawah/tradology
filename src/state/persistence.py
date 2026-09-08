"""Atomic persistence layer storing strategy trade states across restarts."""

import os
import json
import tempfile
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.core.models.trade import StrategyTrade


class StatePersistence:
    """Handles atomic serialization and recovery of strategy state to disk."""

    def __init__(self, file_path: str = "data/trade_state.json", logger: Optional[logging.Logger] = None):
        self.file_path = Path(file_path)
        self.logger = logger or logging.getLogger("state_persistence")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def save_state(self, current_trade: Optional[StrategyTrade], history: Optional[List[StrategyTrade]] = None) -> bool:
        """Atomically persist trade state using a temporary file rename."""
        payload = {
            "current_trade": current_trade.to_dict() if current_trade else None,
            "history": [t.to_dict() for t in (history or [])],
        }

        try:
            dir_name = self.file_path.parent
            with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
                json.dump(payload, tf, indent=2)
                temp_name = tf.name

            # Atomic replace
            os.replace(temp_name, self.file_path)
            self.logger.debug(f"Saved state to {self.file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to persist state to {self.file_path}: {e}", exc_info=True)
            return False

    def load_state(self) -> tuple[Optional[StrategyTrade], List[StrategyTrade]]:
        """Load persisted trade state from disk."""
        if not self.file_path.exists():
            self.logger.info(f"No existing state file found at {self.file_path}. Starting clean.")
            return None, []

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            current_trade_data = data.get("current_trade")
            current_trade = StrategyTrade.from_dict(current_trade_data) if current_trade_data else None

            history_data = data.get("history", [])
            history = [StrategyTrade.from_dict(h) for h in history_data]

            self.logger.debug(
                f"Loaded state from {self.file_path}: "
                f"Active Trade={current_trade.strategy_trade_id if current_trade else 'None'}, "
                f"History Count={len(history)}"
            )
            return current_trade, history
        except Exception as e:
            self.logger.error(f"Error loading state from {self.file_path}: {e}. Returning clean state.", exc_info=True)
            return None, []


Tuple_Optional = tuple[Optional[StrategyTrade], List[StrategyTrade]]
