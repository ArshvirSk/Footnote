"""Shared Pydantic schemas for the API layer.

These are the request/response models used by API routes.
Domain types that cross module boundaries live here.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


# ──── Enums (mirror DB enums) ────


class EngineType(str, Enum):
    CHATGPT = "chatgpt"
    GEMINI = "gemini"
    PERPLEXITY = "perplexity"
    CLAUDE = "claude"
    GROK = "grok"
    GOOGLE_AIO = "google_aio"


class MemberRoleType(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    STRATEGIST = "strategist"
    EDITOR = "editor"
    CLIENT_APPROVER = "client_approver"
    CLIENT_VIEWER = "client_viewer"


class JobStatusType(str, Enum):
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
