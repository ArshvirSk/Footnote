"""Auth routes — user identity and session info."""

from typing import Annotated

from fastapi import APIRouter, Depends

from services.api.app.auth import AuthUser, get_current_user
from services.api.app.schemas import MeResponse, MemberRoleType

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
