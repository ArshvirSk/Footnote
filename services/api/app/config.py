"""Application settings loaded from environment variables."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration is read from environment variables."""

    # Postgres (local default; override with DATABASE_URL, e.g. Neon pulls it into .env)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/footnote"
    # Neon's direct (unpooled) endpoint, if present — preferred for migrations/tests
    database_url_unpooled: str = ""
    # Sync driver URL for psycopg2 tools (pytest, seed, migrate). Empty = derive (unpooled first).
    database_url_sync: str = ""
    # Neon branch name written by `neon link` / `neon deploy`
    neon_branch: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    supabase_jwt_secret: str = "super-secret-jwt-key-for-local-dev-change-me"
    supabase_service_role_key: str = ""

    # Encryption for CMS creds and OAuth tokens
    encryption_key: str = ""

    # Service-to-service auth for the Feeds edge worker (X-Internal-Service header)
    edge_service_token: str = ""

    # Engine provider API keys — when a key is set, the worker collects real
    # answers from that engine. When a key is missing the collector fails the
    # run with an explicit error UNLESS mock engines are opted in below.
    openai_api_key: str = ""
    gemini_api_key: str = ""
    perplexity_api_key: str = ""
    xai_api_key: str = ""
    anthropic_api_key: str = ""

    # Milestone 2: mock engines are an explicit opt-in (never a silent fallback).
    # Mock answers are marked raw_json.mock=true and model_label gets a -mock suffix.
    allow_mock_engines: bool = False

    # Collection scheduling: jitter applied to the nightly fan-out (seconds),
    # and the default per-website daily API-call cap (clients.settings
    # billing_limits.max_daily_calls can lower/raise it per website).
    collection_jitter_seconds: int = 120
    default_daily_call_cap: int = 2000

    # Mention judge: "rules" (deterministic, no key needed) or "llm" (OpenAI).
    judge_mode: str = "rules"
    judge_model: str = "gpt-5-mini"

    # Stripe webhook signature verification (HMAC secret); empty = webhook disabled
    stripe_webhook_secret: str = ""

    # Runtime
    environment: str = "development"
    log_level: str = "debug"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Sentry (optional)
    sentry_dsn: str = ""

    model_config = {"env_file": ".env", "case_sensitive": False}

    @model_validator(mode="after")
    def _normalize_db_urls(self) -> "Settings":
        """Accept the plain ``postgresql://`` URLs Neon writes into .env.

        - async engine (SQLAlchemy) needs the ``postgresql+asyncpg://`` driver prefix
        - psycopg2 tools (tests/seed/migrate) use Neon's unpooled endpoint when present
        - Neon hosts get sslmode=require when the URL doesn't specify it
        """
        def _ensure_ssl(url: str) -> str:
            if "neon.tech" in url and "sslmode=" not in url:
                sep = "&" if "?" in url else "?"
                return f"{url}{sep}sslmode=require"
            return url

        def _strip_libpq_only(url: str, *drop: str) -> str:
            """Drop params asyncpg can't accept as connect kwargs.

            Neon writes channel_binding=require (libpq-only); sslmode is also
            rejected by asyncpg.connect (TLS is passed via connect_args instead).
            """
            drop_set = {"channel_binding", *drop}
            if not any(key in url for key in drop_set):
                return url
            parts = urlsplit(url)
            pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in drop_set]
            return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))

        if self.database_url.startswith("postgresql://"):
            self.database_url = "postgresql+asyncpg://" + self.database_url.removeprefix("postgresql://")
        # TLS for the async engine is supplied by db.py via connect_args={"ssl": True}.
        self.database_url = _strip_libpq_only(self.database_url, "sslmode")

        if self.database_url_unpooled.startswith("postgresql+asyncpg://"):
            self.database_url_unpooled = self.database_url_unpooled.replace(
                "postgresql+asyncpg://", "postgresql://", 1
            )
        self.database_url_unpooled = _ensure_ssl(self.database_url_unpooled)

        if not self.database_url_sync:
            self.database_url_sync = self.database_url_unpooled or self.database_url
        if self.database_url_sync.startswith("postgresql+asyncpg://"):
            self.database_url_sync = self.database_url_sync.replace(
                "postgresql+asyncpg://", "postgresql://", 1
            )
        self.database_url_sync = _strip_libpq_only(_ensure_ssl(self.database_url_sync))
        return self


settings = Settings()
