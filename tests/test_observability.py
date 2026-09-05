"""Tests for Production-Grade Structured Event Logging, Sanitization, and Observability."""

import json
import logging
from unittest.mock import MagicMock
from src.logging_utils.sanitizer import mask_sensitive_data, format_kv
from src.logging_utils.events import TradingEventLogger


def test_mask_sensitive_data_redacts_credentials():
    """Verify secrets and auth credentials are masked in dicts and nested structures."""
    payload = {
        "api_key": "live_secret_key_12345",
        "api_secret": "my_super_secret_shhh",
        "product_id": 150247,
        "nested": {
            "token": "bot_telegram_token",
            "password": "db_password_xyz",
            "symbol": "C-BTC-77800-020926",
        },
        "headers": [
            {"api-key": "header_key", "content-type": "application/json"},
        ],
    }

    sanitized = mask_sensitive_data(payload)
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["api_secret"] == "[REDACTED]"
    assert sanitized["product_id"] == 150247
    assert sanitized["nested"]["token"] == "[REDACTED]"
    assert sanitized["nested"]["password"] == "[REDACTED]"
    assert sanitized["nested"]["symbol"] == "C-BTC-77800-020926"
    assert sanitized["headers"][0]["api-key"] == "[REDACTED]"
    assert sanitized["headers"][0]["content-type"] == "application/json"


def test_format_kv_formats_cleanly():
    """Verify format_kv formats keyword args into a clean key=value string."""
    res = format_kv(
        trade_id="STRANGLE_1",
        leg="CE",
        quantity=5.0,
        price=120.50,
        missing=None,
    )
    assert "trade_id=STRANGLE_1" in res
    assert "leg=CE" in res
    assert "quantity=5.00" in res
    assert "price=120.50" in res
    assert "missing" not in res


def test_trading_event_logger_order_submitted():
    """Verify order_submitted emits structured INFO log and records to trade journal."""
    mock_logger = MagicMock(spec=logging.Logger)
    mock_trade_logger = MagicMock()
    event_logger = TradingEventLogger(logger=mock_logger, trade_logger=mock_trade_logger)

    event_logger.order_submitted(
        trade_id="STRANGLE_20260902_093243",
        leg="CE",
        symbol="C-BTC-77800-020926",
        product_id=150247,
        side="SELL",
        order_type="MARKET",
        quantity=5.0,
        client_order_id="S_260902_093243_CE_ent_s_65667",
    )

    mock_logger.info.assert_called_once()
    logged_msg = mock_logger.info.call_args[0][0]
    assert "[EVENT:ORDER_SUBMIT]" in logged_msg
    assert "trade_id=STRANGLE_20260902_093243" in logged_msg
    assert "leg=CE" in logged_msg
    assert "product_id=150247" in logged_msg

    mock_trade_logger.log_trade_event.assert_called_once()
    event_type, data = mock_trade_logger.log_trade_event.call_args[0]
    assert event_type == "ORDER_SUBMIT"
    assert data["trade_id"] == "STRANGLE_20260902_093243"
    assert data["leg"] == "CE"


def test_trading_event_logger_order_rejected_with_sanitization():
    """Verify order_rejected scrubs sensitive data in request/response and logs ERROR."""
    mock_logger = MagicMock(spec=logging.Logger)
    mock_trade_logger = MagicMock()
    event_logger = TradingEventLogger(logger=mock_logger, trade_logger=mock_trade_logger)

    event_logger.order_rejected(
        trade_id="STRANGLE_20260902_090000",
        leg="CE",
        symbol="C-BTC-78000-020926",
        product_id=150246,
        side="SELL",
        order_type="MARKET",
        quantity=10.0,
        client_order_id="S_20260902_090000_CE_entry_very_long_id_exceeding_delta_max",
        http_status=400,
        exchange_error_code="bad_schema",
        exchange_message="client_order_id length exceeds 32 characters",
        request_payload={"api_secret": "sensitive_raw_key", "size": 10},
        response_body={"error": {"code": "bad_schema"}},
        exception_type="DeltaAPIError",
        retryable=False,
    )

    mock_logger.error.assert_called_once()
    logged_msg = mock_logger.error.call_args[0][0]
    assert "[EVENT:ORDER_REJECTED]" in logged_msg
    assert "error_code=bad_schema" in logged_msg
    assert "sensitive_raw_key" not in logged_msg  # Redacted
    assert "[REDACTED]" in logged_msg


def test_trading_event_logger_bracket_attached():
    """Verify bracket_attached logs all OCO parameters and bracket ID."""
    mock_logger = MagicMock(spec=logging.Logger)
    mock_trade_logger = MagicMock()
    event_logger = TradingEventLogger(logger=mock_logger, trade_logger=mock_trade_logger)

    event_logger.bracket_attached(
        trade_id="STRANGLE_20260902_093243",
        leg="CE",
        symbol="C-BTC-77800-020926",
        product_id=150247,
        bracket_id="1511288034",
        sl_price=240.0,
        tp_price=2.0,
        trigger_method="mark_price",
        order_type="market_order",
        status="ACTIVE",
    )

    mock_logger.info.assert_called_once()
    logged_msg = mock_logger.info.call_args[0][0]
    assert "[EVENT:BRACKET_ATTACHED]" in logged_msg
    assert "bracket_id=1511288034" in logged_msg
    assert "sl_price=240.00" in logged_msg
    assert "tp_price=2.00" in logged_msg
