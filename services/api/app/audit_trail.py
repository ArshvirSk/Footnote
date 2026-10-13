"""Enterprise audit trail helper for logging administrative and system events."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from services.api.app.logging import get_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def record_audit_event(
    db: AsyncSession,
    *,
    org_id: UUID | None = None,
    actor: UUID | None = None,
    action: str,
    entity: str,
    entity_id: UUID | None = None,
    meta: dict[str, Any] | None = None,
) -> int:
    """Insert an entry into audit_log and return its generated ID."""
    stmt = text(
        """
        INSERT INTO audit_log (org_id, actor, action, entity, entity_id, meta, at)
        VALUES (:org_id, :actor, :action, :entity, :entity_id, :meta, now())
        RETURNING id
        """
    )
    result = await db.execute(
        stmt,
        {
            "org_id": str(org_id) if org_id else None,
            "actor": str(actor) if actor else None,
            "action": action,
            "entity": entity,
            "entity_id": str(entity_id) if entity_id else None,
            "meta": json.dumps(meta or {}),
        },
    )
    row = result.first()
    log_id = int(row[0]) if row else 0
    logger.info("audit_event_recorded", id=log_id, action=action, entity=entity, actor=str(actor) if actor else None)
    return log_id
