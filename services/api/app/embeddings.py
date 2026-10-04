"""Embedding provider for brand memory (pgvector).

Uses OpenAI's ``text-embedding-3-small`` (1536 dimensions, matching
``brand_memory_chunks.embedding vector(1536)``). The provider key comes from the
environment; when it is missing every caller gets an explicit configuration
error — we never write placeholder vectors into brand memory.
"""

from __future__ import annotations

from typing import Any

import httpx
from services.api.app.config import settings
from services.api.app.logging import get_logger

logger = get_logger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
# USD per 1M input tokens (text-embedding-3-small), used for cost logging.
EMBEDDING_PRICE_PER_MTOKEN = 0.02


class EmbeddingNotConfigured(RuntimeError):
    """Raised when no embedding provider key is configured."""


def embedding_cost_usd(tokens: int) -> float:
    """Cost of an embedding call in USD (rounded to micro-dollars)."""
    return round(tokens * EMBEDDING_PRICE_PER_MTOKEN / 1_000_000, 6)


async def embed_texts(
    texts: list[str], transport: httpx.AsyncBaseTransport | None = None
) -> tuple[list[list[float]], int]:
    """Embed texts with OpenAI. Returns ``(vectors, prompt_tokens)``.

    ``transport`` lets tests inject an ``httpx.MockTransport`` instead of
    hitting the network.
    """
    if not texts:
        return [], 0
    if not settings.openai_api_key:
        raise EmbeddingNotConfigured(
            "Embeddings provider not configured: set OPENAI_API_KEY to enable brand-memory ingestion"
        )

    payload: dict[str, Any] = {"model": EMBEDDING_MODEL, "input": texts}
    async with httpx.AsyncClient(transport=transport, timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    vectors = [item["embedding"] for item in data["data"]]
    for vector in vectors:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError(f"Embedding provider returned {len(vector)} dimensions, expected {EMBEDDING_DIMENSIONS}")
    tokens = int((data.get("usage") or {}).get("prompt_tokens", 0))
    return vectors, tokens
