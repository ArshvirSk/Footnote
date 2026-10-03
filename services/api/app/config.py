"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration is read from environment variables."""

    # Postgres
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/footnote"
    database_url_sync: str = "postgresql://postgres:postgres@db:5432/footnote"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Auth
    supabase_jwt_secret: str = "super-secret-jwt-key-for-local-dev-change-me"
    supabase_service_role_key: str = ""

    # Encryption for CMS creds and OAuth tokens
    encryption_key: str = ""

    # Runtime
    environment: str = "development"
    log_level: str = "debug"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Sentry (optional)
    sentry_dsn: str = ""

    model_config = {"env_file": ".env", "case_sensitive": False}


settings = Settings()
