"""LangGraph generation agents placeholder."""

import asyncio
from typing import Any


async def mock_brief_generator(prompt_id: str, client_id: str) -> dict[str, Any]:
    """
    Mock agent that generates a brief.
    In Phase 3/4, this will be a LangGraph StateGraph that reads brand profiles,
    SERP data, and constructs an SEO brief.
    """
    print(f"[Agent] Generating brief for prompt {prompt_id}...")
    await asyncio.sleep(2)
    print("[Agent] Brief generated. Moving to internal_ops approval gate.")
    return {"status": "pending_approval", "gate": "internal_ops"}

async def mock_draft_generator(brief_id: str) -> dict[str, Any]:
    """
    Mock agent that generates the actual markdown content.
    """
    print(f"[Agent] Generating draft from brief {brief_id}...")
    await asyncio.sleep(3)
    print("[Agent] Draft generated. Moving to client_review approval gate.")
    return {"status": "pending_approval", "gate": "client_review"}
