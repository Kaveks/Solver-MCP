"""
Unit tests for the health routes (docs/phase-1.1 Unit B).

Liveness must always return 200 with no dependency on Redis. Readiness must return 200
when Redis is reachable and 503 when it is not — verified by substituting the internal
Redis check, so no live Redis is required.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import mcp_server.routes.health as health
from mcp_server.app import app

client = TestClient(app)


def test_health_liveness() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok_when_redis_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _reachable() -> bool:
        return True

    monkeypatch.setattr(health, "_check_redis", _reachable)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_503_when_redis_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _unreachable() -> bool:
        raise ConnectionError("redis down")

    monkeypatch.setattr(health, "_check_redis", _unreachable)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not ready"
