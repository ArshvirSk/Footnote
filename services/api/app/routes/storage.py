"""Storage and artifact routes for presigned URLs and artifact streaming."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from services.api.app.auth import INTERNAL_ROLES, AuthUser, require_roles
from services.api.app.logging import get_logger
from services.api.app.storage import storage_service

logger = get_logger(__name__)

router = APIRouter(prefix="/storage", tags=["storage"])


class PresignedUrlRequest(BaseModel):
    key: str
    operation: str = Field(default="get_object", pattern="^(get_object|put_object)$")
    expires_in_seconds: int = Field(default=3600, ge=60, le=86400)
    content_type: str | None = None


class PresignedUrlResponse(BaseModel):
    key: str
    bucket: str
    operation: str
    url: str
    expires_at: int
    expires_in_seconds: int
    content_type: str


class StorageStatusResponse(BaseModel):
    provider: str
    bucket: str
    region: str
    is_cloud_configured: bool
    total_artifacts_cached: int
    endpoint_configured: bool
    presigned_urls_enabled: bool


@router.get("/status", response_model=StorageStatusResponse)
async def get_storage_status(
    user: Annotated[AuthUser, Depends(require_roles(*INTERNAL_ROLES))],
) -> dict[str, Any]:
    """Retrieve storage system status and configuration."""
    return storage_service.get_status()


@router.post("/presigned-url", response_model=PresignedUrlResponse)
async def create_presigned_url(
    req: PresignedUrlRequest,
    user: Annotated[AuthUser, Depends(require_roles(*INTERNAL_ROLES))],
) -> dict[str, Any]:
    """Generate a presigned URL for secure artifact upload or download."""
    return storage_service.generate_presigned_url(
        key=req.key,
        operation=req.operation,
        expires_in_seconds=req.expires_in_seconds,
        content_type=req.content_type,
    )


@router.get("/artifacts/{artifact_key:path}")
async def get_artifact_content(
    artifact_key: str,
    expires: Annotated[int | None, Query()] = None,
    sig: Annotated[str | None, Query()] = None,
) -> Response:
    """Download artifact by signed URL or direct access."""
    if expires and sig:
        if not storage_service.verify_signature(artifact_key, expires, sig):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired storage signature")

    result = storage_service.get_artifact(artifact_key)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact not found: {artifact_key}")

    data, content_type = result
    return Response(content=data, media_type=content_type)


@router.put("/artifacts/{artifact_key:path}")
async def upload_artifact_content(
    artifact_key: str,
    request: Request,
    expires: Annotated[int | None, Query()] = None,
    sig: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Upload artifact content using presigned URL signature."""
    if not expires or not sig or not storage_service.verify_signature(artifact_key, expires, sig):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid or expired storage upload signature")

    body = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream")
    return storage_service.put_artifact(artifact_key, body, content_type=content_type)
