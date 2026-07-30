"""
mcp_server/routes/health.py — liveness and readiness probes.

Used by Docker Compose health checks (and Kubernetes probes in Production).

GET /health        Liveness. 200 if the process is up. No dependencies checked.
GET /health/ready  Readiness. 200 only if Redis is reachable; 503 otherwise.

Settings are read inside the handlers (not at import) so importing this module never
requires a populated environment — important for the import regression guard.
"""

from __future__ import annotations

import redis.asyncio as aioredis
from fastapi import APIRouter, Response

from config import get_settings
from mcp_server.schemas.api import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


async def _check_redis() -> bool:
    """Return True if Redis answers a PING, False if the call fails.

    Factored out so it can be substituted in unit tests without a live Redis.
    """
    settings = get_settings()
    client = aioredis.from_url(settings.REDIS_URL.get_secret_value())
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe — the process is running."""
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=ReadyResponse, response_model_exclude_none=True)
async def ready(response: Response) -> ReadyResponse:
    """Readiness probe — 200 only when Redis is reachable."""
    try:
        reachable = await _check_redis()
    except Exception:
        reachable = False

    if reachable:
        return ReadyResponse(status="ready")

    response.status_code = 503
    return ReadyResponse(status="not ready", reason="redis unreachable")
