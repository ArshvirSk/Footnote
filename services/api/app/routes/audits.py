"""Site audit routes — start an audit on a live website and read results."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from services.api.app.audit import run_site_audit
from services.api.app.auth import (
    AuthUser,
    MemberRole,
    get_current_user,
    has_client_access,
    require_roles,
)
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}/audits", tags=["audits"])


class StartAuditRequest(BaseModel):
    url: str | None = None  # defaults to https://{client.primary_domain}


class FindingResponse(BaseModel):
    id: UUID
    category: str
    severity: str
    rule: str
    detail: str
    url: str | None
    fix_owner: str
    status: str


class AuditResponse(BaseModel):
    id: UUID
    client_id: UUID
    started_at: datetime | None
    finished_at: datetime | None
    score: float | None
    summary: dict[str, Any]


class AuditDetailResponse(AuditResponse):
    findings: list[FindingResponse]
    pages: list[dict[str, Any]]


@router.post("", response_model=AuditDetailResponse, status_code=status.HTTP_201_CREATED)
async def start_audit(
    client_id: UUID,
    body: StartAuditRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuditDetailResponse:
    """Crawl the client's website and persist a scored audit with findings.

    Synchronous by design for Phase 1: the crawl is bounded (homepage + ≤20
    sitemap pages) and the frontend shows a spinner.
    """
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    target = body.url
    if not target:
        res = await db.execute(
            text("SELECT primary_domain FROM clients WHERE id = :cid"), {"cid": str(client_id)}
        )
        domain = res.scalar()
        if not domain:
            raise HTTPException(status_code=404, detail="Client not found")
        target = f"https://{domain}"

    audit_id = uuid4()
    await db.execute(
        text(
            "INSERT INTO audits (id, client_id, started_at) VALUES (:id, :cid, now())"
        ),
        {"id": str(audit_id), "cid": str(client_id)},
    )
    await db.commit()

    try:
        result = await run_site_audit(target)
    except Exception as exc:
        await db.execute(
            text(
                "UPDATE audits SET finished_at = now(), summary = :summary WHERE id = :id"
            ),
            {"id": str(audit_id), "summary": '{"error": true}'},
        )
        await db.commit()
        logger.exception("site_audit_failed", audit_id=str(audit_id), error=str(exc))
        raise HTTPException(status_code=502, detail=f"Audit failed: {exc}") from exc

    # Persist findings
    for f in result.findings:
        await db.execute(
            text(
                """
                INSERT INTO audit_findings (id, audit_id, client_id, category, severity, url, rule, detail, fix_owner, status)
                VALUES (:id, :aid, :cid, :cat, :sev, :url, :rule, :detail, :owner, 'open')
                """
            ),
            {
                "id": str(uuid4()),
                "aid": str(audit_id),
                "cid": str(client_id),
                "cat": f.category,
                "sev": f.severity,
                "url": f.url,
                "rule": f.rule,
                "detail": f.detail,
                "owner": f.fix_owner,
            },
        )

    # Persist crawled pages
    for p in result.pages:
        await db.execute(
            text(
                """
                INSERT INTO site_pages (id, client_id, url, status_code, title, meta, jsonld, word_count, content_hash, last_crawled_at)
                VALUES (:id, :cid, :url, :status, :title, CAST(:meta AS jsonb), CAST(:jsonld AS jsonb), :wc, :hash, now())
                ON CONFLICT (client_id, url) DO UPDATE SET
                    status_code = EXCLUDED.status_code,
                    title = EXCLUDED.title,
                    meta = EXCLUDED.meta,
                    jsonld = EXCLUDED.jsonld,
                    word_count = EXCLUDED.word_count,
                    content_hash = EXCLUDED.content_hash,
                    last_crawled_at = now()
                """
            ),
            {
                "id": str(uuid4()),
                "cid": str(client_id),
                "url": p.url,
                "status": p.status_code,
                "title": p.title,
                "meta": json.dumps(p.meta),
                "jsonld": json.dumps(p.jsonld),
                "wc": p.word_count,
                "hash": p.content_hash,
            },
        )

    await db.execute(
        text(
            "UPDATE audits SET finished_at = now(), score = :score, summary = CAST(:summary AS jsonb) WHERE id = :id"
        ),
        {"id": str(audit_id), "score": result.score, "summary": json.dumps(result.summary)},
    )
    await db.commit()

    return await _audit_detail(db, audit_id, client_id)


@router.get("", response_model=list[AuditResponse])
async def list_audits(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AuditResponse]:
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    res = await db.execute(
        text(
            "SELECT id, client_id, started_at, finished_at, score, summary FROM audits "
            "WHERE client_id = :cid ORDER BY started_at DESC LIMIT 20"
        ),
        {"cid": str(client_id)},
    )
    return [
        AuditResponse(
            id=r.id, client_id=r.client_id, started_at=r.started_at,
            finished_at=r.finished_at, score=float(r.score) if r.score is not None else None,
            summary=r.summary or {},
        )
        for r in res.all()
    ]


@router.get("/{audit_id}", response_model=AuditDetailResponse)
async def get_audit(
    client_id: UUID,
    audit_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuditDetailResponse:
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    exists = await db.execute(
        text("SELECT 1 FROM audits WHERE id = :aid AND client_id = :cid"),
        {"aid": str(audit_id), "cid": str(client_id)},
    )
    if exists.first() is None:
        raise HTTPException(status_code=404, detail="Audit not found")
    return await _audit_detail(db, audit_id, client_id)


async def _audit_detail(db: AsyncSession, audit_id: UUID, client_id: UUID) -> AuditDetailResponse:
    res = await db.execute(
        text(
            "SELECT id, client_id, started_at, finished_at, score, summary FROM audits WHERE id = :aid"
        ),
        {"aid": str(audit_id)},
    )
    row = res.one()
    # site_pages holds the latest crawl per URL (no audit_id column), so scope
    # the response to the URLs this audit actually fetched.
    page_urls = (row.summary or {}).get("page_urls", [])
    findings_res = await db.execute(
        text(
            """
            SELECT id, category, severity, rule, detail, url, fix_owner, status
            FROM audit_findings WHERE audit_id = :aid
            ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                     category, rule
            """
        ),
        {"aid": str(audit_id)},
    )
    if page_urls:
        pages_res = await db.execute(
            text(
                """
                SELECT url, status_code, title, word_count, last_crawled_at,
                       (meta->>'description') AS description
                FROM site_pages WHERE client_id = :cid AND url = ANY(:urls)
                ORDER BY last_crawled_at DESC NULLS LAST LIMIT 50
                """
            ),
            {"cid": str(client_id), "urls": page_urls},
        )
    else:
        pages_res = await db.execute(
            text(
                """
                SELECT url, status_code, title, word_count, last_crawled_at,
                       (meta->>'description') AS description
                FROM site_pages WHERE client_id = :cid
                ORDER BY last_crawled_at DESC NULLS LAST LIMIT 50
                """
            ),
            {"cid": str(client_id)},
        )
    return AuditDetailResponse(
        id=row.id,
        client_id=row.client_id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        score=float(row.score) if row.score is not None else None,
        summary=row.summary or {},
        findings=[
            FindingResponse(
                id=f.id, category=f.category, severity=f.severity, rule=f.rule,
                detail=f.detail, url=f.url, fix_owner=f.fix_owner, status=f.status,
            )
            for f in findings_res.all()
        ],
        pages=[
            {
                "url": p.url,
                "status_code": p.status_code,
                "title": p.title,
                "word_count": p.word_count,
                "description": p.description,
                "last_crawled_at": p.last_crawled_at.isoformat() if p.last_crawled_at else None,
            }
            for p in pages_res.all()
        ],
    )
