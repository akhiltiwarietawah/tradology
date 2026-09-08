"""Delta Exchange India WebSocket Client with Auth, Heartbeats, and Stale Detection."""

import hmac
import hashlib
import time
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable, Awaitable, Set
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from src.config.constants import (
    WS_CHANNEL_TICKER,
    WS_CHANNEL_ORDERS,
    WS_CHANNEL_POSITIONS,
    WS_CHANNEL_HEARTBEATS,
)


class DeltaWsClient:
    """Async WebSocket client for real-time market data and account feeds on Delta India."""

    def __init__(
        self,
        ws_url: str,
        api_key: str = "",
        api_secret: str = "",
        max_reconnect_attempts: int = 10,
        base_reconnect_delay: float = 2.0,
        stale_threshold_seconds: float = 30.0,
        logger: Optional[logging.Logger] = None,
    ):
        self.ws_url = ws_url
        self.api_key = api_key
        self.api_secret = api_secret
        self.max_reconnect_attempts = max_reconnect_attempts
        self.base_reconnect_delay = base_reconnect_delay
        self.stale_threshold_seconds = stale_threshold_seconds
        self.logger = logger or logging.getLogger("delta_ws_client")

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._connected = False
        self._authenticated = False
        self._last_msg_timestamp = time.time()
        self._subscribed_symbols: Set[str] = set()
        self._received_symbols: Set[str] = set()
        self._latest_tickers: Dict[str, Dict[str, Any]] = {}
        self._total_tickers_received = 0
        self._first_msg_received = False

        self._ticker_callbacks: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []
        self._order_callbacks: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []
        self._position_callbacks: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []

        self._listener_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    @staticmethod
    def _is_ws_open(ws: Any) -> bool:
        if ws is None:
            return False
        if hasattr(ws, "closed"):
            return not ws.closed
        if hasattr(ws, "close_code"):
            return ws.close_code is None
        if hasattr(ws, "state"):
            return str(ws.state).upper() == "OPEN"
        return True

    @property
    def is_connected(self) -> bool:
        return self._connected and self._is_ws_open(self._ws)

    @property
    def is_stale(self) -> bool:
        if not self.is_connected:
            return True
        if not self._subscribed_symbols:
            return False
        return (time.time() - self._last_msg_timestamp) > self.stale_threshold_seconds

    def add_ticker_callback(self, cb: Callable[[Dict[str, Any]], Awaitable[None]]):
        self._ticker_callbacks.append(cb)

    def _cache_ticker(self, ticker_data: Dict[str, Any]) -> None:
        """Keep last WS ticker keyed by symbol and product id for status/PnL snapshots."""
        sym = ticker_data.get("symbol")
        if sym:
            self._latest_tickers[str(sym)] = ticker_data
        product_id = ticker_data.get("product_id") or ticker_data.get("id")
        if product_id is not None:
            self._latest_tickers[str(product_id)] = ticker_data

    def get_latest_ticker(self, symbol_or_id: str) -> Optional[Dict[str, Any]]:
        if not symbol_or_id:
            return None
        return self._latest_tickers.get(str(symbol_or_id))

    def add_order_callback(self, cb: Callable[[Dict[str, Any]], Awaitable[None]]):
        self._order_callbacks.append(cb)

    def add_position_callback(self, cb: Callable[[Dict[str, Any]], Awaitable[None]]):
        self._position_callbacks.append(cb)

    def _generate_auth_signature(self, timestamp: str) -> str:
        message = "GET" + timestamp + "/live"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def connect(self):
        self._running = True
        self._listener_task = asyncio.create_task(self._connection_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_monitor_loop())

    async def stop(self):
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._listener_task:
            self._listener_task.cancel()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        self._connected = False
        self.logger.info("WebSocket client stopped.")

    async def _connection_loop(self):
        attempts = 0
        while self._running:
            try:
                self.logger.info(f"Connecting to Delta WebSocket: {self.ws_url}")
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    self._last_msg_timestamp = time.time()
                    attempts = 0
                    self.logger.info("WebSocket connected successfully.")

                    if self.api_key and self.api_secret:
                        await self._authenticate()

                    if self._subscribed_symbols:
                        await self._subscribe_symbols(list(self._subscribed_symbols))

                    async for raw_msg in ws:
                        self._last_msg_timestamp = time.time()
                        await self._handle_message(raw_msg)

            except (ConnectionClosed, WebSocketException, asyncio.TimeoutError, OSError) as e:
                self._connected = False
                self._authenticated = False
                if not self._running:
                    break

                attempts += 1
                delay = min(self.base_reconnect_delay * (2 ** (attempts - 1)), 60.0)
                self.logger.warning(
                    f"WebSocket disconnected ({e}). Reconnect attempt {attempts}/{self.max_reconnect_attempts} in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            except Exception as e:
                self._connected = False
                self._authenticated = False
                self.logger.error(f"Unexpected WebSocket error: {e}", exc_info=True)
                await asyncio.sleep(5.0)

    async def _authenticate(self):
        try:
            timestamp = str(int(time.time()))
            sig = self._generate_auth_signature(timestamp)
            auth_msg = {
                "type": "auth",
                "payload": {
                    "api-key": self.api_key,
                    "signature": sig,
                    "timestamp": timestamp,
                },
            }
            await self._ws.send(json.dumps(auth_msg))
            self.logger.info("Sent WebSocket authentication request.")
        except Exception as e:
            self.logger.error(f"Failed to authenticate WebSocket: {e}")

    async def subscribe_tickers(self, symbols: List[str]):
        for s in symbols:
            self._subscribed_symbols.add(s)
        if self.is_connected:
            await self._subscribe_symbols(symbols)

    async def _subscribe_symbols(self, symbols: List[str]):
        if not self._is_ws_open(self._ws) or not symbols:
            return
        payload = {
            "type": "subscribe",
            "payload": {
                "channels": [
                    {"name": WS_CHANNEL_TICKER, "symbols": list(symbols)},
                ]
            },
        }
        payload_str = json.dumps(payload)
        await self._ws.send(payload_str)
        self.logger.info(f"Sent WebSocket subscription payload: {payload_str}")

    async def subscribe_private_channels(self):
        if not self._is_ws_open(self._ws):
            return
        payload = {
            "type": "subscribe",
            "payload": {
                "channels": [
                    {"name": WS_CHANNEL_ORDERS},
                    {"name": WS_CHANNEL_POSITIONS},
                ]
            },
        }
        await self._ws.send(json.dumps(payload))
        self.logger.info("Subscribed to private channels: orders, positions")

    async def _handle_message(self, raw_msg: str):
        try:
            msg = json.loads(raw_msg)
            msg_type = msg.get("type", "")
            channel = msg.get("channel", "")

            if not self._first_msg_received:
                self._first_msg_received = True
                self.logger.info(f"📥 First WebSocket frame received: type='{msg_type}', channel='{channel}', keys={list(msg.keys())[:6]}")

            if msg_type == "subscriptions":
                confirmed_channels = msg.get("channels", [])
                self.logger.info(f"✅ Delta confirmed subscriptions: {confirmed_channels}")
                return

            if msg_type in ("auth_success", "authenticated") or msg.get("auth") == "success":
                self._authenticated = True
                self.logger.info("✅ WebSocket authentication verified by Delta.")
                await self.subscribe_private_channels()
                return

            if msg_type == "heartbeat" or channel == WS_CHANNEL_HEARTBEATS:
                return

            if channel == WS_CHANNEL_TICKER or msg_type == "v2/ticker":
                ticker_data = msg.get("data", msg)
                if isinstance(ticker_data, dict):
                    sym = ticker_data.get("symbol", "UNKNOWN")
                    mark_px = ticker_data.get("mark_price", 0.0)
                    self._cache_ticker(ticker_data)
                    self._total_tickers_received += 1
                    if sym not in self._received_symbols:
                        self._received_symbols.add(sym)
                        self.logger.info(f"📊 New symbol ticker received on WS: {sym} (Mark: ${float(mark_px or 0):.2f})")
                    elif self._total_tickers_received % 100 == 0:
                        self.logger.debug(f"Live WS Ticker stream: {sym} @ ${float(mark_px or 0):.2f} (Total msgs: {self._total_tickers_received})")

                    for cb in self._ticker_callbacks:
                        asyncio.create_task(cb(ticker_data))
                return

            if channel == WS_CHANNEL_ORDERS or msg_type == "orders":
                order_data = msg.get("data", msg)
                for cb in self._order_callbacks:
                    asyncio.create_task(cb(order_data))
                return

            if channel == WS_CHANNEL_POSITIONS or msg_type == "positions":
                pos_data = msg.get("data", msg)
                for cb in self._position_callbacks:
                    asyncio.create_task(cb(pos_data))
                return

        except Exception as e:
            self.logger.error(f"Error handling WebSocket message: {e}")

    async def _heartbeat_monitor_loop(self):
        while self._running:
            await asyncio.sleep(10)
            if self._running and self.is_stale:
                time_since = time.time() - self._last_msg_timestamp
                self.logger.warning(
                    f"⚠️ WebSocket data is STALE ({time_since:.1f}s since last message, threshold={self.stale_threshold_seconds}s). Triggering reconnect..."
                )
                if self._ws:
                    await self._ws.close()
