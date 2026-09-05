"""Utility functions to sanitize sensitive data and format structured logs."""

import json
from typing import Any, Dict, List, Union

SENSITIVE_KEYS = {
    "api_key",
    "api_secret",
    "secret",
    "signature",
    "api-key",
    "api-secret",
    "api-signature",
    "password",
    "token",
    "telegram_token",
    "telegram_bot_token",
    "authorization",
    "cookie",
    "db_password",
    "database_url",
    "private_key",
}


def mask_sensitive_data(data: Any) -> Any:
    """
    Recursively scrub sensitive keys and tokens from dicts, lists, and strings.
    Ensures API credentials, secrets, and auth headers are NEVER printed in logs.
    """
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            key_lower = str(k).lower().replace("-", "_")
            if any(sens in key_lower for sens in SENSITIVE_KEYS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = mask_sensitive_data(v)
        return sanitized

    elif isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]

    elif isinstance(data, str):
        return data

    return data


def format_kv(**kwargs) -> str:
    """Format keyword arguments into a clean key=value string for console & text loggers."""
    parts = []
    for k, v in kwargs.items():
        if v is None:
            continue
        if isinstance(v, float):
            # Format clean floats
            if abs(v) < 1e-4 and v != 0:
                parts.append(f"{k}={v:.6f}")
            else:
                parts.append(f"{k}={v:.2f}")
        elif isinstance(v, (dict, list)):
            sanitized = mask_sensitive_data(v)
            parts.append(f"{k}={json.dumps(sanitized, separators=(',', ':'))}")
        else:
            parts.append(f"{k}={v}")
    return " ".join(parts)
