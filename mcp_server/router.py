"""
mcp_server/router.py — routes solver tool calls to async execution (Layer 2).

Data-driven: the known solvers come from the connector registry, so adding a solver is a
registry entry, not a control-flow change here (the router decision from docs/phase-1.2).

Submission (docs/phase-1.4) now does the real thing: create a PENDING job in the Redis-backed
job store and dispatch a Celery task to the worker. The MCP tools in server.py are unchanged —
the docs/phase-1.2 mock has been swapped out behind the same submit_job/get_job interface.
"""

from __future__ import annotations

import uuid
from typing import Any

from connectors.registry import known_solvers
from execution import cache, job_store
from observability import get_logger

logger = get_logger(__name__)


def _dispatch(job_id: str, solver_name: str, payload: dict[str, Any]) -> None:
    """Enqueue the simulation on the worker. Imported lazily to keep Layer 2 thin and avoid
    importing the Celery app at module load (and to let tests patch this single seam)."""
    from execution.worker import run_simulation

    run_simulation.delay(job_id, solver_name, payload)


def submit_job(
    solver_name: str, payload: dict[str, Any], tool_name: str | None = None
) -> dict[str, Any]:
    """Create a job and return its public view.

    Checks the SHA-256 cache before dispatch — on a hit the job is created already COMPLETED
    from the cached result (no Celery, no solver run); on a miss it is dispatched to the
    worker. The cache check is never skipped.

    Emits exactly one INFO line — the cache decision — so an observer can tell from a single
    record whether the tool call was served from cache or ran the solver fresh, and which
    tool/solver it was. ``tool_name`` is the MCP tool the agent invoked (e.g. run_md_simulation).
    """
    if solver_name not in known_solvers():
        raise ValueError(f"Unknown solver {solver_name!r}; not in the connector registry.")

    job_id = str(uuid.uuid4())
    job_store.create_job(job_id, solver_name, payload)

    key = cache.cache_key(solver_name, payload)
    cached = cache.get(key)
    if cached is not None:
        # Cache hit: served from the SHA-256 cache — no Celery, no solver. submit returns
        # COMPLETED here, collapsing the agent's status-poll loop (each skipped poll is one
        # fewer LLM round-trip); the LLM itself still runs to form the call and interpret it.
        logger.info(
            "cache HIT — served from cache, no solver run",
            extra={
                "event": "cache_hit",
                "tool": tool_name,
                "solver": solver_name,
                "job_id": job_id,
                "cache_key": key,
            },
        )
        job_store.set_status(
            job_id,
            "COMPLETED",
            result_ref=cached["result_ref"],
            result=cached["result"],
        )
        return job_store.get_job(job_id)

    # Cache miss: dispatch to the worker, which invokes the connector/solver fresh.
    logger.info(
        "cache MISS — dispatching fresh run to solver",
        extra={
            "event": "cache_miss",
            "tool": tool_name,
            "solver": solver_name,
            "job_id": job_id,
            "cache_key": key,
        },
    )
    _dispatch(job_id, solver_name, payload)
    return job_store.get_job(job_id)


def get_job(job_id: str) -> dict[str, Any] | None:
    """Return the public view of a job, or None if no such job exists."""
    return job_store.get_job(job_id)
