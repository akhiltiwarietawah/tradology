"""Logging module providing structured JSON logging, trade auditing, and console output."""

import os
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import pytz

from src.config.constants import IST_TIMEZONE


class JsonFormatter(logging.Formatter):
    """Formatter that outputs structured JSON for log analytics."""

    def format(self, record: logging.LogRecord) -> str:
        ist_now = datetime.now(IST_TIMEZONE).isoformat()
        log_record = {
            "timestamp_ist": ist_now,
            "timestamp_utc": datetime.now(pytz.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_record.update(record.extra_data)
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


class CountBasedLogBackoff:
    """Utility to suppress repeated log messages by backing off log frequency."""

    def __init__(self, initial_interval: int = 1, max_interval: int = 60):
        self._counts: Dict[str, int] = {}
        self.initial_interval = initial_interval
        self.max_interval = max_interval

    def should_log(self, key: str) -> bool:
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        if count <= self.initial_interval:
            return True
        if count % self.max_interval == 0:
            return True
        return False


def setup_logger(
    name: str = "trading_engine",
    logs_dir: str = "logs",
    log_level: str = "INFO",
) -> logging.Logger:
    """Configure engine logger with human-readable console and structured file handlers."""
    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)

    # 1. Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_formatter.converter = lambda *args: datetime.now(IST_TIMEZONE).timetuple()
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 2. Text Log File Handler
    file_handler = RotatingFileHandler(
        filename=os.path.join(logs_dir, "bot.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(console_formatter)
    logger.addHandler(file_handler)

    # 3. JSONL Events File Handler
    json_handler = RotatingFileHandler(
        filename=os.path.join(logs_dir, "events.jsonl"),
        maxBytes=20 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    json_handler.setLevel(level)
    json_handler.setFormatter(JsonFormatter())
    logger.addHandler(json_handler)

    return logger


class TradeLogger:
    """Specialized trade journal writing complete strategy lifecycle records to trades.jsonl."""

    def __init__(self, logs_dir: str = "logs"):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.trades_file = self.logs_dir / "trades.jsonl"

    def log_trade_event(self, event_type: str, data: Dict[str, Any]) -> None:
        payload = {
            "timestamp_ist": datetime.now(IST_TIMEZONE).isoformat(),
            "timestamp_utc": datetime.now(pytz.UTC).isoformat(),
            "event_type": event_type,
            **data,
        }
        with open(self.trades_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def log_leg_fill(self, trade_id: str, leg_data: Dict[str, Any]) -> None:
        self.log_trade_event("LEG_FILL", {"strategy_trade_id": trade_id, "leg": leg_data})

    def log_sl_trigger(self, trade_id: str, leg_symbol: str, current_price: float, sl_price: float) -> None:
        self.log_trade_event(
            "SL_TRIGGER",
            {
                "strategy_trade_id": trade_id,
                "symbol": leg_symbol,
                "current_price": current_price,
                "sl_price": sl_price,
            },
        )

    def log_leg_exit(self, trade_id: str, leg_data: Dict[str, Any]) -> None:
        self.log_trade_event("LEG_EXIT", {"strategy_trade_id": trade_id, "leg": leg_data})

    def log_trade_completion(self, trade_data: Dict[str, Any]) -> None:
        self.log_trade_event("TRADE_COMPLETED", {"trade": trade_data})

    def log_emergency_unwind(self, trade_id: str, reason: str, details: Dict[str, Any]) -> None:
        self.log_trade_event(
            "EMERGENCY_UNWIND",
            {"strategy_trade_id": trade_id, "reason": reason, "details": details},
        )

    def log_reconciliation_event(self, description: str, diff_details: Dict[str, Any]) -> None:
        self.log_trade_event(
            "RECONCILIATION",
            {"description": description, "details": diff_details},
        )
