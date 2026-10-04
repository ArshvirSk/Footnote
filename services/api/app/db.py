"""Database connection and session management."""

from collections.abc import AsyncGenerator

from services.api.app.config import settings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# TLS: asyncpg rejects `sslmode=` as a connect kwarg (Neon URLs carry it),
# so Neon connections get SSL via connect_args instead.
_connect_args: dict[str, object] = {"ssl": True} if "neon.tech" in settings.database_url else {}

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    connect_args=_connect_args,
    echo=settings.environment == "development",
    pool_size=10,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session, setting the JWT claim for RLS."""
    async with async_session_factory() as session:
        yield session
