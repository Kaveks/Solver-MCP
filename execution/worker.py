"""
execution/worker.py — Celery application for the Solver-MCP execution layer (Layer 3).

This is the placeholder Celery app introduced in docs/phase-1.1 Unit B: it gives the
worker container a configured Celery instance that connects to Redis and starts cleanly.
The real job-processing task (pick up a job, run the connector through its SolverInterface
lifecycle, write artifacts, update status) is wired in docs/phase-1.4.

The worker container runs this app via:

    celery -A execution.worker:celery_app worker

Broker and result-backend URLs come from config.get_settings() — never os.environ
directly. CELERY_BROKER_URL / CELERY_RESULT_BACKEND default to REDIS_URL (see the
settings validator), so a minimal .env only needs REDIS_URL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from celery import Celery
from pydantic import ValidationError

from config import get_settings
from connectors.base import BuildError, ParseError
from connectors.registry import get_connector
from execution import artifact_store, cache, job_store
from observability import get_logger, set_correlation_id

logger = get_logger(__name__)


def create_celery_app() -> Celery:
    """Build the Celery application from validated settings."""
    settings = get_settings()

    app = Celery(
        "Solver-MCP",
        broker=settings.CELERY_BROKER_URL.get_secret_value(),
        backend=settings.CELERY_RESULT_BACKEND.get_secret_value(),
    )

    # Conservative defaults suited to long-running simulation jobs:
    # - track STARTED so job status can report RUNNING (used from phase-1.4 onward)
    # - acks_late + prefetch 1 so a crashing worker does not silently drop a job
    app.conf.update(
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )
    return app


# Module-level app object the Celery CLI and task registration use.
celery_app = create_celery_app()


def _fail(job_id: str, stage: str, code: str, message: str) -> None:
    """Record a job as FAILED with a structured error (no stack trace surfaced)."""
    job_store.set_status(
        job_id,
        "FAILED",
        error={"stage": stage, "code": code, "message": message[:500]},
    )


@celery_app.task(name="run_simulation")
def run_simulation(job_id: str, solver_name: str, payload: dict[str, Any]) -> None:
    """Drive a job through the SolverInterface lifecycle and record its outcome.

    Solver-agnostic: every connector follows the same validate -> build -> run -> parse
    contract, and each failure mode maps to a structured {stage, code, message} error.

    A top-level guard ensures a job is never left stuck in RUNNING: any unexpected error
    (a crash mid-job) is recorded as a structured FAILED. No stack trace is surfaced.
    """
    set_correlation_id(job_id)
    try:
        _run_job(job_id, solver_name, payload)
    except Exception as exc:  # last-resort: never leave the job in RUNNING
        logger.exception("worker crashed handling job %s", job_id)
        _fail(job_id, "worker", "WORKER_ERROR", str(exc))


def _run_job(job_id: str, solver_name: str, payload: dict[str, Any]) -> None:
    job_store.set_status(job_id, "RUNNING")

    try:
        connector = get_connector(solver_name)
    except ValueError as exc:
        _fail(job_id, "validation", "UNKNOWN_SOLVER", str(exc))
        return

    work_dir = Path(get_settings().WORK_DIR)

    try:
        validated = connector.validate_inputs(payload)
    except ValidationError as exc:
        _fail(job_id, "validation", "SCHEMA_INVALID", str(exc))
        return

    try:
        case_dir = connector.build_input_files(validated, work_dir)
    except BuildError as exc:
        _fail(job_id, "build", "BUILD_FAILED", str(exc))
        return

    # A runner/Docker error (as opposed to a non-zero solver exit) is a solver-stage failure.
    try:
        result = connector.run(case_dir)
    except Exception as exc:
        _fail(job_id, "solver", "RUNNER_ERROR", str(exc))
        return

    if not result.success:
        classify = getattr(connector, "classify_run_failure", None)
        error = (
            classify(result)
            if callable(classify)
            else {"stage": "solver", "code": "SOLVER_ERROR", "message": result.stderr[:500]}
        )
        logger.warning(
            "fresh run FAILED at solver stage",
            extra={
                "event": "run_failed",
                "solver": solver_name,
                "job_id": job_id,
                "code": error["code"],
            },
        )
        job_store.set_status(job_id, "FAILED", error=error)
        return

    try:
        summary = connector.parse_outputs(case_dir)
    except ParseError as exc:
        _fail(job_id, "parse", "PARSE_FAILED", str(exc))
        return

    result_ref = artifact_store.store(solver_name, job_id, case_dir)
    # Store under the SHA-256 cache key so an identical future call skips the solver.
    key = cache.cache_key(solver_name, payload)
    cache.store(key, result_ref, summary)
    job_store.set_status(job_id, "COMPLETED", result_ref=result_ref, result=summary)
    # One completion line: the fresh solver run finished and its result is now cached.
    logger.info(
        "fresh run COMPLETED — result cached",
        extra={
            "event": "run_completed",
            "solver": solver_name,
            "job_id": job_id,
            "cache_key": key,
        },
    )
