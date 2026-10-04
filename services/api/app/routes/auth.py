"""Auth routes — user identity, session info, dev login."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from pydantic import BaseModel
from services.api.app.auth import AuthUser, get_current_user
from services.api.app.config import settings
from services.api.app.db import get_db
from services.api.app.schemas import MemberRoleType, MeResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=MeResponse)
async def get_me(
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> MeResponse:
    """Return the current user's identity, org, role, and client access."""
    return MeResponse(
        user_id=user.user_id,
        email=user.email,
        org_id=user.org_id,
        role=MemberRoleType(user.role.value) if user.role else None,
        client_ids=user.client_ids,
    )


class DevLoginRequest(BaseModel):
    email: str


class DevLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID
    email: str


@router.post("/dev-login", response_model=DevLoginResponse)
async def dev_login(
    body: DevLoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DevLoginResponse:
    """Development-only login: exchange an email for a signed JWT.

    Enabled only when ENVIRONMENT != "production" (the frontend login page
    calls this while Supabase auth is not yet wired up). In production this
    returns 404 so the endpoint cannot be used to mint tokens.
    """
    if settings.environment == "production":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    result = await db.execute(
        text("SELECT id, email FROM auth.users WHERE lower(email) = lower(:email) LIMIT 1"),
        {"email": body.email},
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No user with that email — run `python -m services.api.scripts.seed` first",
        )

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(row.id),
            "email": row.email or body.email,
            "iat": now,
            "exp": now + timedelta(hours=12),
            "iss": "footnote-dev",
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )
    return DevLoginResponse(access_token=token, user_id=row.id, email=row.email or body.email)
