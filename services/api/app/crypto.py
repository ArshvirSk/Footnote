"""Cryptographic helpers for encrypting and decrypting sensitive credentials.

Uses AES-256-GCM authenticated encryption with a 12-byte random nonce
prepended to the ciphertext.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from services.api.app.config import settings
from services.api.app.logging import get_logger

logger = get_logger(__name__)

# Fallback development key seed if ENCRYPTION_KEY is not configured
DEV_FALLBACK_SEED = b"footnote-dev-default-encryption-seed-2026"

SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "app_password",
    "secret",
    "token",
    "api_key",
    "key",
    "private",
    "auth",
)


def get_encryption_key() -> bytes:
    """Derive a 32-byte AES key from settings.encryption_key.

    Accepts base64-encoded 32-byte strings, 64-char hex strings, or arbitrary strings
    (hashed via SHA-256). Falls back to a deterministic dev seed if empty.
    """
    raw = (settings.encryption_key or "").strip()
    if not raw:
        return hashlib.sha256(DEV_FALLBACK_SEED).digest()

    # Try base64
    try:
        decoded = base64.b64decode(raw)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass

    # Try hex
    try:
        decoded_hex = bytes.fromhex(raw)
        if len(decoded_hex) == 32:
            return decoded_hex
    except Exception:
        pass

    # Arbitrary passphrase string -> SHA-256
    return hashlib.sha256(raw.encode("utf-8")).digest()


def encrypt_credentials(config: dict[str, Any]) -> bytes:
    """Encrypt a dictionary of credentials into AES-256-GCM byte payload.

    Format: [12-byte nonce][ciphertext + 16-byte tag].
    """
    if not config:
        return b""

    key = get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    payload_bytes = json.dumps(config, separators=(",", ":")).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, payload_bytes, None)
    return nonce + ciphertext


def decrypt_credentials(config_enc: bytes | memoryview | None) -> dict[str, Any]:
    """Decrypt an AES-256-GCM byte payload back into credentials dictionary.

    Returns an empty dict if config_enc is empty or None.
    Raises ValueError on decryption/authentication failure.
    """
    if not config_enc:
        return {}

    raw_bytes = bytes(config_enc)
    if len(raw_bytes) < 28:  # 12 nonce + 16 auth tag minimum
        raise ValueError("Encrypted configuration payload is too short or corrupted.")

    key = get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = raw_bytes[:12]
    ciphertext = raw_bytes[12:]

    try:
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(decrypted_bytes.decode("utf-8"))
    except Exception as exc:
        logger.error("credentials_decryption_failed", error=str(exc))
        raise ValueError("Failed to decrypt credentials payload (invalid key or ciphertext)") from exc


def mask_credentials(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of the config dictionary with sensitive fields masked.

    Replaces passwords, API keys, tokens, and secrets with masked placeholders
    so they can be safely displayed in the Ops console or API responses.
    """
    if not config:
        return {}

    masked: dict[str, Any] = {}
    for key, value in config.items():
        k_lower = key.lower()
        is_sensitive = any(sub in k_lower for sub in SENSITIVE_KEY_SUBSTRINGS)

        if is_sensitive and isinstance(value, str) and value:
            if len(value) > 8:
                masked[key] = f"{value[:2]}••••••••{value[-2:]}"
            else:
                masked[key] = "••••••••"
        elif isinstance(value, dict):
            masked[key] = mask_credentials(value)
        else:
            masked[key] = value

    return masked
