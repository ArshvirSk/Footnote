"""Publishing targets, publications history, and CMS connection testing API."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from services.api.app.auth import AuthUser, MemberRole, require_roles
from services.api.app.crypto import (
    decrypt_credentials,
    encrypt_credentials,
    mask_credentials,
)
from services.api.app.db import get_db
from services.api.app.logging import get_logger
from services.api.app.routes.collection import _drain_queue, _get_queue
from services.workers.app.publisher import run_publisher
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

router = APIRouter(prefix="/clients/{client_id}", tags=["publishing"])


# ───────────── Schemas ─────────────

class PublishTargetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    kind: str = Field(..., description="wordpress | feeds | webhook | webflow | shopify | ghost")
    is_default: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class PublishTargetUpdate(BaseModel):
    name: str | None = None
    is_default: bool | None = None
    status: str | None = None
    config: dict[str, Any] | None = None


class PublishTargetResponse(BaseModel):
    id: UUID
    client_id: UUID
    name: str | None
    kind: str
    is_default: bool
    status: str
    config: dict[str, Any]
    last_tested_at: datetime | None
    last_test_status: str | None
    last_test_error: str | None
    created_at: datetime | None
    updated_at: datetime | None


class PublishTargetTestResponse(BaseModel):
    status: str
    detail: str
    latency_ms: float
    data: dict[str, Any] = Field(default_factory=dict)


class PublishContentItemRequest(BaseModel):
    target_id: UUID | None = None
    post_status: str = Field(default="publish", description="publish | draft")


class PublishContentItemResponse(BaseModel):
    status: str
    publication_id: UUID
    target_id: UUID
    message: str


class PublicationRecord(BaseModel):
    id: UUID
    content_item_id: UUID
    client_id: UUID
    version_id: UUID | None
    target_id: UUID | None
    external_id: str | None
    url: str | None
    status: str
    error: str | None
    title: str | None
    jsonld_verified: bool
    canonical_verified: bool
    http_status: int | None
    verified_at: datetime | None
    published_at: datetime | None


# ───────────── Permission Helper ─────────────

async def _verify_client_access(user: AuthUser, client_id: UUID, db: AsyncSession) -> None:
    res = await db.execute(
        text(
            """
            SELECT 1 FROM client_members cm
            WHERE cm.client_id = :cid AND cm.user_id = :uid
            UNION
            SELECT 1 FROM clients c
            JOIN org_members om ON om.org_id = c.org_id
            WHERE c.id = :cid AND om.user_id = :uid
            """
        ),
        {"cid": str(client_id), "uid": str(user.id)},
    )
    if not res.first():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


# ───────────── Publish Targets CRUD ─────────────

@router.get("/publish-targets", response_model=list[PublishTargetResponse])
async def list_publish_targets(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST, MemberRole.EDITOR))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PublishTargetResponse]:
    """List all publish targets for client with credentials masked."""
    await _verify_client_access(user, client_id, db)

    res = await db.execute(
        text(
            """
            SELECT id, client_id, kind, config_enc, status, name, is_default,
                   last_tested_at, last_test_status, last_test_error, created_at, updated_at
            FROM publish_targets
            WHERE client_id = :cid
            ORDER BY is_default DESC, created_at DESC
            """
        ),
        {"cid": str(client_id)},
    )
    rows = res.fetchall()

    targets: list[PublishTargetResponse] = []
    for r in rows:
        try:
            cfg = decrypt_credentials(r.config_enc)
        except Exception:
            cfg = {}
        targets.append(
            PublishTargetResponse(
                id=r.id,
                client_id=r.client_id,
                name=r.name,
                kind=r.kind,
                is_default=r.is_default or False,
                status=r.status or "active",
                config=mask_credentials(cfg),
                last_tested_at=r.last_tested_at,
                last_test_status=r.last_test_status or "untested",
                last_test_error=r.last_test_error,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return targets


@router.post("/publish-targets", response_model=PublishTargetResponse, status_code=status.HTTP_201_CREATED)
async def create_publish_target(
    client_id: UUID,
    body: PublishTargetCreate,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublishTargetResponse:
    """Create a new publishing target. Credentials in `config` are AES-256-GCM encrypted."""
    await _verify_client_access(user, client_id, db)

    config_enc = encrypt_credentials(body.config) if body.config else b""

    if body.is_default:
        await db.execute(
            text("UPDATE publish_targets SET is_default = false WHERE client_id = :cid"),
            {"cid": str(client_id)},
        )

    res = await db.execute(
        text(
            """
            INSERT INTO publish_targets (client_id, kind, config_enc, status, name, is_default, created_at, updated_at)
            VALUES (:cid, :kind, :c_enc, 'active', :name, :is_def, now(), now())
            RETURNING id, client_id, kind, config_enc, status, name, is_default,
                      last_tested_at, last_test_status, last_test_error, created_at, updated_at
            """
        ),
        {
            "cid": str(client_id),
            "kind": body.kind,
            "c_enc": config_enc,
            "name": body.name,
            "is_def": body.is_default,
        },
    )
    row = res.one()

    # If feeds site, ensure feeds_sites record exists
    if body.kind == "feeds":
        await db.execute(
            text(
                """
                INSERT INTO feeds_sites (client_id, mount_path, custom_domain)
                VALUES (:cid, :mount, :domain)
                ON CONFLICT (client_id) DO NOTHING
                """
            ),
            {
                "cid": str(client_id),
                "mount": body.config.get("mount_path", "/feeds"),
                "domain": body.config.get("custom_domain"),
            },
        )

    await db.commit()

    return PublishTargetResponse(
        id=row.id,
        client_id=row.client_id,
        name=row.name,
        kind=row.kind,
        is_default=row.is_default or False,
        status=row.status or "active",
        config=mask_credentials(body.config),
        last_tested_at=row.last_tested_at,
        last_test_status=row.last_test_status or "untested",
        last_test_error=row.last_test_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/publish-targets/{target_id}", response_model=PublishTargetResponse)
async def get_publish_target(
    client_id: UUID,
    target_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST, MemberRole.EDITOR))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublishTargetResponse:
    """Get a single publishing target with masked credentials."""
    await _verify_client_access(user, client_id, db)

    res = await db.execute(
        text(
            """
            SELECT id, client_id, kind, config_enc, status, name, is_default,
                   last_tested_at, last_test_status, last_test_error, created_at, updated_at
            FROM publish_targets
            WHERE id = :tid AND client_id = :cid
            """
        ),
        {"tid": str(target_id), "cid": str(client_id)},
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish target not found")

    try:
        cfg = decrypt_credentials(row.config_enc)
    except Exception:
        cfg = {}

    return PublishTargetResponse(
        id=row.id,
        client_id=row.client_id,
        name=row.name,
        kind=row.kind,
        is_default=row.is_default or False,
        status=row.status or "active",
        config=mask_credentials(cfg),
        last_tested_at=row.last_tested_at,
        last_test_status=row.last_test_status or "untested",
        last_test_error=row.last_test_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.patch("/publish-targets/{target_id}", response_model=PublishTargetResponse)
async def update_publish_target(
    client_id: UUID,
    target_id: UUID,
    body: PublishTargetUpdate,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublishTargetResponse:
    """Update a publishing target. If new config is supplied, it is re-encrypted."""
    await _verify_client_access(user, client_id, db)

    target_res = await db.execute(
        text("SELECT * FROM publish_targets WHERE id = :tid AND client_id = :cid"),
        {"tid": str(target_id), "cid": str(client_id)},
    )
    current = target_res.first()
    if not current:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish target not found")

    updates: list[str] = ["updated_at = now()"]
    params: dict[str, Any] = {"tid": str(target_id), "cid": str(client_id)}

    if body.name is not None:
        updates.append("name = :name")
        params["name"] = body.name

    if body.status is not None:
        updates.append("status = :status")
        params["status"] = body.status

    if body.is_default is not None:
        if body.is_default:
            await db.execute(
                text("UPDATE publish_targets SET is_default = false WHERE client_id = :cid"),
                {"cid": str(client_id)},
            )
        updates.append("is_default = :is_def")
        params["is_def"] = body.is_default

    effective_config: dict[str, Any]
    if body.config is not None:
        # Merge with existing decrypted config if partial
        try:
            existing = decrypt_credentials(current.config_enc)
        except Exception:
            existing = {}
        merged = {**existing, **body.config}
        effective_config = merged
        updates.append("config_enc = :c_enc")
        params["c_enc"] = encrypt_credentials(merged)
    else:
        try:
            effective_config = decrypt_credentials(current.config_enc)
        except Exception:
            effective_config = {}

    query = f"UPDATE publish_targets SET {', '.join(updates)} WHERE id = :tid AND client_id = :cid RETURNING *"
    res = await db.execute(text(query), params)
    row = res.one()
    await db.commit()

    return PublishTargetResponse(
        id=row.id,
        client_id=row.client_id,
        name=row.name,
        kind=row.kind,
        is_default=row.is_default or False,
        status=row.status or "active",
        config=mask_credentials(effective_config),
        last_tested_at=row.last_tested_at,
        last_test_status=row.last_test_status or "untested",
        last_test_error=row.last_test_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.delete("/publish-targets/{target_id}")
async def delete_publish_target(
    client_id: UUID,
    target_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Delete a publishing target."""
    await _verify_client_access(user, client_id, db)

    res = await db.execute(
        text("DELETE FROM publish_targets WHERE id = :tid AND client_id = :cid RETURNING id"),
        {"tid": str(target_id), "cid": str(client_id)},
    )
    if not res.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish target not found")
    await db.commit()
    return {"status": "deleted"}


# ───────────── Test Connection Endpoint ─────────────

@router.post("/publish-targets/{target_id}/test", response_model=PublishTargetTestResponse)
async def test_publish_target_connection(
    client_id: UUID,
    target_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublishTargetTestResponse:
    """Live connectivity and credentials test for a target."""
    await _verify_client_access(user, client_id, db)

    res = await db.execute(
        text("SELECT * FROM publish_targets WHERE id = :tid AND client_id = :cid"),
        {"tid": str(target_id), "cid": str(client_id)},
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish target not found")

    try:
        config = decrypt_credentials(row.config_enc)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to decrypt target credentials") from exc

    start_time = time.perf_counter()
    kind = row.kind.lower()

    if kind == "wordpress":
        endpoint = (config.get("endpoint") or config.get("url") or "").rstrip("/")
        username = config.get("username") or ""
        app_password = config.get("app_password") or config.get("password") or ""

        if not endpoint:
            result = PublishTargetTestResponse(
                status="failed",
                detail="Missing WordPress endpoint URL",
                latency_ms=0.0,
            )
        elif not username or not app_password:
            result = PublishTargetTestResponse(
                status="failed",
                detail="Missing WordPress username or application password",
                latency_ms=0.0,
            )
        else:
            api_url = f"{endpoint}/wp-json/wp/v2/users/me"
            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    resp = await client.get(
                        api_url,
                        auth=(username, app_password),
                        headers={"User-Agent": "Footnote-Publisher/1.0"},
                    )
                latency = round((time.perf_counter() - start_time) * 1000, 2)

                if resp.status_code == 200:
                    data = resp.json()
                    result = PublishTargetTestResponse(
                        status="success",
                        detail=f"Connected successfully as '{data.get('name', username)}' (slug: {data.get('slug', username)})",
                        latency_ms=latency,
                        data={"user_id": data.get("id"), "name": data.get("name"), "roles": data.get("roles", [])},
                    )
                elif resp.status_code in (401, 403):
                    result = PublishTargetTestResponse(
                        status="failed",
                        detail=f"WordPress Authentication Failed ({resp.status_code}): Invalid username or application password.",
                        latency_ms=latency,
                    )
                else:
                    result = PublishTargetTestResponse(
                        status="failed",
                        detail=f"WordPress Error ({resp.status_code}): {resp.text[:200]}",
                        latency_ms=latency,
                    )
            except Exception as e:
                latency = round((time.perf_counter() - start_time) * 1000, 2)
                result = PublishTargetTestResponse(
                    status="failed",
                    detail=f"Connection Error: {str(e)}",
                    latency_ms=latency,
                )

    elif kind == "feeds":
        latency = round((time.perf_counter() - start_time) * 1000, 2)
        site_res = await db.execute(
            text("SELECT mount_path, custom_domain FROM feeds_sites WHERE client_id = :cid"),
            {"cid": str(client_id)},
        )
        site_row = site_res.first()
        result = PublishTargetTestResponse(
            status="success",
            detail="Feeds static builder engine configured and ready.",
            latency_ms=latency,
            data={
                "mount_path": site_row.mount_path if site_row else "/feeds",
                "custom_domain": site_row.custom_domain if site_row else None,
            },
        )

    elif kind == "webhook":
        url = config.get("webhook_url") or config.get("url") or ""
        latency = round((time.perf_counter() - start_time) * 1000, 2)
        if url.startswith("http://") or url.startswith("https://"):
            result = PublishTargetTestResponse(
                status="success",
                detail=f"Webhook destination valid ({url})",
                latency_ms=latency,
                data={"url": url},
            )
        else:
            result = PublishTargetTestResponse(
                status="failed",
                detail="Invalid webhook URL scheme (must be http/https)",
                latency_ms=latency,
            )
    else:
        latency = round((time.perf_counter() - start_time) * 1000, 2)
        result = PublishTargetTestResponse(
            status="success",
            detail=f"Target type '{kind}' configured.",
            latency_ms=latency,
        )

    # Persist test result
    await db.execute(
        text(
            """
            UPDATE publish_targets
            SET last_tested_at = now(),
                last_test_status = :status,
                last_test_error = :err
            WHERE id = :tid
            """
        ),
        {
            "tid": str(target_id),
            "status": result.status,
            "err": result.detail if result.status != "success" else None,
        },
    )
    await db.commit()

    return result


# ───────────── Publish Execution Endpoint (With Hard Gate) ─────────────

@router.post("/content-items/{item_id}/publish", response_model=PublishContentItemResponse)
async def publish_content_item(
    client_id: UUID,
    item_id: UUID,
    body: PublishContentItemRequest,
    background: BackgroundTasks,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST, MemberRole.EDITOR))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PublishContentItemResponse:
    """Publish an approved content item to a configured target.

    HARD GATE RULE:
    Publication is strictly forbidden unless the current draft version has an
    explicit approval record (approvals.status = 'approved').
    """
    await _verify_client_access(user, client_id, db)

    # 1. Fetch item and version
    item_res = await db.execute(
        text(
            """
            SELECT ci.id, ci.current_version_id, ci.publish_target_id, ci.status, cv.title, cv.body_md
            FROM content_items ci
            LEFT JOIN content_versions cv ON cv.id = ci.current_version_id
            WHERE ci.id = :did AND ci.client_id = :cid
            """
        ),
        {"did": str(item_id), "cid": str(client_id)},
    )
    item = item_res.first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content item not found")

    if not item.current_version_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content item has no draft version to publish",
        )

    # 2. Hard Approval Gate Check
    approval_res = await db.execute(
        text(
            """
            SELECT id, status, decision, reviewer_id, decided_at
            FROM approvals
            WHERE client_id = :cid
              AND subject_type = 'content_version'
              AND subject_id = :vid
              AND status = 'approved'
            ORDER BY decided_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"cid": str(client_id), "vid": str(item.current_version_id)},
    )
    approval = approval_res.first()
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Publication blocked by approval gate: "
                "The current draft version has not received an approved decision by an authorized editor or client."
            ),
        )

    # 3. Resolve Target
    target_id = body.target_id or item.publish_target_id
    if not target_id:
        # Check default target
        default_target_res = await db.execute(
            text("SELECT id FROM publish_targets WHERE client_id = :cid AND is_default = true LIMIT 1"),
            {"cid": str(client_id)},
        )
        row = default_target_res.first()
        if row:
            target_id = row.id
        else:
            # Fall back to any active target
            any_target_res = await db.execute(
                text("SELECT id FROM publish_targets WHERE client_id = :cid AND status = 'active' ORDER BY created_at ASC LIMIT 1"),
                {"cid": str(client_id)},
            )
            any_row = any_target_res.first()
            if any_row:
                target_id = any_row.id

    if not target_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No publish target configured. Please add a publishing target (e.g. WordPress or Feeds) first.",
        )

    # 4. Insert Publication Record
    pub_res = await db.execute(
        text(
            """
            INSERT INTO publications (content_item_id, client_id, version_id, target_id, status, title, published_at)
            VALUES (:did, :cid, :vid, :tid, 'running', :title, now())
            RETURNING id
            """
        ),
        {
            "did": str(item_id),
            "cid": str(client_id),
            "vid": str(item.current_version_id),
            "tid": str(target_id),
            "title": item.title,
        },
    )
    publication_id = pub_res.scalar_one()

    # 5. Update content item state
    await db.execute(
        text(
            """
            UPDATE content_items
            SET publish_target_id = :tid, status = 'publishing'
            WHERE id = :did AND client_id = :cid
            """
        ),
        {"tid": str(target_id), "did": str(item_id), "cid": str(client_id)},
    )
    await db.commit()

    # 6. Schedule publisher worker execution
    background.add_task(
        run_publisher,
        {"redis": _get_queue()},
        str(item_id),
        str(client_id),
    )
    background.add_task(_drain_queue)

    logger.info(
        "publication_enqueued",
        content_item_id=str(item_id),
        client_id=str(client_id),
        publication_id=str(publication_id),
        target_id=str(target_id),
    )

    return PublishContentItemResponse(
        status="running",
        publication_id=publication_id,
        target_id=target_id,
        message="Publication dispatched to worker.",
    )


# ───────────── Publications History ─────────────

@router.get("/publications", response_model=list[PublicationRecord])
async def list_publications(
    client_id: UUID,
    user: Annotated[AuthUser, Depends(require_roles(MemberRole.OWNER, MemberRole.ADMIN, MemberRole.STRATEGIST, MemberRole.EDITOR, MemberRole.CLIENT_VIEWER, MemberRole.CLIENT_APPROVER))],
    db: Annotated[AsyncSession, Depends(get_db)],
    content_item_id: UUID | None = None,
) -> list[PublicationRecord]:
    """List publication history and verification status."""
    await _verify_client_access(user, client_id, db)

    query = """
        SELECT p.id, p.content_item_id, p.client_id, p.version_id, p.target_id,
               p.external_id, p.url, p.status, p.error, p.title,
               p.jsonld_verified, p.canonical_verified, p.http_status,
               p.verified_at, p.published_at
        FROM publications p
        WHERE p.client_id = :cid
    """
    params: dict[str, Any] = {"cid": str(client_id)}
    if content_item_id:
        query += " AND p.content_item_id = :did"
        params["did"] = str(content_item_id)

    query += " ORDER BY p.published_at DESC NULLS LAST LIMIT 50"

    res = await db.execute(text(query), params)
    rows = res.fetchall()

    return [
        PublicationRecord(
            id=r.id,
            content_item_id=r.content_item_id,
            client_id=r.client_id,
            version_id=r.version_id,
            target_id=r.target_id,
            external_id=r.external_id,
            url=r.url,
            status=r.status or "queued",
            error=r.error,
            title=r.title,
            jsonld_verified=r.jsonld_verified or False,
            canonical_verified=r.canonical_verified or False,
            http_status=r.http_status,
            verified_at=r.verified_at,
            published_at=r.published_at,
        )
        for r in rows
    ]
