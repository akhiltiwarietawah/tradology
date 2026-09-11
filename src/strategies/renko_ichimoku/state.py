"""Independent on-disk state for the Renko Ichimoku strategy. Never mix with strangle state."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RenkoIchimokuState:
    position: int = 0  # 1 long, -1 short, 0 flat
    entry_price: Optional[float] = None
    entry_order_id: Optional[str] = None
    active_trade_id: Optional[str] = None
    entry_time: Optional[float] = None
    last_processed_candle_time: Optional[float] = None
    last_traded_brick_index: Optional[int] = None
    last_brick_close: Optional[float] = None
    last_brick_direction: int = 0
    warmup_complete: bool = False
    instrument_id: Optional[str] = None
    symbol: Optional[str] = None
    account: Optional[str] = None
    resolved_symbol: Optional[str] = None
    in_flight_client_order_id: Optional[str] = None
    in_flight_action: Optional[str] = None
    in_flight_brick_index: Optional[int] = None
    orders_halted: bool = False
    halt_reason: Optional[str] = None


class RenkoIchimokuStateStore:
    def __init__(self, file_path: str, logger: logging.Logger):
        self.file_path = Path(file_path)
        self.logger = logger
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> RenkoIchimokuState:
        if not self.file_path.exists():
            self.logger.info(f"No Renko Ichimoku state file at {self.file_path}. Starting flat.")
            return RenkoIchimokuState()
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RenkoIchimokuState(
                position=int(data.get("position") or 0),
                entry_price=data.get("entry_price"),
                entry_order_id=data.get("entry_order_id"),
                active_trade_id=data.get("active_trade_id"),
                entry_time=data.get("entry_time"),
                last_processed_candle_time=data.get("last_processed_candle_time"),
                last_traded_brick_index=data.get("last_traded_brick_index"),
                last_brick_close=data.get("last_brick_close"),
                last_brick_direction=int(data.get("last_brick_direction") or 0),
                warmup_complete=bool(data.get("warmup_complete")),
                instrument_id=data.get("instrument_id"),
                symbol=data.get("symbol"),
                account=data.get("account"),
                resolved_symbol=data.get("resolved_symbol"),
                in_flight_client_order_id=data.get("in_flight_client_order_id"),
                in_flight_action=data.get("in_flight_action"),
                in_flight_brick_index=data.get("in_flight_brick_index"),
                orders_halted=bool(data.get("orders_halted")),
                halt_reason=data.get("halt_reason"),
            )
        except Exception as e:
            self.logger.error(f"Failed to load Renko Ichimoku state: {e}. Starting flat (will not reopen).")
            return RenkoIchimokuState()

    def save(self, state: RenkoIchimokuState) -> None:
        payload = asdict(state)
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.file_path.parent, delete=False, encoding="utf-8") as tf:
                json.dump(payload, tf, indent=2)
                temp_name = tf.name
            os.replace(temp_name, self.file_path)
        except Exception as e:
            self.logger.error(f"Failed to persist Renko Ichimoku state: {e}", exc_info=True)
