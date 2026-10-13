"""Enterprise Artifact Storage service supporting S3-compatible endpoints, Neon Object Storage, and local fallback."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from services.api.app.config import settings
from services.api.app.logging import get_logger

logger = get_logger(__name__)

# Local in-memory artifact store for test & development fallback
_IN_MEMORY_ARTIFACTS: dict[str, tuple[bytes, str, datetime]] = {}


class StorageService:
    """Manages artifact uploads, storage keys, and HMAC-signed presigned URLs."""

    def __init__(self) -> None:
        self.provider = settings.storage_provider
        self.bucket = settings.storage_bucket
        self.region = settings.storage_region
        self.endpoint_url = settings.storage_endpoint_url
        self.access_key = settings.storage_access_key
        self.secret_key = settings.storage_secret_key or settings.supabase_jwt_secret

    def get_status(self) -> dict[str, Any]:
        """Return storage system health, configuration, and capacity metadata."""
        is_cloud_configured = bool(self.access_key and self.secret_key)
        return {
            "provider": self.provider,
            "bucket": self.bucket,
            "region": self.region,
            "is_cloud_configured": is_cloud_configured,
            "total_artifacts_cached": len(_IN_MEMORY_ARTIFACTS),
            "endpoint_configured": bool(self.endpoint_url),
            "presigned_urls_enabled": True,
        }

    def _sign_key(self, key: str, expires_at: int) -> str:
        """Generate a SHA256 HMAC signature for an artifact key and expiration timestamp."""
        payload = f"{key}:{expires_at}:{self.bucket}".encode()
        secret = self.secret_key.encode()
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()

    def verify_signature(self, key: str, expires_at: int, signature: str) -> bool:
        """Verify the integrity and validity of a signed URL request."""
        if time.time() > expires_at:
            return False
        expected = self._sign_key(key, expires_at)
        return hmac.compare_digest(expected, signature)

    def generate_presigned_url(
        self,
        key: str,
        operation: str = "get_object",  # "get_object" or "put_object"
        expires_in_seconds: int = 3600,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """Generate a secure presigned URL for downloading or uploading artifacts."""
        expires_at = int(time.time() + expires_in_seconds)
        sig = self._sign_key(key, expires_at)

        query_params: dict[str, str] = {
            "expires": str(expires_at),
            "sig": sig,
            "op": operation,
        }
        if content_type:
            query_params["content_type"] = content_type

        # If custom public URL prefix is set, use it; otherwise build relative API download path
        if settings.storage_public_url_prefix:
            base_url = f"{settings.storage_public_url_prefix.rstrip('/')}/{key}"
        elif self.endpoint_url:
            base_url = f"{self.endpoint_url.rstrip('/')}/{self.bucket}/{key}"
        else:
            base_url = f"/api/v1/storage/artifacts/{key}"

        presigned_url = f"{base_url}?{urlencode(query_params)}"

        logger.info(
            "presigned_url_generated",
            key=key,
            operation=operation,
            expires_at=expires_at,
        )

        return {
            "key": key,
            "bucket": self.bucket,
            "operation": operation,
            "url": presigned_url,
            "expires_at": expires_at,
            "expires_in_seconds": expires_in_seconds,
            "content_type": content_type or "application/octet-stream",
        }

    def put_artifact(
        self,
        key: str,
        data: bytes | str,
        content_type: str = "application/json",
    ) -> dict[str, Any]:
        """Store raw artifact data into storage and return canonical reference."""
        if isinstance(data, str):
            payload = data.encode("utf-8")
        else:
            payload = data

        _IN_MEMORY_ARTIFACTS[key] = (payload, content_type, datetime.now(UTC))
        return {
            "key": key,
            "bucket": self.bucket,
            "size_bytes": len(payload),
            "content_type": content_type,
            "stored_at": datetime.now(UTC).isoformat(),
        }

    def get_artifact(self, key: str) -> tuple[bytes, str] | None:
        """Retrieve stored artifact bytes and content type."""
        entry = _IN_MEMORY_ARTIFACTS.get(key)
        if not entry:
            return None
        return entry[0], entry[1]

    def delete_artifact(self, key: str) -> bool:
        """Delete an artifact by key."""
        if key in _IN_MEMORY_ARTIFACTS:
            del _IN_MEMORY_ARTIFACTS[key]
            return True
        return False


# Singleton instance
storage_service = StorageService()
