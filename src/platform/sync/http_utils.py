"""Shared HTTP helpers for signed exchange REST calls."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import aiohttp


class ExchangeHttpError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


async def http_get_json(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 15.0,
) -> Any:
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
        async with session.get(url, headers=headers, params=params) as resp:
            text = await resp.text()
            if resp.status == 429:
                raise ExchangeHttpError("Exchange rate limit exceeded", status_code=429, error_code="rate_limited")
            if resp.status >= 400:
                raise ExchangeHttpError(
                    f"HTTP {resp.status}: {text[:200]}",
                    status_code=resp.status,
                    error_code="http_error",
                )
            return json.loads(text) if text else {}


def binance_sign_query(secret: str, params: Dict[str, Any]) -> str:
    query = urlencode(params)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


def bybit_sign(secret: str, timestamp: str, api_key: str, recv_window: str, query: str = "") -> str:
    payload = f"{timestamp}{api_key}{recv_window}{query}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def okx_sign(secret: str, timestamp: str, method: str, path: str, body: str = "") -> str:
    payload = f"{timestamp}{method.upper()}{path}{body}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest().hex()
