"""Client management routes — ops only."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.auth import (
    AuthUser,
    MemberRole,
    get_current_user,
    has_client_access,
    require_roles,
)
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from services.api.app.schemas import ClientCreateRequest, ClientResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientResponse])
async def list_clients(
    user: Annotated[
        AuthUser,
        Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST, MemberRole.EDITOR)),
    ],
    db: AsyncSession = Depends(get_db),
) -> list[ClientResponse]:
    """List all clients in the user's organization."""
    if not user.org_id:
        return []

    result = await db.execute(
        text(
            "SELECT id, org_id, name, primary_domain, industry, country, "
            "status, settings, onboarded_at, created_at "
            "FROM clients WHERE org_id = :oid ORDER BY created_at DESC"
        ),
        {"oid": str(user.org_id)},
    )
    rows = result.all()
    return [
        ClientResponse(
            id=r.id,
            org_id=r.org_id,
            name=r.name,
            primary_domain=r.primary_domain,
            industry=r.industry,
            country=r.country,
            status=r.status,
            settings=r.settings if r.settings else {},
            onboarded_at=r.onboarded_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ClientResponse:
    """Get a single client by ID. Checks access."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(
        text(
            "SELECT id, org_id, name, primary_domain, industry, country, "
            "status, settings, onboarded_at, created_at "
            "FROM clients WHERE id = :cid"
        ),
        {"cid": str(client_id)},
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    return ClientResponse(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        primary_domain=row.primary_domain,
        industry=row.industry,
        country=row.country,
        status=row.status,
        settings=row.settings if row.settings else {},
        onboarded_at=row.onboarded_at,
        created_at=row.created_at,
    )


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ClientCreateRequest,
    user: Annotated[
        AuthUser,
        Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN)),
    ],
    db: AsyncSession = Depends(get_db),
) -> ClientResponse:
    """Create a new client in the user's organization."""
    if not user.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not part of an organization",
        )

    result = await db.execute(
        text(
            "INSERT INTO clients (org_id, name, primary_domain, industry, country) "
            "VALUES (:oid, :name, :domain, :industry, :country) "
            "RETURNING id, org_id, name, primary_domain, industry, country, "
            "status, settings, onboarded_at, created_at"
        ),
        {
            "oid": str(user.org_id),
            "name": body.name,
            "domain": body.primary_domain,
            "industry": body.industry,
            "country": body.country,
        },
    )
    await db.commit()
    row = result.first()
    if not row:
        raise HTTPException(status_code=500, detail="Failed to create client")

    logger.info("client_created", client_id=str(row.id), client_name=body.name, org_id=str(user.org_id))

    return ClientResponse(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        primary_domain=row.primary_domain,
        industry=row.industry,
        country=row.country,
        status=row.status,
        settings=row.settings if row.settings else {},
        onboarded_at=row.onboarded_at,
        created_at=row.created_at,
    )
