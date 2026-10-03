"""Edge search routes for real-time RAG ingestion by external LLMs."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.auth import AuthUser, get_current_user
from services.api.app.db import get_db
from services.api.app.logging import get_logger

logger = get_logger(__name__)

# The edge proxy uses internal auth, we skip standard user auth for /edge
# In production, we'd use a dependency that validates the X-Internal-Service header
# or an internal JWT minted by the edge worker.
router = APIRouter(prefix="/clients/{client_id}/edge", tags=["edge"])

async def mock_get_embedding(query: str) -> list[float]:
    """Mock embedding generation (e.g., text-embedding-3-small)."""
    # Returns a mock 1536-dimensional vector for pgvector
    return [0.01] * 1536


@router.get("/search")
async def edge_search(
    client_id: UUID,
    q: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Real-time semantic search endpoint for the Feeds Edge Proxy.
    Returns JSON-LD structured data representing the client's approved content.
    """
    if not q:
        raise HTTPException(status_code=400, detail="Missing query parameter 'q'")

    # 1. Embed the query
    query_vector = await mock_get_embedding(q)
    vector_str = f"[{','.join(map(str, query_vector))}]"
    
    # 2. Similarity search via pgvector (L2 distance `<->`)
    # We restrict to chunks belonging to active publications for this client
    search_query = text("""
        SELECT cc.id, cc.text_content, cc.metadata, 
               p.target_url, d.title,
               1 - (cc.embedding <=> :vec) as cosine_similarity
        FROM content_chunks cc
        JOIN publications p ON p.id = cc.publication_id
        JOIN drafts d ON d.id = p.entity_id
        WHERE cc.client_id = :cid AND p.is_live = true
        ORDER BY cc.embedding <=> :vec
        LIMIT 5
    """)
    
    res = await db.execute(search_query, {"cid": str(client_id), "vec": vector_str})
    rows = res.fetchall()
    
    # 3. Format as JSON-LD for optimal LLM ingestion
    items = []
    for row in rows:
        items.append({
            "@type": "Article",
            "headline": row.title,
            "url": row.target_url,
            "text": row.text_content,
            "about": row.metadata.get("topics", []) if row.metadata else []
        })
        
    logger.info("edge_search_executed", client_id=str(client_id), query=q, matches=len(items))

    # JSON-LD Graph wrapping
    return {
        "@context": "https://schema.org",
        "@graph": items
    }
