"""Contract tests for engine adapters.

Each real adapter must (a) build a provider-conformant request (URL, auth
header, prompt in body) and (b) parse the provider response into a RawAnswer
with text, ordered citations, and a model label. The request/response shapes
are pinned to the providers' official docs (verified 2026-10-04), so a silent
drift in our contract fails here. Transport is mocked with httpx.MockTransport — no network, no keys.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from services.api.app.schemas import EngineType
from services.workers.app.adapters import (
    AnthropicSearchAdapter,
    EngineNotConfiguredError,
    GeminiSearchAdapter,
    GrokAdapter,
    InMemoryTokenBucket,
    MockEngineAdapter,
    OpenAISearchAdapter,
    PerplexityAdapter,
    RawAnswer,
    _HttpAdapter,
    get_adapter,
)

PROMPT = "best crm for small business"


def _transport(capture: dict[str, Any], response_json: dict[str, Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        capture["method"] = request.method
        capture["url"] = str(request.url)
        capture["headers"] = dict(request.headers)
        capture["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=response_json)

    return httpx.MockTransport(handler)


async def _ask(adapter: _HttpAdapter, capture: dict[str, Any], response_json: dict[str, Any]) -> RawAnswer:
    adapter._transport = _transport(capture, response_json)
    return await adapter.ask(PROMPT, geo="IN", run_index=1)


@pytest.mark.asyncio
async def test_openai_adapter_contract() -> None:
    """Chat Completions with gpt-5-search-api + web_search_options (docs-verified)."""
    capture: dict[str, Any] = {}
    payload = {
        "model": "gpt-5-search-api",
        "choices": [
            {
                "message": {
                    "content": "Top CRMs include Acme and Rival.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url_citation": {"url": "https://acmecorp.com", "title": "Acme", "start_index": 10, "end_index": 16},
                        },
                        {
                            "type": "url_citation",
                            "url_citation": {"url": "https://rivaltech.io", "title": "Rival", "start_index": 30, "end_index": 36},
                        },
                    ],
                }
            }
        ],
    }
    adapter = OpenAISearchAdapter("sk-test", InMemoryTokenBucket("t", 10, 100))
    answer = await _ask(adapter, capture, payload)

    assert capture["method"] == "POST"
    assert capture["url"] == "https://api.openai.com/v1/chat/completions"
    assert capture["headers"]["authorization"] == "Bearer sk-test"
    assert capture["body"]["model"] == "gpt-5-search-api"
    assert capture["body"]["web_search_options"] == {}
    assert capture["body"]["messages"][0]["content"] == PROMPT
    assert "metadata" not in capture["body"]
    assert answer.text == "Top CRMs include Acme and Rival."
    assert [c["url"] for c in answer.citations] == ["https://acmecorp.com", "https://rivaltech.io"]
    assert answer.citations[0]["title"] == "Acme"
    assert [c["position"] for c in answer.citations] == [1, 2]
    assert answer.model_label == "gpt-5-search-api"
    assert answer.raw_json["model"] == "gpt-5-search-api"


@pytest.mark.asyncio
async def test_gemini_adapter_contract() -> None:
    capture: dict[str, Any] = {}
    payload = {
        "modelVersion": "gemini-2.5-flash",
        "candidates": [
            {
                "content": {"parts": [{"text": "Acme is a top pick."}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": "https://acmecorp.com/features", "title": "Acme Features"}},
                        {"web": {"uri": "https://g2.com/acme", "title": "G2"}},
                    ]
                },
            }
        ],
    }
    adapter = GeminiSearchAdapter("g-key", InMemoryTokenBucket("t", 10, 100))
    answer = await _ask(adapter, capture, payload)

    assert capture["url"].startswith("https://generativelanguage.googleapis.com/v1beta/models/")
    assert ":generateContent" in capture["url"]
    assert capture["headers"]["x-goog-api-key"] == "g-key"
    assert capture["body"]["tools"] == [{"google_search": {}}]
    assert capture["body"]["contents"][0]["parts"][0]["text"] == PROMPT
    assert "metadata" not in capture["body"]
    assert answer.text == "Acme is a top pick."
    assert [c["url"] for c in answer.citations] == ["https://acmecorp.com/features", "https://g2.com/acme"]
    assert answer.model_label == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_perplexity_adapter_contract() -> None:
    """Agent API (POST /v1/agent) — Sonar Chat Completions ended 2026-09-27."""
    capture: dict[str, Any] = {}
    payload = {
        "id": "resp_123",
        "model": "sonar",
        "status": "completed",
        "output": [
            {
                "type": "search_results",
                "results": [
                    {"url": "https://techcrunch.com/x", "title": "TechCrunch", "date": "2026-09-01"},
                    {"url": "https://g2.com/y", "title": "G2", "date": "2026-09-02"},
                ],
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Answer with sources.",
                        "annotations": [{"type": "citation", "url": "https://techcrunch.com/x"}],
                    }
                ],
            },
        ],
    }
    adapter = PerplexityAdapter("pplx-key", InMemoryTokenBucket("t", 10, 100))
    answer = await _ask(adapter, capture, payload)

    assert capture["url"] == "https://api.perplexity.ai/v1/agent"
    assert capture["headers"]["authorization"] == "Bearer pplx-key"
    assert capture["body"] == {"preset": "fast", "input": PROMPT}
    assert answer.text == "Answer with sources."
    # search_results win (they carry titles); the duplicate annotation is dropped.
    assert [c["url"] for c in answer.citations] == ["https://techcrunch.com/x", "https://g2.com/y"]
    assert answer.citations[0]["title"] == "TechCrunch"
    assert answer.model_label == "sonar"


@pytest.mark.asyncio
async def test_perplexity_annotation_only_sources() -> None:
    """When no search_results item is present, annotation URLs are the citations."""
    capture: dict[str, Any] = {}
    payload = {
        "model": "sonar",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "x",
                        "annotations": [{"type": "citation", "url": "https://only-annotation.com"}],
                    }
                ],
            }
        ],
    }
    adapter = PerplexityAdapter("pplx-key", InMemoryTokenBucket("t", 10, 100))
    answer = await _ask(adapter, capture, payload)
    assert [c["url"] for c in answer.citations] == ["https://only-annotation.com"]


@pytest.mark.asyncio
async def test_grok_adapter_contract() -> None:
    """Responses API (POST /v1/responses) + web_search tool with top-level citations."""
    capture: dict[str, Any] = {}
    payload = {
        "model": "grok-4.7",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Grok answer.[[1]](https://acmecorp.com/blog)",
                    }
                ],
            }
        ],
        "citations": ["https://acmecorp.com/blog"],
    }
    adapter = GrokAdapter("xai-key", InMemoryTokenBucket("t", 10, 100))
    answer = await _ask(adapter, capture, payload)

    assert capture["url"] == "https://api.x.ai/v1/responses"
    assert capture["headers"]["authorization"] == "Bearer xai-key"
    assert capture["body"]["model"] == "grok-4.7"
    assert capture["body"]["tools"] == [{"type": "web_search"}]
    assert capture["body"]["input"][0]["content"] == PROMPT
    assert answer.text == "Grok answer.[[1]](https://acmecorp.com/blog)"
    assert [c["url"] for c in answer.citations] == ["https://acmecorp.com/blog"]
    assert answer.model_label == "grok-4.7"


@pytest.mark.asyncio
async def test_grok_inline_markdown_citation_fallback() -> None:
    """Without a citations list, inline [[N]](url) markdown is parsed."""
    capture: dict[str, Any] = {}
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "See [[1]](https://a.com/x) and [[2]](https://b.com/y)."}
                ],
            }
        ],
    }
    adapter = GrokAdapter("xai-key", InMemoryTokenBucket("t", 10, 100))
    answer = await _ask(adapter, capture, payload)
    assert [c["url"] for c in answer.citations] == ["https://a.com/x", "https://b.com/y"]


@pytest.mark.asyncio
async def test_anthropic_adapter_contract() -> None:
    capture: dict[str, Any] = {}
    payload = {
        "model": "claude-sonnet-5-5",
        "content": [
            {"type": "text", "text": "Claude says Acme leads. ", "citations": [{"type": "web_search_result_location", "url": "https://acmecorp.com", "title": "Acme"}]},
            {"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": "https://rivaltech.io/compare", "title": "Compare"}]},
        ],
    }
    adapter = AnthropicSearchAdapter("ant-key", InMemoryTokenBucket("t", 10, 100))
    answer = await _ask(adapter, capture, payload)

    assert capture["url"] == "https://api.anthropic.com/v1/messages"
    assert capture["headers"]["x-api-key"] == "ant-key"
    assert capture["headers"]["anthropic-version"] == "2023-06-01"
    assert capture["body"]["model"] == "claude-sonnet-5-5"
    assert capture["body"]["tools"][0]["type"] == "web_search_20250305"
    assert answer.text == "Claude says Acme leads. "
    assert [c["url"] for c in answer.citations] == ["https://acmecorp.com", "https://rivaltech.io/compare"]
    assert answer.model_label == "claude-sonnet-5-5"


@pytest.mark.asyncio
async def test_adapter_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    adapter = PerplexityAdapter("pplx-key", InMemoryTokenBucket("t", 10, 100))
    adapter._transport = httpx.MockTransport(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.ask(PROMPT, geo="IN", run_index=1)


# ───────────── Mock gating (explicit opt-in only) ─────────────


def test_get_adapter_without_key_and_no_opt_in_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.api.app.config.settings.openai_api_key", "")
    monkeypatch.setattr("services.api.app.config.settings.allow_mock_engines", False)
    with pytest.raises(EngineNotConfiguredError) as exc:
        get_adapter(EngineType.CHATGPT)
    assert "OPENAI_API_KEY" in str(exc.value)


def test_get_adapter_mock_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.api.app.config.settings.openai_api_key", "")
    monkeypatch.setattr("services.api.app.config.settings.allow_mock_engines", True)
    mock = get_adapter(EngineType.CHATGPT)
    assert isinstance(mock, MockEngineAdapter)


def test_get_adapter_returns_real_adapter_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.api.app.config.settings.perplexity_api_key", "pplx-test")
    monkeypatch.setattr("services.api.app.config.settings.allow_mock_engines", True)
    adapter = get_adapter(EngineType.PERPLEXITY)
    assert isinstance(adapter, PerplexityAdapter)
    assert adapter.mode == "api"


def test_get_adapter_google_aio_needs_opt_in() -> None:
    # No public query API for Google AI Mode yet — mock only when opted in.
    from services.api.app.config import settings

    original = settings.allow_mock_engines
    try:
        settings.allow_mock_engines = False
        with pytest.raises(EngineNotConfiguredError):
            get_adapter(EngineType.GOOGLE_AIO)
        settings.allow_mock_engines = True
        assert isinstance(get_adapter(EngineType.GOOGLE_AIO), MockEngineAdapter)
    finally:
        settings.allow_mock_engines = original


def test_mock_answer_is_marked() -> None:
    import asyncio

    mock = MockEngineAdapter(EngineType.GEMINI)
    answer = asyncio.run(mock.ask("q", geo="IN", run_index=1))
    assert answer.raw_json["mock"] is True
    assert answer.model_label.endswith("-mock")


@pytest.mark.asyncio
async def test_in_memory_bucket_enforces_rate() -> None:
    import time

    bucket = InMemoryTokenBucket("rate-test", capacity=2, refill_rate_per_sec=50)
    start = time.monotonic()
    await bucket.acquire()
    await bucket.acquire()
    await bucket.acquire()  # must wait for refill (~20ms at 50/s)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.01
