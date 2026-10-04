"""Content chunker and embedder worker.

Chunks published content and stores real embeddings in brand_memory_chunks
(searchable brand memory) keyed by source = 'publication:{publication_id}'.

Uses the shared embeddings provider (OpenAI text-embedding-3-small). When no
provider key is configured the job fails loudly instead of writing placeholder
vectors — brand memory must never contain fake data.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from services.api.app.db import engine
from services.api.app.embeddings import EMBEDDING_MODEL, embed_texts, embedding_cost_usd
from services.api.app.logging import get_logger
from services.api.app.text import chunk_text
from sqlalchemy import text

logger = get_logger(__name__)


async def embed_publication(
    ctx: dict[str, Any], client_id: str, publication_id: str, content_text: str, metadata: dict[str, Any]
) -> dict[str, Any]:
    """Split published text into chunks, embed them, and store them for retrieval.

    Replaces any previous chunks for the same publication (idempotent re-runs).
    """
    logger.info("embed_publication_started", pub_id=publication_id)

    chunks = chunk_text(content_text)
    title = metadata.get("title") if isinstance(metadata, dict) else None
    source = f"publication:{publication_id}"

    vectors, tokens = await embed_texts(chunks)
    cost = embedding_cost_usd(tokens)

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM brand_memory_chunks WHERE client_id = :cid AND source = :src"),
            {"cid": client_id, "src": source},
        )
        for chunk, vector in zip(chunks, vectors, strict=True):
            await conn.execute(
                text(
                    """
                    INSERT INTO brand_memory_chunks (id, client_id, source, title, content, embedding)
                    VALUES (:id, :cid, :src, :title, :content, CAST(:vec AS vector))
                    """
                ),
                {
                    "id": str(uuid4()),
                    "cid": client_id,
                    "src": source,
                    "title": title,
                    "content": chunk,
                    "vec": f"[{','.join(map(str, vector))}]",
                },
            )
        await conn.execute(
            text(
                """
                INSERT INTO agent_runs (id, client_id, agent, input, output, model, tokens_in, tokens_out, cost_usd, status, started_at, finished_at)
                VALUES (:id, :cid, 'publish', CAST(:input AS jsonb), CAST(:output AS jsonb), :model, :tin, 0, :cost, 'succeeded', now(), now())
                """
            ),
            {
                "id": str(uuid4()),
                "cid": client_id,
                "input": json.dumps({"publication_id": publication_id, "chunks": len(chunks)}),
                "output": json.dumps({"chunks": len(chunks)}),
                "model": EMBEDDING_MODEL,
                "tin": tokens,
                "cost": cost,
            },
        )

    logger.info("embed_publication_completed", pub_id=publication_id, chunks_created=len(chunks), tokens=tokens)
    return {"status": "success", "chunks": len(chunks), "tokens": tokens, "cost_usd": cost}
