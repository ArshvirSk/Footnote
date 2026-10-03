"""Engine Adapters and Rate Limiter for AI platforms."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Protocol, Literal

import httpx
from redis.asyncio import Redis
from services.api.app.schemas import EngineType
from services.api.app.logging import get_logger

logger = get_logger(__name__)

class RawAnswer:
    def __init__(self, text: str, citations: list[dict], model_label: str, raw_json: dict, screenshot_path: str | None = None):
        self.text = text
        self.citations = citations
        self.model_label = model_label
        self.raw_json = raw_json
        self.screenshot_path = screenshot_path


class EngineAdapter(Protocol):
    engine: EngineType
    mode: Literal["api", "ui"]

    async def ask(self, prompt: str, *, geo: str, run_index: int) -> RawAnswer: ...


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
            success = await self.redis.eval(script, 1, self.key, self.capacity, self.refill_rate, tokens, now) # type: ignore
            
            if success:
                return
            
            # Wait before retrying (exponential backoff handled by caller or simple sleep here)
            await asyncio.sleep(1.0)


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
            raw_json={"mock": True, "text": text}
        )

# Implementations of actual APIs would go here, utilizing httpx.AsyncClient.
# Since this is a test/local setup, we use MockEngineAdapter by default unless API keys exist.

class OpenAISearchAdapter:
    engine = EngineType.CHATGPT
    mode: Literal["api", "ui"] = "api"

    def __init__(self, api_key: str, redis: Redis):
        self.client = httpx.AsyncClient(headers={"Authorization": f"Bearer {api_key}"})
        self.bucket = RedisTokenBucket(redis, "openai", capacity=50, refill_rate_per_sec=1.0)

    async def ask(self, prompt: str, *, geo: str, run_index: int) -> RawAnswer:
        await self.bucket.acquire()
        # In a real impl, call OpenAI API with search tool enabled.
        # For now, simulate.
        return await MockEngineAdapter(self.engine).ask(prompt, geo=geo, run_index=run_index)


def get_adapter(engine: EngineType, redis: Redis) -> EngineAdapter:
    """Factory to get the right adapter based on env config."""
    # In a full implementation, we'd check os.environ for keys and return real adapters.
    return MockEngineAdapter(engine)
