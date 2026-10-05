"""Site audit routes — start/verify an audit on a live website and read results.

Milestone 3 adds:

- ``POST /clients/{id}/audits/{audit_id}/rerun`` — re-crawls the same site with
  the same rule engine, diffs findings by ``(rule, url)`` and marks vanished
  findings ``fixed`` (+ ``verified_at`` / ``resolved_in_audit_id``). Findings
  that are still present keep their operator status; regressions are reported.
- ``PATCH /clients/{id}/audits/{audit_id}/findings/{finding_id}`` — operator
  triage: open | in_progress | fixed | ignored.
- ``GET /clients/{id}/audits/{audit_id}/brief`` — PR-ready markdown dev brief.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from services.api.app.audit import AuditResult, run_site_audit, suggested_fix
from services.api.app.auth import (
    AuthUser,
    MemberRole,
    get_current_user,
    has_client_access,
    require_roles,
)
from services.api.app.config import settings
from services.api.app.db import get_db
from services.api.app.dev_brief import BriefFinding, build_dev_brief
from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}/audits", tags=["audits"])

TRIAGE_STATUSES = {"open", "in_progress", "fixed", "ignored"}
_ACTIVE_STATUSES = {"open", "in_progress"}


class StartAuditRequest(BaseModel):
    url: str | None = None  # defaults to https://{client.primary_domain}


class FindingStatusRequest(BaseModel):
    status: str


class FindingResponse(BaseModel):
    id: UUID
    category: str
    severity: str
    rule: str
    detail: str
    url: str | None
    fix_owner: str
    status: str
    suggested_fix: str | None = None
    verified_at: datetime | None = None


class AuditResponse(BaseModel):
    id: UUID
    client_id: UUID
    started_at: datetime | None
    finished_at: datetime | None
    score: float | None
    summary: dict[str, Any]
    rerun_of: UUID | None = None


class AuditDetailResponse(AuditResponse):
    findings: list[FindingResponse]
    pages: list[dict[str, Any]]


class RerunResponse(BaseModel):
    """Result of a fix-verification run: the new snapshot plus the diff."""

    audit: AuditDetailResponse
    rerun_of: UUID
    fixed: list[FindingResponse]
    still_present: list[FindingResponse]
    regressed: list[FindingResponse]
    new: list[FindingResponse]


class BriefResponse(BaseModel):
    filename: str
    markdown: str


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

    target = body.url or await _default_target(db, client_id)
    audit_id = uuid4()
    await db.execute(
        text("INSERT INTO audits (id, client_id, started_at) VALUES (:id, :cid, now())"),
        {"id": str(audit_id), "cid": str(client_id)},
    )
    await db.commit()

    await _run_and_persist(db, client_id, audit_id, target)
    return await _audit_detail(db, audit_id, client_id)


@router.post("/{audit_id}/rerun", response_model=RerunResponse)
async def rerun_audit(
    client_id: UUID,
    audit_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RerunResponse:
    """Re-run the same audit to verify fixes and report the diff (M3).

    Findings are keyed by ``(rule, url)``. Vanished findings become ``fixed``
    (verified_at + resolved_in_audit_id set); still-present findings keep their
    triage status (in_progress/ignored are carried onto the new snapshot);
    previously-fixed findings that reappear are reported as regressions.
    """
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    source = (
        await db.execute(
            text("SELECT id, summary FROM audits WHERE id = :aid AND client_id = :cid"),
            {"aid": str(audit_id), "cid": str(client_id)},
        )
    ).first()
    if source is None:
        raise HTTPException(status_code=404, detail="Audit not found")
    target = str((source.summary or {}).get("base_url") or "")
    if not target:
        target = await _default_target(db, client_id)

    old_findings = (
        await db.execute(
            text(
                "SELECT id, rule, url, status FROM audit_findings "
                "WHERE audit_id = :aid ORDER BY id"
            ),
            {"aid": str(audit_id)},
        )
    ).all()
    old_by_key: dict[tuple[str, str | None], Any] = {}
    for row in old_findings:
        old_by_key.setdefault((str(row.rule), row.url), row)

    new_audit_id = uuid4()
    await db.execute(
        text("INSERT INTO audits (id, client_id, started_at, rerun_of) VALUES (:id, :cid, now(), :src)"),
        {"id": str(new_audit_id), "cid": str(client_id), "src": str(audit_id)},
    )
    await db.commit()

    result = await _run_and_persist(db, client_id, new_audit_id, target)
    new_keys = {(f.rule, f.url) for f in result.findings}

    fixed_ids: list[UUID] = []
    still_keys: list[tuple[str, str | None]] = []
    regressed_keys: list[tuple[str, str | None]] = []
    # Carry triage state onto the new snapshot (ignore for regressions).
    carry_over: dict[tuple[str, str | None], str] = {}

    for key, row in old_by_key.items():
        old_status = str(row.status)
        if old_status in _ACTIVE_STATUSES:
            if key in new_keys:
                still_keys.append(key)
                if old_status == "in_progress":
                    carry_over[key] = "in_progress"
                await db.execute(
                    text("UPDATE audit_findings SET last_seen_at = now() WHERE id = :fid"),
                    {"fid": str(row.id)},
                )
            else:
                await db.execute(
                    text(
                        "UPDATE audit_findings SET status = 'fixed', verified_at = now(), "
                        "resolved_in_audit_id = :new WHERE id = :fid"
                    ),
                    {"fid": str(row.id), "new": str(new_audit_id)},
                )
                fixed_ids.append(row.id)
        elif old_status == "ignored" and key in new_keys:
            carry_over[key] = "ignored"
        elif old_status == "fixed" and key in new_keys:
            regressed_keys.append(key)

    for key, carry_status in carry_over.items():
        await db.execute(
            text(
                "UPDATE audit_findings SET status = :status "
                "WHERE audit_id = :aid AND rule = :rule AND coalesce(url, '') = coalesce(:url, '')"
            ),
            {"status": carry_status, "aid": str(new_audit_id), "rule": key[0], "url": key[1]},
        )
    await db.commit()

    fixed = [await _finding_by_id(db, fid) for fid in fixed_ids]
    still_present = [await _finding_by_key(db, new_audit_id, rule, url) for rule, url in still_keys]
    regressed = [await _finding_by_key(db, new_audit_id, rule, url) for rule, url in regressed_keys]
    new_findings = [f for f in result.findings if (f.rule, f.url) not in old_by_key]
    new_items = [await _finding_by_key(db, new_audit_id, f.rule, f.url) for f in new_findings]

    detail = await _audit_detail(db, new_audit_id, client_id)
    logger.info(
        "audit_rerun_completed",
        audit_id=str(new_audit_id), source=str(audit_id),
        fixed=len(fixed), still_present=len(still_present), regressed=len(regressed), new=len(new_items),
    )
    return RerunResponse(
        audit=detail,
        rerun_of=audit_id,
        fixed=fixed,
        still_present=still_present,
        regressed=regressed,
        new=new_items,
    )


@router.patch("/{audit_id}/findings/{finding_id}", response_model=FindingResponse)
async def triage_finding(
    client_id: UUID,
    audit_id: UUID,
    finding_id: UUID,
    body: FindingStatusRequest,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FindingResponse:
    """Operator triage of one finding: open | in_progress | fixed | ignored."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if body.status not in TRIAGE_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(TRIAGE_STATUSES)}")

    res = await db.execute(
        text(
            "UPDATE audit_findings SET status = :status "
            "WHERE id = :fid AND audit_id = :aid AND client_id = :cid RETURNING id"
        ),
        {"status": body.status, "fid": str(finding_id), "aid": str(audit_id), "cid": str(client_id)},
    )
    if res.first() is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    await db.commit()
    return await _finding_by_id(db, finding_id)


@router.get("/{audit_id}/brief", response_model=BriefResponse)
async def get_dev_brief(
    client_id: UUID,
    audit_id: UUID,
    user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BriefResponse:
    """PR-ready markdown dev brief for this audit snapshot (FR-17)."""
    if not await has_client_access(user, client_id, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    audit = (
        await db.execute(
            text(
                "SELECT a.id, a.started_at, a.finished_at, a.score, a.summary, c.name AS client_name "
                "FROM audits a JOIN clients c ON c.id = a.client_id "
                "WHERE a.id = :aid AND a.client_id = :cid"
            ),
            {"aid": str(audit_id), "cid": str(client_id)},
        )
    ).first()
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    rows = (
        await db.execute(
            text(
                "SELECT category, severity, rule, detail, url, fix_owner, status, suggested_fix "
                "FROM audit_findings WHERE audit_id = :aid "
                "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END"
            ),
            {"aid": str(audit_id)},
        )
    ).all()
    findings = [
        BriefFinding(
            category=str(r.category), severity=str(r.severity), rule=str(r.rule),
            detail=str(r.detail), url=r.url, fix_owner=str(r.fix_owner), status=str(r.status),
            suggested_fix=r.suggested_fix or suggested_fix(str(r.rule)),
        )
        for r in rows
    ]
    markdown = build_dev_brief(
        client_name=str(audit.client_name),
        audit_id=str(audit.id),
        finished_at=audit.finished_at,
        score=float(audit.score) if audit.score is not None else None,
        summary=audit.summary or {},
        findings=findings,
    )
    slug = re.sub(r"[^a-z0-9]+", "-", str(audit.client_name).casefold()).strip("-") or "website"
    day = (audit.finished_at or audit.started_at)
    filename = f"dev-brief-{slug}-{day.strftime('%Y%m%d') if day else 'draft'}.md"
    return BriefResponse(filename=filename, markdown=markdown)


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
            "SELECT id, client_id, started_at, finished_at, score, summary, rerun_of FROM audits "
            "WHERE client_id = :cid ORDER BY started_at DESC LIMIT 20"
        ),
        {"cid": str(client_id)},
    )
    return [
        AuditResponse(
            id=r.id, client_id=r.client_id, started_at=r.started_at,
            finished_at=r.finished_at, score=float(r.score) if r.score is not None else None,
            summary=r.summary or {}, rerun_of=r.rerun_of,
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


# ── Internals ────────────────────────────────────────────────────────────────


async def _default_target(db: AsyncSession, client_id: UUID) -> str:
    res = await db.execute(
        text("SELECT primary_domain FROM clients WHERE id = :cid"), {"cid": str(client_id)}
    )
    domain = res.scalar()
    if not domain:
        raise HTTPException(status_code=404, detail="Client not found")
    return f"https://{domain}"


async def _audit_context(db: AsyncSession, client_id: UUID) -> tuple[str, list[str], str]:
    """Brand name, aliases and the PageSpeed key for entity-drift + speed checks."""
    res = await db.execute(text("SELECT name FROM clients WHERE id = :cid"), {"cid": str(client_id)})
    name = str(res.scalar() or "")
    alias_res = await db.execute(
        text("SELECT alias FROM brand_aliases WHERE client_id = :cid ORDER BY is_primary DESC, alias"),
        {"cid": str(client_id)},
    )
    aliases = [str(r.alias) for r in alias_res.all() if r.alias]
    return name, aliases, settings.pagespeed_api_key


async def _run_and_persist(
    db: AsyncSession, client_id: UUID, audit_id: UUID, target: str
) -> AuditResult:
    """Run the crawler and persist findings/pages; mark the audit finished."""
    name, aliases, pagespeed_key = await _audit_context(db, client_id)
    try:
        result = await run_site_audit(
            target,
            entity_names=[name, *aliases] if name else aliases,
            pagespeed_key=pagespeed_key,
        )
    except Exception as exc:
        await db.execute(
            text("UPDATE audits SET finished_at = now(), summary = :summary WHERE id = :id"),
            {"id": str(audit_id), "summary": '{"error": true}'},
        )
        await db.commit()
        logger.exception("site_audit_failed", audit_id=str(audit_id), error=str(exc))
        raise HTTPException(status_code=502, detail=f"Audit failed: {exc}") from exc

    for f in result.findings:
        await db.execute(
            text(
                """
                INSERT INTO audit_findings (id, audit_id, client_id, category, severity, url, rule, detail,
                    fix_owner, status, suggested_fix)
                VALUES (:id, :aid, :cid, :cat, :sev, :url, :rule, :detail, :owner, 'open', :fix)
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
                "fix": suggested_fix(f.rule) or None,
            },
        )

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
    return result


async def _audit_detail(db: AsyncSession, audit_id: UUID, client_id: UUID) -> AuditDetailResponse:
    res = await db.execute(
        text(
            "SELECT id, client_id, started_at, finished_at, score, summary, rerun_of "
            "FROM audits WHERE id = :aid"
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
            SELECT id, category, severity, rule, detail, url, fix_owner, status, suggested_fix, verified_at
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
        rerun_of=row.rerun_of,
        findings=[
            FindingResponse(
                id=f.id, category=f.category, severity=f.severity, rule=f.rule,
                detail=f.detail, url=f.url, fix_owner=f.fix_owner, status=f.status,
                suggested_fix=f.suggested_fix, verified_at=f.verified_at,
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


async def _finding_by_id(db: AsyncSession, finding_id: UUID) -> FindingResponse:
    res = await db.execute(
        text(
            "SELECT id, category, severity, rule, detail, url, fix_owner, status, suggested_fix, verified_at "
            "FROM audit_findings WHERE id = :fid"
        ),
        {"fid": str(finding_id)},
    )
    return _finding_row(res.one())


async def _finding_by_key(
    db: AsyncSession, audit_id: UUID, rule: str, url: str | None
) -> FindingResponse:
    res = await db.execute(
        text(
            "SELECT id, category, severity, rule, detail, url, fix_owner, status, suggested_fix, verified_at "
            "FROM audit_findings WHERE audit_id = :aid AND rule = :rule "
            "AND coalesce(url, '') = coalesce(:url, '') LIMIT 1"
        ),
        {"aid": str(audit_id), "rule": rule, "url": url},
    )
    return _finding_row(res.one())


def _finding_row(row: Any) -> FindingResponse:
    return FindingResponse(
        id=row.id, category=row.category, severity=row.severity, rule=row.rule,
        detail=row.detail, url=row.url, fix_owner=row.fix_owner, status=row.status,
        suggested_fix=row.suggested_fix, verified_at=row.verified_at,
    )
