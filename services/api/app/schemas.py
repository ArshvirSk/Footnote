"""Shared Pydantic schemas for the API layer.

These are the request/response models used by API routes.
Domain types that cross module boundaries live here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

# ──── Enums (mirror DB enums) ────


class EngineType(StrEnum):
    CHATGPT = "chatgpt"
    GEMINI = "gemini"
    PERPLEXITY = "perplexity"
    CLAUDE = "claude"
    GROK = "grok"
    GOOGLE_AIO = "google_aio"


class MemberRoleType(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    STRATEGIST = "strategist"
    EDITOR = "editor"
    CLIENT_APPROVER = "client_approver"
    CLIENT_VIEWER = "client_viewer"


class JobStatusType(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


# ──── Organizations ────


class OrgResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    created_at: datetime


class OrgCreateRequest(BaseModel):
    name: str
    slug: str


# ──── Clients ────


class ClientResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    primary_domain: str
    industry: str | None = None
    country: str = "IN"
    status: str = "onboarding"
    settings: dict[str, object] = Field(default_factory=dict)
    onboarded_at: datetime | None = None
    created_at: datetime
    is_demo: bool = False


class ChecklistItemResponse(BaseModel):
    """One item of the 7-item website setup checklist."""

    key: str
    label: str
    why: str
    done: bool
    detail: str
    href: str


class ClientSummaryResponse(ClientResponse):
    """Client row enriched with derived status and website-list facts."""

    derived_status: str = "onboarding"
    setup_progress: int = 0
    setup_total: int = 7
    checklist: list[ChecklistItemResponse] = Field(default_factory=list)
    last_collection_at: datetime | None = None
    visibility_pct: float | None = None
    open_issues: int = 0
    pending_approvals: int = 0
    active_prompts: int = 0


class ClientCreateRequest(BaseModel):
    name: str
    primary_domain: str
    industry: str | None = None
    country: str = "IN"


# ──── Auth ────


class MeResponse(BaseModel):
    user_id: UUID
    email: str
    org_id: UUID | None = None
    role: MemberRoleType | None = None
    client_ids: list[UUID] = []


# ──── Health ────


class HealthResponse(BaseModel):
    status: str = "ok"
    environment: str
    version: str = "0.1.0"
