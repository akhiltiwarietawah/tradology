"""Encrypt/decrypt exchange API credentials at rest."""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("credential_vault")


class CredentialVault:
    """Fernet-based credential encryption. Never log plaintext secrets."""

    def __init__(self, encryption_key: str | None = None):
        raw = encryption_key or os.getenv("CREDENTIALS_ENCRYPTION_KEY", "")
        if not raw:
            logger.warning("CREDENTIALS_ENCRYPTION_KEY not set — using ephemeral dev key (NOT for production)")
            raw = Fernet.generate_key().decode()
        if len(raw) == 44 and raw.endswith("="):
            key_bytes = raw.encode()
        else:
            key_bytes = base64.urlsafe_b64encode(raw.ljust(32)[:32].encode())
        self._fernet = Fernet(key_bytes)

    def encrypt_credentials(self, payload: Dict[str, Any]) -> bytes:
        data = json.dumps(payload).encode("utf-8")
        return self._fernet.encrypt(data)

    def decrypt_credentials(self, blob: bytes) -> Dict[str, Any]:
        try:
            data = self._fernet.decrypt(blob)
            return json.loads(data.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError) as exc:
            raise ValueError("Unable to decrypt credentials") from exc

    @staticmethod
    def redact_for_response(payload: Dict[str, Any]) -> Dict[str, Any]:
        redacted = dict(payload)
        for key in ("api_key", "api_secret", "passphrase", "secret"):
            if key in redacted and redacted[key]:
                val = str(redacted[key])
                redacted[key] = f"{val[:4]}...{val[-4:]}" if len(val) > 8 else "****"
        return redacted
