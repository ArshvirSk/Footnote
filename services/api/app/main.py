"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.api.app.config import settings
from services.api.app.logging import get_logger, setup_logging
from services.api.app.routes import (
    audits,
    auth,
    billing,
    brand,
    clients,
    collection,
    content,
    edge,
    entities,
    gaps,
    health,
    integrations,
    prompts,
    research,
    tracking,
    websites,
)

logger = get_logger(__name__)


def setup_observability() -> None:
    """Configure Sentry and OpenTelemetry tracing (stub)."""
    if settings.environment == "production":
        # sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)
        # FastAPInstrumentor.instrument_app(app)
        logger.info("observability_initialized")

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: setup and teardown."""
    setup_logging(settings.log_level)
    setup_observability()
    logger.info("api_starting", environment=settings.environment)
    yield
    logger.info("api_shutting_down")


app = FastAPI(
    title="Footnote API",
    description="Managed SEO + AEO/GEO platform API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(clients.router, prefix="/api/v1")
app.include_router(prompts.router, prefix="/api/v1")
app.include_router(collection.router, prefix="/api/v1")
app.include_router(research.router, prefix="/api/v1")
app.include_router(tracking.router, prefix="/api/v1")
app.include_router(integrations.router, prefix="/api/v1")
app.include_router(content.router, prefix="/api/v1")
app.include_router(edge.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(gaps.router, prefix="/api/v1")
app.include_router(audits.router, prefix="/api/v1")
app.include_router(websites.router, prefix="/api/v1")
app.include_router(brand.router, prefix="/api/v1")
app.include_router(entities.router, prefix="/api/v1")
