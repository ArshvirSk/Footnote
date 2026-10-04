"""Derived website status and the 7-item setup checklist (Milestone 1).

The website status shown in the console is *derived* from the setup checklist —
it can never contradict it. ``clients.status`` is only honoured for explicit
lifecycle states (paused / churned); otherwise the derived value wins:

    paused | churned   -> explicit lifecycle (operator-set)
    active             -> all 7 checklist items complete
    onboarding         -> anything less

Every query is scoped by ``client_id`` (and org for list queries). The facts are
plain counts so the checklist is re-computable at any time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SETUP_TOTAL = 7
MIN_ACTIVE_PROMPTS = 25
LIFECYCLE_STATUSES = {"paused", "churned"}

# key, label, why it matters, where to fix it (relative to /ops)
SETUP_ITEMS: list[tuple[str, str, str, str]] = [
    ("brand_profile", "Brand profile", "Voice, positioning and proof points used by every agent.", "/ops/websites/{id}#brand"),
    ("competitors", "Competitors", "Rivals tracked in citation and mention analysis.", "/ops/websites/{id}#competitors"),
    ("personas", "Personas", "Buyer personas that prompts are mapped to.", "/ops/websites/{id}#personas"),
    ("prompts", f"{MIN_ACTIVE_PROMPTS}+ active prompts", "The tracked question set collected across engines.", "/ops/prompts"),
    ("baseline", "Baseline collection", "First real collection run to measure visibility.", "/ops/prompts"),
    ("site_audit", "Site audit", "Live crawl scored for answer-engine readiness.", "/ops/site-audit"),
    ("publish_target", "Publish target", "Where approved content gets published.", "/ops/websites/{id}#publishing"),
]


@dataclass(frozen=True)
class WebsiteFacts:
    """Counts backing the checklist and derived status (per client)."""

    brand_profile_items: int = 0
    competitors_count: int = 0
    personas_count: int = 0
    active_prompts: int = 0
    succeeded_answers: int = 0
    finished_audits: int = 0
    publish_targets: int = 0
    open_gaps: int = 0
    open_findings: int = 0
    pending_approvals: int = 0
    visible_7d: int = 0
    tracked_7d: int = 0
    last_collection_at: datetime | None = None
    last_audit_at: datetime | None = None

    @property
    def setup_progress(self) -> int:
        return sum(1 for item in checklist(self) if item["done"])

    @property
    def open_issues(self) -> int:
        return self.open_gaps + self.open_findings

    @property
    def visibility_pct(self) -> float | None:
        """Visibility as a 0..1 ratio (the UI formats it as a percentage)."""
        if not self.tracked_7d:
            return None
        return round(self.visible_7d / self.tracked_7d, 4)


def facts_from_row(row: Any) -> WebsiteFacts:
    """Build facts from a row produced by ``CLIENT_FACTS_SQL``."""
    return WebsiteFacts(
        brand_profile_items=row.brand_profile_items or 0,
        competitors_count=row.competitors_count or 0,
        personas_count=row.personas_count or 0,
        active_prompts=row.active_prompts or 0,
        succeeded_answers=row.succeeded_answers or 0,
        finished_audits=row.finished_audits or 0,
        publish_targets=row.publish_targets or 0,
        open_gaps=row.open_gaps or 0,
        open_findings=row.open_findings or 0,
        pending_approvals=row.pending_approvals or 0,
        visible_7d=row.visible_7d or 0,
        tracked_7d=row.tracked_7d or 0,
        last_collection_at=row.last_collection_at,
        last_audit_at=row.last_audit_at,
    )


def checklist(facts: WebsiteFacts, client_id: str = "") -> list[dict[str, Any]]:
    """The seven setup items with done state, detail and fix link."""
    states: dict[str, tuple[bool, str]] = {
        "brand_profile": (
            facts.brand_profile_items > 0,
            "Profile saved" if facts.brand_profile_items > 0 else "Not filled in yet",
        ),
        "competitors": (
            facts.competitors_count > 0,
            f"{facts.competitors_count} tracked" if facts.competitors_count else "No competitors added",
        ),
        "personas": (
            facts.personas_count > 0,
            f"{facts.personas_count} defined" if facts.personas_count else "No personas defined",
        ),
        "prompts": (
            facts.active_prompts >= MIN_ACTIVE_PROMPTS,
            f"{facts.active_prompts} of {MIN_ACTIVE_PROMPTS} active",
        ),
        "baseline": (
            facts.succeeded_answers > 0,
            f"{facts.succeeded_answers} answers collected" if facts.succeeded_answers else "No collection run yet",
        ),
        "site_audit": (
            facts.finished_audits > 0,
            f"{facts.finished_audits} audit(s)" if facts.finished_audits else "No audit run yet",
        ),
        "publish_target": (
            facts.publish_targets > 0,
            "Configured" if facts.publish_targets else "Not configured",
        ),
    }
    items: list[dict[str, Any]] = []
    for key, label, why, href in SETUP_ITEMS:
        done, detail = states[key]
        items.append(
            {
                "key": key,
                "label": label,
                "why": why,
                "done": done,
                "detail": detail,
                "href": href.format(id=client_id),
            }
        )
    return items


def derive_status(facts: WebsiteFacts, lifecycle_status: str) -> str:
    """Derived website status; explicit lifecycle states win, else checklist."""
    if lifecycle_status in LIFECYCLE_STATUSES:
        return lifecycle_status
    return "active" if facts.setup_progress == SETUP_TOTAL else "onboarding"


# One query per list — every fact is a subselect scoped to that client.
CLIENT_FACTS_SQL = """
SELECT c.id, c.org_id, c.name, c.primary_domain, c.industry, c.country,
       c.status, c.settings, c.onboarded_at, c.created_at, c.is_demo,
       (SELECT count(*) FROM brand_profiles bp
         WHERE bp.client_id = c.id
           AND (coalesce(bp.voice, '') <> '' OR coalesce(bp.positioning, '') <> ''
                OR jsonb_array_length(coalesce(bp.products, '[]'::jsonb)) > 0
                OR jsonb_array_length(coalesce(bp.proof_points, '[]'::jsonb)) > 0)) AS brand_profile_items,
       (SELECT count(*) FROM competitors x WHERE x.client_id = c.id) AS competitors_count,
       (SELECT count(*) FROM personas x WHERE x.client_id = c.id) AS personas_count,
       (SELECT count(*) FROM prompts x WHERE x.client_id = c.id AND x.is_active) AS active_prompts,
       (SELECT count(*) FROM answers x WHERE x.client_id = c.id AND x.status = 'succeeded') AS succeeded_answers,
       (SELECT count(*) FROM audits x WHERE x.client_id = c.id AND x.finished_at IS NOT NULL) AS finished_audits,
       (SELECT count(*) FROM publish_targets x WHERE x.client_id = c.id) AS publish_targets,
       (SELECT count(*) FROM gaps g WHERE g.client_id = c.id AND g.status = 'open') AS open_gaps,
       (SELECT count(*) FROM audit_findings af
         WHERE af.status = 'open' AND af.audit_id = (
           SELECT a2.id FROM audits a2 WHERE a2.client_id = c.id
           ORDER BY a2.started_at DESC LIMIT 1)) AS open_findings,
       (SELECT count(*) FROM approvals ap
         WHERE ap.client_id = c.id AND ap.status = 'pending') AS pending_approvals,
       (SELECT coalesce(sum(dm.prompts_visible), 0) FROM daily_metrics dm
         WHERE dm.client_id = c.id AND dm.day >= current_date - 6) AS visible_7d,
       (SELECT coalesce(sum(dm.prompts_tracked), 0) FROM daily_metrics dm
         WHERE dm.client_id = c.id AND dm.day >= current_date - 6) AS tracked_7d,
       (SELECT max(x.collected_at) FROM answers x
         WHERE x.client_id = c.id AND x.status = 'succeeded') AS last_collection_at,
       (SELECT max(x.finished_at) FROM audits x WHERE x.client_id = c.id) AS last_audit_at
FROM clients c
"""


async def fetch_client_rows(db: AsyncSession, org_id: str, include_demo: bool = False) -> list[Any]:
    """All clients of an org with their derived facts (demo hidden by default)."""
    query = CLIENT_FACTS_SQL + " WHERE c.org_id = :oid"
    if not include_demo:
        query += " AND c.is_demo = false"
    query += " ORDER BY c.created_at DESC"
    result = await db.execute(text(query), {"oid": org_id})
    return list(result.all())


async def fetch_client_row(db: AsyncSession, client_id: str) -> Any | None:
    """A single client with its derived facts (any org — caller checks access)."""
    result = await db.execute(text(CLIENT_FACTS_SQL + " WHERE c.id = :cid"), {"cid": client_id})
    return result.first()
