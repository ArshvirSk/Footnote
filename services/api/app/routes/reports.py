"""Executive report and audit dossier export routes."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from services.api.app.audit_trail import record_audit_event
from services.api.app.auth import (
    INTERNAL_ROLES,
    PORTAL_ROLES,
    AuthUser,
    MemberRole,
    require_roles,
)
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from services.api.app.reporter import (
    generate_executive_report,
    get_report_by_id,
    list_client_reports,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


class GenerateReportRequest(BaseModel):
    title: str | None = None
    report_type: str = Field(default="visibility_audit", pattern="^(visibility_audit|executive_memo|technical_crawl)$")


class ExecutiveReportItem(BaseModel):
    id: UUID
    client_id: UUID
    title: str
    report_type: str
    metrics_summary: dict[str, Any]
    storage_url: str | None = None
    created_at: str | None = None


@router.post("/{client_id}/generate", response_model=ExecutiveReportItem)
async def create_client_report(
    client_id: UUID,
    req: GenerateReportRequest,
    user: Annotated[AuthUser, Depends(require_roles(*INTERNAL_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Generate a high-fidelity executive visibility report and audit dossier."""
    try:
        report = await generate_executive_report(
            db=db,
            client_id=client_id,
            generated_by=user.user_id,
            title=req.title,
            report_type=req.report_type,
        )

        await record_audit_event(
            db,
            org_id=user.org_id,
            actor=user.user_id,
            action="report.generated",
            entity="executive_reports",
            entity_id=UUID(report["id"]),
            meta={
                "client_id": str(client_id),
                "report_type": req.report_type,
                "title": report["title"],
            },
        )
        await db.commit()
        return report
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{client_id}", response_model=list[ExecutiveReportItem])
async def list_reports(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(*INTERNAL_ROLES, *PORTAL_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[dict[str, Any]]:
    """List historical executive visibility reports for a client."""
    # Check portal access if portal user
    if user.role in PORTAL_ROLES and client_id not in user.client_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to client reports")

    return await list_client_reports(db, client_id=client_id, limit=limit)


@router.get("/{report_id}/export")
async def export_report(
    report_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(*INTERNAL_ROLES, *PORTAL_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db)],
    export_format: Annotated[str, Query(alias="format")] = "html",
) -> Response:
    """Export full report as print-ready HTML or structured JSON dossier."""
    report = await get_report_by_id(db, report_id=report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    # If portal user, verify client match
    if user.role in PORTAL_ROLES and UUID(report["client_id"]) not in user.client_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to report")

    if export_format.lower() == "json":
        import json
        return Response(
            content=json.dumps(report["metrics_summary"]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="report-{report_id}.json"'},
        )

    html_content = report.get("content_html") or "<h1>No content</h1>"
    return Response(
        content=html_content,
        media_type="text/html",
        headers={"Content-Disposition": f'inline; filename="report-{report_id}.html"'},
    )
