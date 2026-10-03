"""Content chunker and embedder worker."""

import asyncio
import json
from typing import Any

from sqlalchemy import text

from services.api.app.logging import get_logger
from services.api.app.db import engine

logger = get_logger(__name__)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Simple word-based chunker. (Phase 6 implementation)"""
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks


async def mock_get_embedding(text: str) -> list[float]:
    """Mock embedding call to an LLM provider."""
    # Simulates network delay for hitting an embeddings API
    await asyncio.sleep(0.1)
    return [0.02] * 1536


async def embed_publication(ctx: dict[str, Any], client_id: str, publication_id: str, content_text: str, metadata: dict) -> dict[str, str]:
    """
    Splits the published text into chunks, generates embeddings for each, 
    and saves them to pgvector for Edge RAG retrieval.
    """
    logger.info("embed_publication_started", pub_id=publication_id)
    
    chunks = chunk_text(content_text)
    
    async with engine.begin() as conn:
        for idx, chunk in enumerate(chunks):
            vector = await mock_get_embedding(chunk)
            vector_str = f"[{','.join(map(str, vector))}]"
            
            # Upsert chunks 
            # In pgvector, we insert the vector representation directly
            await conn.execute(
                text("""
                    INSERT INTO content_chunks (client_id, publication_id, chunk_index, text_content, embedding, metadata)
                    VALUES (:cid, :pid, :idx, :txt, :vec, :meta)
                    ON CONFLICT (publication_id, chunk_index) DO UPDATE SET
                        text_content = EXCLUDED.text_content,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata
                """),
                {
                    "cid": client_id,
                    "pid": publication_id,
                    "idx": idx,
                    "txt": chunk,
                    "vec": vector_str,
                    "meta": json.dumps(metadata)
                }
            )
            
    logger.info("embed_publication_completed", pub_id=publication_id, chunks_created=len(chunks))
    return {"status": "success", "chunks": len(chunks)}
