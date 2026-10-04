"""Milestone 2 parser/judge tests: golden-set gate, fuzzy detection, taxonomy, LLM judge.

The golden-set gate is the contract for any judge change: >= 30 hand-labelled
fixtures with >= 95% agreement (the TRD gate is 90%).
"""

from __future__ import annotations

import json

import httpx
import pytest
from packages.evals.judge_eval import MIN_GOLDEN_CASES, load_golden_set, run_judge_eval
from services.api.app.config import settings
from services.workers.app.parser import (
    JUDGE_RULES_VERSION,
    classify_domain,
    evaluate_mention,
    find_mention,
    judge_mention,
)

# ──── Golden set ────


def test_golden_set_has_enough_hand_labelled_fixtures() -> None:
    golden = load_golden_set()
    assert len(golden) >= MIN_GOLDEN_CASES
    # Every fixture is labelled on both axes (or explicitly expects no mention).
    assert all(c.expected_sentiment in ("positive", "neutral", "negative", "mixed") for c in golden)
    assert sum(1 for c in golden if c.expect_none) >= 5


@pytest.mark.asyncio
async def test_judge_agreement_gates() -> None:
    results = await run_judge_eval()
    assert results.total >= MIN_GOLDEN_CASES
    assert results.mention_agreement >= 0.95
    assert results.recommendation_agreement >= 0.95
    assert results.sentiment_agreement >= 0.95
    assert results.accuracy >= 0.95
    assert results.judge_version == JUDGE_RULES_VERSION


# ──── Fuzzy brand/alias detection ────


@pytest.mark.asyncio
async def test_detects_separator_free_and_case_variants() -> None:
    hit = find_mention("For enterprise IT work, DBAConsultants is frequently cited.", "DBA Consultants")
    assert hit is not None
    assert hit.name == "DBA Consultants"

    result = await evaluate_mention("ACME CORP delivers strong results.", "Acme Corp", ["Acme"])
    assert result is not None
    assert result.sentiment == "positive"

    nimbus = await evaluate_mention("NimbusCloud is reliable and strong.", "Nimbus Cloud", [])
    assert nimbus is not None
    assert nimbus.sentiment == "positive"


@pytest.mark.asyncio
async def test_fuzzy_finds_no_false_positives() -> None:
    assert find_mention("Pricing varies by vendor and contract length.", "Acme Corp", "Acme") is None
    assert await evaluate_mention("CRM software has matured considerably.", "Acme Corp", ["Acme"]) is None
    # Short single-word names are not fuzzy-matched (too risky).
    assert find_mention("The accumulator stores charge.", "Acme") is None


@pytest.mark.asyncio
async def test_competitor_mentions_detected_with_aliases() -> None:
    hit = find_mention("RivalTech is the safer choice right now.", "Rival Technology", "RivalTech")
    assert hit is not None
    assert hit.name == "RivalTech"  # the alias that actually appears in the text
    assert "RivalTech" in hit.excerpt


# ──── Domain taxonomy (FR-12) ────


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("reddit.com", "forum"),
        ("www.reddit.com", "forum"),
        ("quora.com", "forum"),
        ("g2.com", "review_site"),
        ("capterra.com", "review_site"),
        ("en.wikipedia.org", "wiki"),
        ("techcrunch.com", "news"),
        ("economictimes.indiatimes.com", "news"),
        ("example.gov", "gov_edu"),
        ("mit.edu", "gov_edu"),
        ("amazon.in", "marketplace"),
        ("medium.com", "publisher"),
        ("some-random-blog.example", "other"),
        ("", "other"),
    ],
)
def test_classify_domain(domain: str, expected: str) -> None:
    assert classify_domain(domain) == expected


# ──── Versioned LLM judge (stubbed transport, no key needed) ────


def _llm_payload(content: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_llm_judge_parses_json_and_records_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "judge_mode", "llm")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "judge_model", "gpt-5-mini")

    transport = _llm_payload(
        json.dumps(
            {
                "mentioned": True,
                "recommended": False,
                "sentiment": "negative",
                "excerpt": "Acme Corp is overpriced and hard to use.",
            }
        )
    )
    result = await judge_mention(
        "Some overview. Acme Corp is overpriced and hard to use.",
        "Acme Corp",
        ["Acme"],
        transport=transport,
    )
    assert result is not None
    assert result.recommended is False
    assert result.sentiment == "negative"
    assert result.judge_version == f"llm:{settings.judge_model}:v1"


@pytest.mark.asyncio
async def test_llm_judge_not_mentioned_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "judge_mode", "llm")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")

    transport = _llm_payload(json.dumps({"mentioned": False, "recommended": False, "sentiment": "neutral"}))
    assert await judge_mention("Nothing about the brand here.", "Acme Corp", [], transport=transport) is None


@pytest.mark.asyncio
async def test_llm_judge_falls_back_to_rules_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "judge_mode", "llm")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(boom)
    result = await judge_mention(
        "Acme Corp is widely considered excellent.",
        "Acme Corp",
        ["Acme"],
        transport=transport,
    )
    assert result is not None
    # Fallback must be explicit in the recorded version.
    assert result.judge_version == JUDGE_RULES_VERSION
    assert result.sentiment == "positive"


@pytest.mark.asyncio
async def test_default_judge_is_rules_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "judge_mode", "rules")
    result = await judge_mention("Acme Corp is excellent.", "Acme Corp", ["Acme"])
    assert result is not None
    assert result.judge_version == JUDGE_RULES_VERSION
