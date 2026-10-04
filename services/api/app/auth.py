"""JWT authentication and authorization for FastAPI.

Verifies Supabase JWTs, extracts user identity and role,
and provides dependency injection for protected routes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from services.api.app.config import settings
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


class MemberRole(StrEnum):
    """Maps to member_role_t in the database."""

    OWNER = "owner"
    ADMIN = "admin"
    STRATEGIST = "strategist"
    EDITOR = "editor"
    CLIENT_APPROVER = "client_approver"
    CLIENT_VIEWER = "client_viewer"


# Roles that can access /ops routes
OPS_ROLES = {MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST, MemberRole.EDITOR}

# Roles that can access /portal routes
PORTAL_ROLES = {MemberRole.CLIENT_APPROVER, MemberRole.CLIENT_VIEWER}

# All internal roles (not client-scoped)
INTERNAL_ROLES = {MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST, MemberRole.EDITOR}


class AuthUser(BaseModel):
    """Authenticated user context extracted from JWT + database lookup."""

    user_id: UUID
    email: str
    org_id: UUID | None = None
    role: MemberRole | None = None
    client_ids: list[UUID] = []


async def _decode_jwt(token: str) -> dict[str, str | int | bool]:
    """Decode and verify a Supabase JWT."""
    try:
        payload: dict[str, str | int | bool] = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return payload
    except JWTError as exc:
        logger.warning("jwt_decode_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


async def _get_user_context(
    user_id: UUID, db: AsyncSession
) -> tuple[UUID | None, MemberRole | None, list[UUID]]:
    """Look up org membership and client access for a user."""
    # Check org_members first (internal roles)
    result = await db.execute(
        text("SELECT org_id, role FROM org_members WHERE user_id = :uid LIMIT 1"),
        {"uid": str(user_id)},
    )
    row = result.first()
    if row:
        return row.org_id, MemberRole(row.role), []

    # Check client_members (portal roles)
    result = await db.execute(
        text("SELECT client_id, role FROM client_members WHERE user_id = :uid"),
        {"uid": str(user_id)},
    )
    rows = result.all()
    if rows:
        client_ids = [r.client_id for r in rows]
        role = MemberRole(rows[0].role)
        return None, role, client_ids

    return None, None, []


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> AuthUser:
    """FastAPI dependency: extract and validate the current user from JWT.

    Also sets the PostgreSQL session variable so RLS policies work.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    payload = await _decode_jwt(credentials.credentials)
    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing sub claim",
        )

    user_id = UUID(sub)
    email = str(payload.get("email", ""))

    # Set the JWT claim for RLS. set_config(..., is_local=true) == SET LOCAL,
    # but accepts a bind parameter (SET does not).
    await db.execute(
        text("SELECT set_config('request.jwt.claim.sub', :uid, true)"),
        {"uid": str(user_id)},
    )

    org_id, role, client_ids = await _get_user_context(user_id, db)

    return AuthUser(
        user_id=user_id,
        email=email,
        org_id=org_id,
        role=role,
        client_ids=client_ids,
    )


def require_roles(*roles: MemberRole) -> Callable[..., Awaitable[AuthUser]]:
    """Dependency factory: ensure the user has one of the given roles."""

    async def _check(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {user.role} not permitted; requires one of {[r.value for r in roles]}",
            )
        return user

    return _check


def require_ops_role() -> Callable[..., Awaitable[AuthUser]]:
    """Dependency: user must have an ops-console role."""
    return require_roles(*OPS_ROLES)


def require_portal_role() -> Callable[..., Awaitable[AuthUser]]:
    """Dependency: user must have a portal role."""
    return require_roles(*PORTAL_ROLES)


async def has_client_access(user: AuthUser, client_id: UUID, db: AsyncSession) -> bool:
    """Check if the user can access a specific client. Used for API-level checks
    on top of RLS (defense in depth)."""
    if user.role in INTERNAL_ROLES and user.org_id:
        result = await db.execute(
            text("SELECT 1 FROM clients WHERE id = :cid AND org_id = :oid"),
            {"cid": str(client_id), "oid": str(user.org_id)},
        )
        return result.first() is not None

    return client_id in user.client_ids
