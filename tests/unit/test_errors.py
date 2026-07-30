"""
Error-handling path tests (docs/phase-3.2, Step 3.3).

Every failure mode returns a structured {stage, code, message} with no stack trace, a job is
never left stuck in RUNNING, and a Redis outage falls through rather than failing the job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from connectors.base import RunResult, SolverInterface
from execution import cache, job_store, worker
from mcp_server import router


class _BrokenRedis:
    """A Redis client that raises on every call — simulates an outage."""

    def get(self, *args, **kwargs):
        raise ConnectionError("redis down")

    def set(self, *args, **kwargs):
        raise ConnectionError("redis down")


class _Dummy:
    pass


class _FakeConnector(SolverInterface):
    def __init__(self, *, run_result=None, run_raises=None) -> None:
        self._run_result = run_result or RunResult(exit_code=0, stdout="ok", stderr="")
        self._run_raises = run_raises

    @property
    def solver_name(self) -> str:
        return "fake"

    def validate_inputs(self, raw: dict):
        return _Dummy()

    def build_input_files(self, validated, work_dir: Path) -> Path:
        return work_dir / "case"

    def run(self, case_dir: Path) -> RunResult:
        if self._run_raises is not None:
            raise self._run_raises
        return self._run_result

    def parse_outputs(self, case_dir: Path) -> dict:
        return {"ok": True}


def _setup(monkeypatch, connector, *, store=lambda solver, jid, case: f"/art/{solver}/{jid}"):
    job_store.create_job("j", "fake", {})
    monkeypatch.setattr(worker, "get_connector", lambda name: connector)
    monkeypatch.setattr(worker.artifact_store, "store", store)


# ── cache-unavailable fall-through ───────────────────────────────────────────

def test_cache_get_unavailable_falls_through() -> None:
    cache.set_client(_BrokenRedis())
    # submit must not raise; a lookup outage is treated as a miss -> PENDING
    result = router.submit_job("openfoam", {"case_name": "x"})
    assert result["status"] == "PENDING"


def test_cache_store_unavailable_still_completes(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.set_client(_BrokenRedis())  # store raises -> swallowed
    _setup(monkeypatch, _FakeConnector())
    worker.run_simulation("j", "fake", {})
    assert job_store.get_job("j")["status"] == "COMPLETED"


# ── solver / runner / crash paths ────────────────────────────────────────────

def test_solver_nonzero_exit_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, _FakeConnector(run_result=RunResult(1, "", "diverged")))
    worker.run_simulation("j", "fake", {})
    error = job_store.get_job("j")["error"]
    assert error["stage"] == "solver"
    assert "Traceback" not in error["message"]


def test_runner_exception_is_solver_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, _FakeConnector(run_raises=RuntimeError("docker unreachable")))
    worker.run_simulation("j", "fake", {})
    error = job_store.get_job("j")["error"]
    assert error["stage"] == "solver"
    assert error["code"] == "RUNNER_ERROR"


def test_worker_crash_never_leaves_running(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(solver, jid, case):
        raise OSError("disk full")

    _setup(monkeypatch, _FakeConnector(), store=_boom)
    worker.run_simulation("j", "fake", {})
    record = job_store.get_job("j")
    assert record["status"] == "FAILED"  # not stuck in RUNNING
    assert record["error"]["stage"] == "worker"
    assert "Traceback" not in record["error"]["message"]
