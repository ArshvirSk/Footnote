"""Engine adapters: real HTTP clients gated by API keys, opt-in mock fallback.

Each adapter calls the provider's public answer/search API and normalizes the
response into a :class:`RawAnswer`. Contracts below were verified against the
providers' official docs on 2026-10-04 (they change often):

- OpenAI        Chat Completions ``gpt-5-search-api`` + ``web_search_options``
                (the ``gpt-4o-search-preview`` models are deprecated);
                citations are ``message.annotations[].url_citation``.
- Gemini        ``generateContent`` + ``tools:[{"google_search": {}}]``;
                citations are ``groundingMetadata.groundingChunks[].web``.
- Perplexity    Agent API ``POST /v1/agent`` with a preset (Sonar Chat
                Completions support ended 2026-09-27); sources are the
                ``search_results`` output item plus message annotations.
- xAI           Responses API ``POST /v1/responses`` + ``web_search`` tool;
                every URL is in the top-level ``citations`` list, with inline
                ``[[N]](url)`` markdown in the text.
- Anthropic     Messages API + ``web_search_20250305`` tool; citations are on
                the text blocks (``web_search_result_location``).

When a provider's API key is not configured, :func:`get_adapter` raises
:class:`EngineNotConfiguredError` unless mock engines are explicitly opted in
via ``ALLOW_MOCK_ENGINES=true``. Mock answers are always marked
``raw_json.mock = true`` with a ``-mock`` model-label suffix.

Rate limiting uses the Redis token bucket when a Redis client is available and
an in-process token bucket otherwise (so the worker can run without Redis).
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Literal, Protocol

import httpx
from redis.asyncio import Redis
from services.api.app.config import settings
from services.api.app.logging import get_logger
from services.api.app.schemas import EngineType

logger = get_logger(__name__)


class RawAnswer:
    def __init__(
        self,
        text: str,
        citations: list[dict[str, Any]],
        model_label: str,
        raw_json: dict[str, Any],
        screenshot_path: str | None = None,
    ) -> None:
        self.text = text
        self.citations = citations
        self.model_label = model_label
        self.raw_json = raw_json
        self.screenshot_path = screenshot_path


class EngineNotConfiguredError(RuntimeError):
    """Raised when an engine cannot be collected: no API key and no mock opt-in.

    The collector records the run as failed with this message, so the UI can
    tell the operator exactly which key to add (or that mock mode is off).
    """

    def __init__(self, engine: str, reason: str) -> None:
        self.engine = engine
        self.reason = reason
        super().__init__(f"engine '{engine}' unavailable: {reason}")


class EngineAdapter(Protocol):
    engine: EngineType
    mode: Literal["api", "ui"]

    async def ask(self, prompt: str, *, geo: str, run_index: int) -> RawAnswer: ...


class TokenBucket(Protocol):
    async def acquire(self, tokens: int = 1) -> None: ...


class RedisTokenBucket:
    """Redis-backed token bucket for rate limiting provider API calls."""

    def __init__(self, redis: Redis, key: str, capacity: int, refill_rate_per_sec: float):
        self.redis = redis
        self.key = f"rate_limit:{key}"
        self.capacity = capacity
        self.refill_rate = refill_rate_per_sec

    async def acquire(self, tokens: int = 1) -> None:
        """Wait until tokens are available and consume them."""
        while True:
            # Atomic Lua script for token bucket
            script = """
            local key = KEYS[1]
            local capacity = tonumber(ARGV[1])
            local refill_rate = tonumber(ARGV[2])
            local requested = tonumber(ARGV[3])
            local now = tonumber(ARGV[4])

            local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
            local tokens = tonumber(bucket[1])
            local last_refill = tonumber(bucket[2])

            if tokens == nil then
                tokens = capacity
                last_refill = now
            end

            local elapsed = math.max(0, now - last_refill)
            local refill = math.floor(elapsed * refill_rate)
            tokens = math.min(capacity, tokens + refill)

            if refill > 0 then
                last_refill = now
            end

            if tokens >= requested then
                redis.call('HMSET', key, 'tokens', tokens - requested, 'last_refill', last_refill)
                redis.call('EXPIRE', key, 86400) -- expire after a day of inactivity
                return 1
            else
                redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
                return 0
            end
            """
            now = time.time()
            success = await self.redis.eval(script, 1, self.key, self.capacity, self.refill_rate, tokens, now)  # type: ignore[misc,arg-type]

            if success:
                return

            # Wait before retrying
            await asyncio.sleep(1.0)


class InMemoryTokenBucket:
    """Process-local token bucket — used when no Redis client is available.

    Functionally equivalent to :class:`RedisTokenBucket` for a single worker
    process; the Lua-atomic guarantee is not needed across processes because
    this fallback only applies to Redis-less (single-process) runs.
    """

    def __init__(self, key: str, capacity: int, refill_rate_per_sec: float):
        self.key = key
        self.capacity = capacity
        self.refill_rate = refill_rate_per_sec
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = max(0.0, now - self._last_refill)
                self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
                self._last_refill = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                need = (tokens - self._tokens) / self.refill_rate
            await asyncio.sleep(max(need, 0.05))


def _make_bucket(engine: EngineType, redis: Redis | None, capacity: int, rate: float) -> TokenBucket:
    if redis is not None:
        return RedisTokenBucket(redis, engine.value, capacity, rate)
    return InMemoryTokenBucket(engine.value, capacity, rate)


class MockEngineAdapter:
    """Fallback adapter for local testing when keys are missing."""

    def __init__(self, engine: EngineType):
        self.engine = engine
        self.mode: Literal["api", "ui"] = "api"

    async def ask(self, prompt: str, *, geo: str, run_index: int) -> RawAnswer:
        await asyncio.sleep(0.5)
        text = f"Simulated response from {self.engine.value} for prompt: {prompt}"
        return RawAnswer(
            text=text,
            citations=[{"url": "https://example.com/mock", "title": "Mock Source", "position": 1}],
            model_label=f"{self.engine.value}-mock",
            raw_json={"mock": True, "text": text},
        )


class _HttpAdapter:
    """Shared HTTP plumbing for provider adapters.

    Subclasses set ``engine``/``mode`` and implement ``_build_request`` and
    ``_parse_response`` — the provider contract that the adapter tests pin.
    """

    engine: EngineType
    mode: Literal["api", "ui"] = "api"

    def __init__(self, api_key: str, bucket: TokenBucket, transport: httpx.AsyncBaseTransport | None = None):
        self.api_key = api_key
        self.bucket = bucket
        self._transport = transport

    async def ask(self, prompt: str, *, geo: str, run_index: int) -> RawAnswer:
        await self.bucket.acquire()
        request = self._build_request(prompt, geo=geo)
        async with httpx.AsyncClient(transport=self._transport, timeout=60.0) as client:
            response = await client.send(request)
            response.raise_for_status()
            return self._parse_response(response.json())

    # Provider contract — overridden per engine
    def _build_request(self, prompt: str, *, geo: str) -> httpx.Request:
        raise NotImplementedError

    def _parse_response(self, data: dict[str, Any]) -> RawAnswer:
        raise NotImplementedError


class OpenAISearchAdapter(_HttpAdapter):
    """ChatGPT via OpenAI's search-enabled Chat Completions model.

    ``gpt-5-search-api`` is the documented Chat Completions web-search model
    (the ``*-search-preview`` models are deprecated). Citations arrive as
    ``annotations`` on the message, nested under ``url_citation``.
    """

    engine = EngineType.CHATGPT

    def _build_request(self, prompt: str, *, geo: str) -> httpx.Request:
        return httpx.Request(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": "gpt-5-search-api",
                "web_search_options": {},
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    def _parse_response(self, data: dict[str, Any]) -> RawAnswer:
        message = data["choices"][0]["message"]
        text = message.get("content") or ""
        citations = []
        position = 0
        for ann in message.get("annotations") or []:
            # Current shape: {"type": "url_citation", "url_citation": {url, title, ...}}
            cit = ann.get("url_citation") if isinstance(ann.get("url_citation"), dict) else ann
            url = cit.get("url")
            if url:
                position += 1
                citations.append({"url": url, "title": cit.get("title") or "", "position": position})
        return RawAnswer(text=text, citations=citations, model_label=str(data.get("model", "gpt-5-search-api")), raw_json=data)


class GeminiSearchAdapter(_HttpAdapter):
    """Gemini via the Google Generative Language API with Google Search grounding."""

    engine = EngineType.GEMINI

    def _build_request(self, prompt: str, *, geo: str) -> httpx.Request:
        return httpx.Request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}],
            },
        )

    def _parse_response(self, data: dict[str, Any]) -> RawAnswer:
        candidate = (data.get("candidates") or [{}])[0]
        text = "".join(part.get("text", "") for part in candidate.get("content", {}).get("parts", []))
        citations = []
        chunks = candidate.get("groundingMetadata", {}).get("groundingChunks", [])
        for idx, chunk in enumerate(chunks, start=1):
            web = chunk.get("web", {})
            if web.get("uri"):
                citations.append({"url": web["uri"], "title": web.get("title", ""), "position": idx})
        return RawAnswer(
            text=text, citations=citations, model_label=str(data.get("modelVersion", "gemini")), raw_json=data
        )


class PerplexityAdapter(_HttpAdapter):
    """Perplexity via the Agent API (Sonar Chat Completions ended 2026-09-27).

    ``POST /v1/agent`` takes ``preset`` + ``input`` and returns a typed
    ``output`` array: a ``search_results`` item carrying the sources and a
    ``message`` item carrying the answer text (with citation annotations).
    The ``fast`` preset is Perplexity's documented successor to Sonar.
    """

    engine = EngineType.PERPLEXITY
    preset = "fast"

    def _build_request(self, prompt: str, *, geo: str) -> httpx.Request:
        return httpx.Request(
            "POST",
            "https://api.perplexity.ai/v1/agent",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"preset": self.preset, "input": prompt},
        )

    def _parse_response(self, data: dict[str, Any]) -> RawAnswer:
        text_parts: list[str] = []
        annotations: list[str] = []
        search_results: list[dict[str, Any]] = []
        for item in data.get("output") or []:
            if item.get("type") == "search_results":
                search_results = item.get("results") or []
            elif item.get("type") == "message":
                for block in item.get("content") or []:
                    if block.get("type") in ("output_text", "text"):
                        text_parts.append(block.get("text") or "")
                    for ann in block.get("annotations") or []:
                        url = ann.get("url")
                        if url and url not in annotations:
                            annotations.append(url)

        citations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for res in search_results:
            url = res.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            citations.append({"url": url, "title": res.get("title") or "", "position": len(citations) + 1})
        for url in annotations:
            if url not in seen:
                seen.add(url)
                citations.append({"url": url, "title": "", "position": len(citations) + 1})

        return RawAnswer(text="".join(text_parts), citations=citations, model_label=str(data.get("model", "sonar")), raw_json=data)


_INLINE_CITATION_RE = re.compile(r"\[\[\d+\]\]\((https?://[^)\s]+)\)")


class GrokAdapter(_HttpAdapter):
    """Grok via the xAI Responses API with the web search tool.

    The Responses API returns every source in the top-level ``citations``
    list (always present) plus inline ``[[N]](url)`` markdown in the text.
    """

    engine = EngineType.GROK

    def _build_request(self, prompt: str, *, geo: str) -> httpx.Request:
        return httpx.Request(
            "POST",
            "https://api.x.ai/v1/responses",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": "grok-4.7",
                "input": [{"role": "user", "content": prompt}],
                "tools": [{"type": "web_search"}],
            },
        )

    def _parse_response(self, data: dict[str, Any]) -> RawAnswer:
        text_parts: list[str] = []
        annotations: list[str] = []
        for item in data.get("output") or []:
            if item.get("type") != "message":
                continue
            for block in item.get("content") or []:
                if block.get("type") == "output_text":
                    text_parts.append(block.get("text") or "")
                for ann in block.get("annotations") or []:
                    url = ann.get("url")
                    if url and url not in annotations:
                        annotations.append(url)
        text = "".join(text_parts)

        urls = [u for u in (data.get("citations") or []) if isinstance(u, str)] or annotations
        if not urls:
            urls = list(dict.fromkeys(_INLINE_CITATION_RE.findall(text)))
        citations = [{"url": url, "title": "", "position": idx} for idx, url in enumerate(urls, start=1)]
        return RawAnswer(text=text, citations=citations, model_label=str(data.get("model", "grok-4.7")), raw_json=data)


class AnthropicSearchAdapter(_HttpAdapter):
    """Claude via the Anthropic Messages API with the web search tool."""

    engine = EngineType.CLAUDE

    def _build_request(self, prompt: str, *, geo: str) -> httpx.Request:
        return httpx.Request(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-sonnet-5-5",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
                "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            },
        )

    def _parse_response(self, data: dict[str, Any]) -> RawAnswer:
        text_parts: list[str] = []
        citations: list[dict[str, Any]] = []
        pos = 0
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
                for cite in block.get("citations") or []:
                    if cite.get("url"):
                        pos += 1
                        citations.append({"url": cite["url"], "title": cite.get("title", ""), "position": pos})
            elif block.get("type") == "web_search_tool_result":
                for content in block.get("content") or []:
                    if content.get("url"):
                        pos += 1
                        citations.append({"url": content["url"], "title": content.get("title", ""), "position": pos})
        return RawAnswer(
            text="".join(text_parts), citations=citations, model_label=str(data.get("model", "claude")), raw_json=data
        )


# Engine -> (settings key, adapter class, bucket capacity, refill/sec)
_API_KEYS: dict[EngineType, tuple[str, type[_HttpAdapter], int, float]] = {
    EngineType.CHATGPT: ("openai_api_key", OpenAISearchAdapter, 50, 1.0),
    EngineType.GEMINI: ("gemini_api_key", GeminiSearchAdapter, 30, 0.5),
    EngineType.PERPLEXITY: ("perplexity_api_key", PerplexityAdapter, 30, 0.5),
    EngineType.GROK: ("xai_api_key", GrokAdapter, 30, 0.5),
    EngineType.CLAUDE: ("anthropic_api_key", AnthropicSearchAdapter, 30, 0.5),
    # google_aio has no public query API yet (UI collection lands in Phase 2).
}


def get_adapter(engine: EngineType, redis: object | None = None) -> EngineAdapter:
    """Factory: real adapter when the provider's API key is configured.

    Without a key the behaviour is explicit, never silent:
    - ``ALLOW_MOCK_ENGINES=true`` → :class:`MockEngineAdapter` (marked as mock),
    - otherwise → :class:`EngineNotConfiguredError` telling the operator which
      key to add.

    ``redis`` may be an arq/redis client, an in-process queue stand-in, or None;
    only a real Redis client is used for the shared token bucket.
    """
    bucket_redis = redis if isinstance(redis, Redis) else None
    entry = _API_KEYS.get(engine)

    key_name: str | None = None
    api_key = ""
    if entry is not None:
        key_name, adapter_cls, capacity, rate = entry
        api_key = getattr(settings, key_name, "")
        if api_key:
            logger.info("engine_adapter_live", engine=engine.value, key=key_name)
            return adapter_cls(api_key, _make_bucket(engine, bucket_redis, capacity, rate))

    if settings.allow_mock_engines:
        reason = "no_api" if entry is None else "missing_api_key"
        logger.info("engine_adapter_mock", engine=engine.value, reason=reason, key=key_name)
        return MockEngineAdapter(engine)

    if key_name is None:
        detail = "no public query API yet (UI collection is planned)"
    else:
        detail = f"set {key_name.upper()} (or ALLOW_MOCK_ENGINES=true for local runs)"
    logger.warning("engine_adapter_unconfigured", engine=engine.value, detail=detail)
    raise EngineNotConfiguredError(engine.value, detail)
