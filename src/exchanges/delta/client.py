"""Delta Exchange India Async REST API Client with HMAC-SHA256 Signing and Timeout Recovery."""

import hmac
import hashlib
import time
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
import aiohttp

from src.config.constants import (
    PATH_PRODUCTS,
    PATH_TICKERS,
    PATH_TICKERS_BATCH,
    PATH_INDICES,
    PATH_ORDERS,
    PATH_ORDERS_HISTORY,
    PATH_ORDERS_BRACKET,
    PATH_POSITIONS,
    PATH_POSITIONS_MARGINED,
    PATH_FILLS,
    PATH_WALLET_BALANCES,
)


class DeltaAPIError(Exception):
    """Base exception for Delta API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}


class DeltaTimeoutError(DeltaAPIError):
    """Exception raised when an API request times out."""
    pass


class DeltaRestClient:
    """Async client for interacting with Delta Exchange India REST API."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        api_secret: str = "",
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        logger: Optional[logging.Logger] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.logger = logger or logging.getLogger("delta_rest_client")
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        await self.get_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _generate_signature(self, method: str, path: str, query_string: str, body_str: str, timestamp: str) -> str:
        """Generate HMAC-SHA256 signature for Delta Exchange API."""
        message = method.upper() + timestamp + path + query_string + body_str
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    async def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        auth_required: bool = True,
    ) -> Dict[str, Any]:
        """Execute signed HTTP request with retry logic and error handling."""
        session = await self.get_session()
        url = f"{self.base_url}{path}"
        method = method.upper()

        query_string = ""
        if params:
            clean_params = {k: v for k, v in params.items() if v is not None}
            if clean_params:
                query_string = "?" + "&".join(f"{k}={v}" for k, v in sorted(clean_params.items()))

        body_str = json.dumps(data, separators=(",", ":")) if data else ""

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "BTC-Strangle-Bot/1.0",
        }

        if auth_required:
            if not self.api_key or not self.api_secret:
                raise DeltaAPIError("API key and secret are required for authenticated endpoints.")
            timestamp = str(int(time.time()))
            sig = self._generate_signature(method, path, query_string, body_str, timestamp)
            headers["api-key"] = self.api_key
            headers["timestamp"] = timestamp
            headers["signature"] = sig

        full_url = f"{url}{query_string}"
        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.debug(f"HTTP {method} {full_url} (attempt {attempt}/{self.max_retries})")
                async with session.request(
                    method=method,
                    url=full_url,
                    headers=headers,
                    data=body_str if method in ("POST", "PUT", "DELETE") and body_str else None,
                ) as response:
                    status = response.status
                    response_text = await response.text()

                    try:
                        resp_json = json.loads(response_text) if response_text else {}
                    except Exception:
                        resp_json = {"raw": response_text}

                    if status in (200, 201):
                        return resp_json

                    if status == 429:
                        retry_after = float(response.headers.get("Retry-After", 2.0 * attempt))
                        self.logger.warning(f"Rate limited (429). Retrying after {retry_after:.1f}s...")
                        await asyncio.sleep(retry_after)
                        continue

                    if status >= 500 and attempt < self.max_retries:
                        backoff = 1.0 * (2 ** (attempt - 1))
                        self.logger.warning(f"Server error {status}. Retrying in {backoff:.1f}s...")
                        await asyncio.sleep(backoff)
                        continue

                    err_obj = resp_json.get("error")
                    if isinstance(err_obj, dict):
                        error_msg = err_obj.get("message") or err_obj.get("code") or str(err_obj)
                    else:
                        error_msg = str(err_obj or resp_json)
                    raise DeltaAPIError(f"Delta API HTTP {status}: {error_msg}", status_code=status, response_data=resp_json)

            except (asyncio.TimeoutError, aiohttp.ClientConnectionError) as e:
                last_exception = e
                if attempt < self.max_retries:
                    backoff = 1.0 * (2 ** (attempt - 1))
                    self.logger.warning(f"Network error on {method} {path}: {str(e)}. Retrying in {backoff:.1f}s...")
                    await asyncio.sleep(backoff)
                else:
                    raise DeltaTimeoutError(f"Network timeout/failure for {method} {path} after {self.max_retries} attempts: {e}")

        if last_exception:
            raise DeltaTimeoutError(f"Request failed: {last_exception}")
        raise DeltaAPIError("Unexpected request failure.")

    async def get_products(
        self,
        contract_types: Optional[str] = "call_options,put_options",
        states: Optional[str] = "live",
    ) -> List[Dict[str, Any]]:
        """Fetch raw products list."""
        params = {}
        if contract_types:
            params["contract_types"] = contract_types
        if states:
            params["states"] = states

        res = await self.request("GET", PATH_PRODUCTS, params=params, auth_required=False)
        return res.get("result", []) if isinstance(res, dict) else res

    async def get_tickers(self, product_ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        """Fetch raw tickers list."""
        params = {}
        if product_ids:
            params["product_ids"] = ",".join(str(p) for p in product_ids[:10])

        res = await self.request("GET", PATH_TICKERS, params=params, auth_required=False)
        return res.get("result", []) if isinstance(res, dict) else res

    async def get_spot_price(self, symbol: str = "BTC") -> float:
        """Fetch underlying index or spot price."""
        try:
            res = await self.request("GET", PATH_INDICES, auth_required=False)
            result_list = res.get("result", [])
            for item in result_list:
                if item.get("symbol", "").upper() in (symbol.upper(), f".{symbol.upper()}", f"{symbol.upper()}USD"):
                    return float(item.get("price") or item.get("index_price") or 0.0)
        except Exception as e:
            self.logger.warning(f"Could not fetch index price from {PATH_INDICES}: {e}")

        try:
            tickers = await self.get_tickers()
            for t in tickers:
                sym = t.get("symbol", "").upper()
                if sym in (f"{symbol.upper()}USD", f"{symbol.upper()}USDT", f"{symbol.upper()}_USDT"):
                    spot = float(t.get("spot_price") or t.get("index_price") or 0.0)
                    if spot > 0:
                        return spot
                    mark = float(t.get("mark_price") or 0.0)
                    if mark > 0:
                        return mark
        except Exception as e:
            self.logger.error(f"Failed to get spot price fallback: {e}")

        raise DeltaAPIError(f"Unable to retrieve spot/index price for {symbol}")

    async def get_positions(self, product_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch open positions from exchange."""
        if product_id is not None:
            res = await self.request("GET", PATH_POSITIONS, params={"product_id": str(product_id)}, auth_required=True)
        else:
            res = await self.request("GET", PATH_POSITIONS_MARGINED, auth_required=True)
        return res.get("result", []) if isinstance(res, dict) else []

    async def get_open_orders(self, product_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch active open orders."""
        params = {"state": "open"}
        if product_id is not None:
            params["product_id"] = str(product_id)
        res = await self.request("GET", PATH_ORDERS, params=params, auth_required=True)
        return res.get("result", []) if isinstance(res, dict) else []

    async def get_order_by_client_id(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        """Query order state by client_order_id to recover from timeouts."""
        try:
            res = await self.request("GET", PATH_ORDERS, params={"client_order_id": client_order_id}, auth_required=True)
            result_list = res.get("result", [])
            if result_list:
                return result_list[0]
            
            history_res = await self.request("GET", PATH_ORDERS_HISTORY, params={"client_order_id": client_order_id}, auth_required=True)
            hist_list = history_res.get("result", [])
            if hist_list:
                return hist_list[0]
        except Exception as e:
            self.logger.warning(f"Error querying order by client_order_id '{client_order_id}': {e}")
        return None

    async def get_recent_fills_for_product(
        self,
        product_id: int,
        side: Optional[str] = None,
        page_size: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent fills (executions) for a specific product from /v2/fills.

        Filters strictly by product_id so unrelated manual trades on other instruments
        do NOT appear. Used by reconciliation to capture actual exit fill prices and fees
        when a strategy leg was closed externally (e.g. manually via Delta UI or by expiry).

        Args:
            product_id: Delta product/instrument ID to filter fills.
            side: Optional "buy" or "sell" filter (close of a short = "buy").
            page_size: Max fills to fetch (default 10, we typically only need the latest 1-2).

        Returns:
            List of raw fill dicts sorted newest-first, or [] on any error.
        """
        params: Dict[str, Any] = {
            "product_id": str(product_id),
            "page_size": str(page_size),
        }
        if side:
            params["side"] = side.lower()
        try:
            res = await self.request("GET", PATH_FILLS, params=params, auth_required=True)
            result = res.get("result", [])
            if isinstance(result, dict):
                # Delta sometimes wraps in {"data": [...]}
                result = result.get("data", [])
            return result if isinstance(result, list) else []
        except Exception as e:
            self.logger.warning(f"Failed to fetch fills for product_id={product_id}: {e}")
            return []

    async def place_order(
        self,
        product_id: int,
        size: float,
        side: str,
        order_type: str = "market_order",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        stop_order_type: Optional[str] = None,
        stop_trigger_method: Optional[str] = None,
        bracket_stop_loss_price: Optional[float] = None,
        bracket_take_profit_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False,
        time_in_force: str = "gtc",
    ) -> Dict[str, Any]:
        """Place an order with timeout verification against exchange."""
        # Validate that size represents a whole number of contracts without fractional loss
        if abs(size - round(size)) > 1e-6:
            raise ValueError(f"Delta contract size must be a whole number of contracts, got: {size}")

        size_int = int(round(size))
        if size_int <= 0:
            raise ValueError(f"Delta contract size must be positive, got: {size_int}")

        order_type_clean = order_type.lower()

        payload: Dict[str, Any] = {
            "product_id": int(product_id),
            "size": size_int,
            "side": side.lower(),
            "order_type": order_type_clean,
        }

        if reduce_only:
            payload["reduce_only"] = True

        # time_in_force is applicable only to limit orders on Delta
        if order_type_clean == "limit_order" and time_in_force:
            payload["time_in_force"] = time_in_force.lower()

        if limit_price is not None:
            payload["limit_price"] = str(limit_price)
        if stop_price is not None:
            payload["stop_price"] = str(stop_price)
        if stop_order_type is not None:
            payload["stop_order_type"] = stop_order_type
        if stop_trigger_method is not None:
            payload["stop_trigger_method"] = stop_trigger_method
        if bracket_stop_loss_price is not None:
            payload["bracket_stop_loss_price"] = str(bracket_stop_loss_price)
        if bracket_take_profit_price is not None:
            payload["bracket_take_profit_price"] = str(bracket_take_profit_price)
        if client_order_id:
            payload["client_order_id"] = str(client_order_id)[:32]

        try:
            self.logger.info(f"Placing order on Delta: product_id={product_id}, side={side}, size={size}, type={order_type}, client_id={client_order_id}")
            res = await self.request("POST", PATH_ORDERS, data=payload, auth_required=True)
            return res.get("result", {})

        except DeltaTimeoutError as e:
            self.logger.warning(f"Order submission timed out for client_order_id {client_order_id}. Checking exchange state before retrying...")
            if client_order_id:
                await asyncio.sleep(1.0)
                existing = await self.get_order_by_client_id(client_order_id)
                if existing:
                    self.logger.info(f"Verified order on Delta after timeout: order_id={existing.get('id')}, state={existing.get('state')}")
                    return existing

            raise DeltaTimeoutError(f"Order submission timed out and could not be verified on exchange: {e}")

    async def create_bracket_order(
        self,
        product_id: int,
        stop_loss_price: float,
        take_profit_price: Optional[float] = None,
        stop_trigger_method: str = "mark_price",
        order_type: str = "market_order",
    ) -> Dict[str, Any]:
        """
        Create a native exchange-side bracket Stop Loss and optional Take Profit order attached to an open position on Delta Exchange.
        Uses POST /v2/orders/bracket.
        """
        payload: Dict[str, Any] = {
            "product_id": int(product_id),
            "stop_trigger_method": stop_trigger_method,
            "stop_loss_order": {
                "order_type": order_type.lower(),
                "stop_price": str(stop_loss_price),
            }
        }
        if take_profit_price is not None and take_profit_price > 0:
            payload["take_profit_order"] = {
                "order_type": "limit_order",
                "stop_price": str(take_profit_price),
                "limit_price": str(take_profit_price),
            }

        self.logger.info(
            f"Creating native bracket order on Delta: product_id={product_id}, SL={stop_loss_price}, TP={take_profit_price} (limit_order), trigger={stop_trigger_method}"
        )
        res = await self.request("POST", PATH_ORDERS_BRACKET, data=payload, auth_required=True)
        return res.get("result", {}) if isinstance(res, dict) else {}

    async def update_bracket_order(
        self,
        bracket_id: int,
        product_id: int,
        stop_loss_price: float,
        take_profit_price: Optional[float] = None,
        stop_trigger_method: str = "mark_price",
        order_type: str = "market_order",
    ) -> Dict[str, Any]:
        """Update an existing native exchange-side bracket order using PUT /v2/orders/bracket."""
        payload: Dict[str, Any] = {
            "id": int(bracket_id),
            "product_id": int(product_id),
            "stop_trigger_method": stop_trigger_method,
            "stop_loss_order": {
                "order_type": order_type.lower(),
                "stop_price": str(stop_loss_price),
            }
        }
        if take_profit_price is not None and take_profit_price > 0:
            payload["take_profit_order"] = {
                "order_type": "limit_order",
                "stop_price": str(take_profit_price),
                "limit_price": str(take_profit_price),
            }

        self.logger.info(
            f"Updating native bracket order on Delta: bracket_id={bracket_id}, product_id={product_id}, SL={stop_loss_price}, TP={take_profit_price} (limit_order)"
        )
        res = await self.request("PUT", PATH_ORDERS_BRACKET, data=payload, auth_required=True)
        return res.get("result", {}) if isinstance(res, dict) else {}

    async def get_bracket_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve bracket order details by order_id using GET /v2/orders/bracket?order_id=<id>."""
        try:
            res = await self.request("GET", PATH_ORDERS_BRACKET, params={"order_id": order_id}, auth_required=True)
            return res.get("result") if isinstance(res, dict) else None
        except Exception as e:
            self.logger.warning(f"Error fetching bracket order {order_id}: {e}")
            return None

    async def cancel_order(self, order_id: int, product_id: int) -> bool:
        """Cancel an open order."""
        try:
            payload = {"product_id": product_id}
            await self.request("DELETE", f"{PATH_ORDERS}/{order_id}", data=payload, auth_required=True)
            return True
        except DeltaAPIError as e:
            self.logger.warning(f"Failed to cancel order {order_id}: {e}")
            return False

    async def cancel_all_orders(self, product_id: Optional[int] = None) -> bool:
        """Cancel all open orders."""
        try:
            payload = {}
            if product_id is not None:
                payload["product_id"] = product_id
            await self.request("DELETE", PATH_ORDERS, data=payload, auth_required=True)
            return True
        except DeltaAPIError as e:
            self.logger.warning(f"Failed to cancel all orders: {e}")
            return False

    async def get_recent_fills(self, product_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch recent fills."""
        params = {}
        if product_id is not None:
            params["product_id"] = str(product_id)
        res = await self.request("GET", PATH_FILLS, params=params, auth_required=True)
        return res.get("result", []) if isinstance(res, dict) else []

    async def get_wallet_balances(self) -> List[Dict[str, Any]]:
        """Fetch wallet balances."""
        res = await self.request("GET", PATH_WALLET_BALANCES, auth_required=True)
        return res.get("result", []) if isinstance(res, dict) else []
