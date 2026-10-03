"""Integrations routes: OAuth flow for GSC and GA4."""

import base64
from typing import Annotated
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.auth import AuthUser, MemberRole, require_roles
from services.api.app.config import settings
from services.api.app.db import get_db
from services.api.app.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}/integrations", tags=["integrations"])


class OAuthCallbackRequest(BaseModel):
    provider: str  # "gsc" or "ga4"
    auth_code: str
    redirect_uri: str


def encrypt_token(token_data: str) -> bytes:
    """Encrypt OAuth tokens using AES-256-GCM."""
    if not settings.encryption_key:
        # Fallback for dev mode without a key
        return token_data.encode("utf-8")
        
    try:
        key = base64.b64decode(settings.encryption_key)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, token_data.encode("utf-8"), None)
        return nonce + ciphertext
    except Exception as e:
        logger.error("encryption_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to encrypt token")


@router.post("/oauth/callback", status_code=status.HTTP_200_OK)
async def oauth_callback(
    client_id: UUID,
    body: OAuthCallbackRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Handle OAuth callback, exchange code for tokens, and store securely."""
    
    # In a real implementation:
    # 1. POST to https://oauth2.googleapis.com/token with body.auth_code
    # 2. Extract access_token, refresh_token, and expiry
    # For phase 2 demo, we stub the exchange.
    
    mock_token_data = '{"access_token": "mock_acc", "refresh_token": "mock_ref", "expires_in": 3600}'
    encrypted_tokens = encrypt_token(mock_token_data)
    
    async with db.begin():
        await db.execute(
            text("""
                INSERT INTO integrations (client_id, provider, account_ref, tokens_enc, status)
                VALUES (:cid, :prov, :acc, :tokens, 'active')
                ON CONFLICT (client_id, provider) DO UPDATE SET
                    tokens_enc = EXCLUDED.tokens_enc,
                    status = 'active',
                    last_synced_at = NULL
            """),
            {
                "cid": str(client_id),
                "prov": body.provider,
                "acc": f"mock_account_for_{body.provider}",
                "tokens": encrypted_tokens
            }
        )
    
    logger.info("integration_connected", client_id=str(client_id), provider=body.provider)
    return {"status": "success", "provider": body.provider}
