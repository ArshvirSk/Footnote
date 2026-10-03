"""Parser service: LLM judge, domain normalization, citation extraction."""

from __future__ import annotations

import re
from urllib.parse import urlparse
from pydantic import BaseModel, Field

from services.api.app.logging import get_logger

logger = get_logger(__name__)

class DomainInfo(BaseModel):
    normalized_domain: str
    is_brand_owned: bool = False
    competitor_id: str | None = None

def normalize_domain(url: str) -> str:
    """Extract and normalize domain from URL. Strips www."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return "unknown"

def extract_citations(text: str, raw_json: dict) -> list[dict]:
    """Extract citations from structured JSON if available, fallback to regex."""
    citations = []
    # If standard tool format is present, extract from it (stub)
    if "sources" in raw_json:
        for idx, src in enumerate(raw_json["sources"]):
            citations.append({"url": src["url"], "title": src.get("title", ""), "position": idx + 1})
        return citations
    
    # Fallback text regex for http(s) urls
    urls = re.findall(r'(https?://\S+)', text)
    for idx, u in enumerate(urls):
        clean_url = u.rstrip(').,"]')
        citations.append({"url": clean_url, "title": "", "position": idx + 1})
    
    return citations

class JudgeResult(BaseModel):
    recommended: bool
    sentiment: str = Field(pattern="^(positive|neutral|negative|mixed)$")
    rank_in_answer: int | None
    excerpt: str

async def evaluate_mention(text: str, brand_name: str, brand_aliases: list[str]) -> JudgeResult | None:
    """LLM Judge to determine if brand was recommended and sentiment."""
    # In a real system, this would call a cheap LLM (e.g. gpt-4o-mini) using instructor/pydantic.
    # We will simulate the logic based on text inclusion.
    text_lower = text.lower()
    
    mentioned = brand_name.lower() in text_lower or any(a.lower() in text_lower for a in brand_aliases)
    if not mentioned:
        return None
        
    return JudgeResult(
        recommended=True,
        sentiment="positive",
        rank_in_answer=1,
        excerpt=f"Mentioned {brand_name} as a recommended tool."
    )
