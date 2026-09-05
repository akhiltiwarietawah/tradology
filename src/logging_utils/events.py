import logging
from typing import Any, Dict, Optional, Union
from src.logging_utils.sanitizer import format_kv, mask_sensitive_data
from src.logging_utils.logger import TradeLogger


class TradingEventLogger:
    """Emits high-signal, industry-standard structured trading events to logger and trade journal."""

    def __init__(self, logger: Optional[logging.Logger] = None, trade_logger: Optional[TradeLogger] = None):
        self.logger = logger or logging.getLogger("trading_engine")
        self.trade_logger = trade_logger or TradeLogger()

    def order_submitted(
        self,
        trade_id: str,
        leg: str,
        symbol: str,
        product_id: Union[int, str],
        side: str,
        order_type: str,
        quantity: float,
        client_order_id: str,
        price: Optional[float] = None,
        reduce_only: bool = False,
    ) -> None:
        """Log structured ORDER_SUBMIT event."""
        kv = format_kv(
            trade_id=trade_id,
            leg=leg,
            symbol=symbol,
            product_id=product_id,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            reduce_only=reduce_only if reduce_only else None,
            client_order_id=client_order_id,
        )
        self.logger.info(f"[EVENT:ORDER_SUBMIT] {kv}")
        self.trade_logger.log_trade_event("ORDER_SUBMIT", {
            "trade_id": trade_id,
            "leg": leg,
            "symbol": symbol,
            "product_id": str(product_id),
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "client_order_id": client_order_id,
            "price": price,
            "reduce_only": reduce_only,
        })

    def order_filled(
        self,
        trade_id: str,
        leg: str,
        symbol: str,
        product_id: Union[int, str],
        order_id: str,
        fill_price: float,
        quantity: float,
        side: str,
        status: str = "FILLED",
        latency_ms: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> None:
        """Log structured ORDER_FILLED event."""
        kv = format_kv(
            trade_id=trade_id,
            leg=leg,
            symbol=symbol,
            product_id=product_id,
            order_id=order_id,
            side=side,
            fill_price=fill_price,
            quantity=quantity,
            status=status,
            latency_ms=f"{latency_ms:.0f}ms" if latency_ms is not None else None,
            client_order_id=client_order_id,
        )
        self.logger.info(f"[EVENT:ORDER_FILLED] {kv}")
        self.trade_logger.log_trade_event("ORDER_FILLED", {
            "trade_id": trade_id,
            "leg": leg,
            "symbol": symbol,
            "product_id": str(product_id),
            "order_id": order_id,
            "side": side,
            "fill_price": fill_price,
            "quantity": quantity,
            "status": status,
            "latency_ms": latency_ms,
            "client_order_id": client_order_id,
        })

    def order_rejected(
        self,
        trade_id: str,
        leg: str,
        symbol: str,
        product_id: Union[int, str],
        side: str,
        order_type: str,
        quantity: float,
        client_order_id: Optional[str] = None,
        http_status: Optional[int] = None,
        exchange_error_code: Optional[str] = None,
        exchange_message: Optional[str] = None,
        request_payload: Optional[Dict[str, Any]] = None,
        response_body: Optional[Dict[str, Any]] = None,
        exception_type: Optional[str] = None,
        retryable: bool = False,
    ) -> None:
        """Log detailed structured ORDER_REJECTED event with sanitized request/response."""
        sanitized_req = mask_sensitive_data(request_payload) if request_payload else None
        sanitized_res = mask_sensitive_data(response_body) if response_body else None

        kv = format_kv(
            trade_id=trade_id,
            leg=leg,
            symbol=symbol,
            product_id=product_id,
            side=side,
            order_type=order_type,
            quantity=quantity,
            client_order_id=client_order_id,
            http_status=http_status,
            error_code=exchange_error_code,
            message=exchange_message,
            retryable=retryable,
            exception=exception_type,
            req=sanitized_req,
            res=sanitized_res,
        )
        self.logger.error(f"[EVENT:ORDER_REJECTED] {kv}")
        self.trade_logger.log_trade_event("ORDER_REJECTED", {
            "trade_id": trade_id,
            "leg": leg,
            "symbol": symbol,
            "product_id": str(product_id),
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "client_order_id": client_order_id,
            "http_status": http_status,
            "error_code": exchange_error_code,
            "message": exchange_message,
            "retryable": retryable,
            "exception_type": exception_type,
            "request_payload": sanitized_req,
            "response_body": sanitized_res,
        })

    def bracket_attached(
        self,
        trade_id: str,
        leg: str,
        symbol: str,
        product_id: Union[int, str],
        bracket_id: str,
        sl_price: float,
        tp_price: Optional[float] = None,
        trigger_method: str = "mark_price",
        order_type: str = "market_order",
        status: str = "ACTIVE",
    ) -> None:
        """Log structured BRACKET_ATTACHED event."""
        kv = format_kv(
            trade_id=trade_id,
            leg=leg,
            symbol=symbol,
            product_id=product_id,
            bracket_id=bracket_id,
            sl_price=sl_price,
            tp_price=tp_price,
            trigger=trigger_method.upper(),
            order_type=order_type.upper(),
            reduce_only="true",
            status=status,
        )
        self.logger.info(f"[EVENT:BRACKET_ATTACHED] {kv}")
        self.trade_logger.log_trade_event("BRACKET_ATTACHED", {
            "trade_id": trade_id,
            "leg": leg,
            "symbol": symbol,
            "product_id": str(product_id),
            "bracket_id": bracket_id,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "trigger_method": trigger_method,
            "status": status,
        })
