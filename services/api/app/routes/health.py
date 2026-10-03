"""Health check endpoint — no auth required."""

from fastapi import APIRouter

from services.api.app.config import settings
from services.api.app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Basic liveness probe."""
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        version="0.1.0",
    )
