"""
execution/job_store.py — Redis-backed job records (Layer 3).

Holds the lifecycle state of each simulation job (PENDING → RUNNING → COMPLETED | FAILED).
Written by the router on submission and by the worker as the job progresses; read by the
HTTP /jobs route and the get_job_status MCP tool. Replaces the in-memory store used in the
docs/phase-1.2 mock.

Records are stored as JSON strings under `job:<id>`. The public view (returned to callers)
follows the CLAUDE.md /jobs shape: job_id + status, result_ref/result when COMPLETED, error
when FAILED.

The Redis client is module-level and lazy, so importing this module never connects. Tests
substitute a fakeredis client via set_client().
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from config import get_settings

_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        import redis

        _client = redis.Redis.from_url(
            get_settings().REDIS_URL.get_secret_value(), decode_responses=True
        )
    return _client


def set_client(client: Any) -> None:
    """Override the Redis client (used by tests to inject fakeredis)."""
    global _client
    _client = client


def _key(job_id: str) -> str:
    return f"job:{job_id}"


def _public_view(record: dict[str, Any]) -> dict[str, Any]:
    view: dict[str, Any] = {"job_id": record["job_id"], "status": record["status"]}
    if record["status"] == "COMPLETED":
        if record.get("result_ref") is not None:
            view["result_ref"] = record["result_ref"]
        if record.get("result") is not None:
            view["result"] = record["result"]
    if record["status"] == "FAILED" and record.get("error") is not None:
        view["error"] = record["error"]
    return view


def create_job(
    job_id: str, solver: str, payload: dict[str, Any], owner: str | None = None
) -> None:
    """Store a new job in PENDING state.

    ``owner`` is an opaque per-device identifier used to scope history to one user. The
    agent path creates jobs deep inside the MCP tool (no owner available there), so it is
    typically attached afterwards via set_owner(); None means unattributed.
    """
    record = {
        "job_id": job_id,
        "solver": solver,
        "status": "PENDING",
        "payload": payload,
        "owner": owner,
        "result_ref": None,
        "result": None,
        "error": None,
        "interpretation": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _get_client().set(_key(job_id), json.dumps(record))


def set_status(
    job_id: str,
    status: str,
    *,
    result_ref: str | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    """Update a job's status (and optionally its result/result_ref/error)."""
    client = _get_client()
    raw = client.get(_key(job_id))
    if raw is None:
        return
    record = json.loads(raw)
    record["status"] = status
    if result_ref is not None:
        record["result_ref"] = result_ref
    if result is not None:
        record["result"] = result
    if error is not None:
        record["error"] = error
    client.set(_key(job_id), json.dumps(record))


def get_job(job_id: str) -> dict[str, Any] | None:
    """Return the public view of a job, or None if no such job exists."""
    raw = _get_client().get(_key(job_id))
    if raw is None:
        return None
    return _public_view(json.loads(raw))


# ── History (backend is the single source of truth, scoped per device) ─────────

def _update(job_id: str, **fields: Any) -> None:
    """Read-modify-write a subset of a job record's fields. No-op if the job is gone."""
    client = _get_client()
    raw = client.get(_key(job_id))
    if raw is None:
        return
    record = json.loads(raw)
    record.update(fields)
    client.set(_key(job_id), json.dumps(record))


def set_interpretation(job_id: str, interpretation: str) -> None:
    """Attach the agent's final prose to a job so history renders fully from the backend."""
    _update(job_id, interpretation=interpretation)


def set_owner(job_id: str, owner: str) -> None:
    """Tag a job with the device that created it, scoping it to that user's history."""
    _update(job_id, owner=owner)


def _list_view(record: dict[str, Any]) -> dict[str, Any]:
    """History-card view: the public fields plus solver, case_name, interpretation, time."""
    return {
        "job_id": record["job_id"],
        "status": record["status"],
        "solver": record.get("solver"),
        "case_name": (record.get("payload") or {}).get("case_name"),
        "result_ref": record.get("result_ref"),
        "result": record.get("result"),
        "error": record.get("error"),
        "interpretation": record.get("interpretation"),
        "created_at": record.get("created_at"),
    }


def list_jobs(owner: str | None = None) -> list[dict[str, Any]]:
    """Return jobs (newest first) as list views. When ``owner`` is given, only that
    device's jobs are returned — history is scoped per user. Without an owner, all jobs
    are returned (debug/admin)."""
    client = _get_client()
    jobs: list[dict[str, Any]] = []
    for key in client.scan_iter("job:*"):
        raw = client.get(key)
        if not raw:
            continue
        record = json.loads(raw)
        if owner and record.get("owner") != owner:
            continue
        jobs.append(_list_view(record))
    jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return jobs
