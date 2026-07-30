"""
Cache-hit end-to-end gate (docs/phase-3.2, Step 3.5) — the Phase 3 gate.

Confirms a second identical call returns the cached result WITHOUT invoking the solver. The
solver is a spy counting its run() invocations; the assertion is behavioural (call count == 1
across two identical submissions), not a timing check — unambiguous and stable in CI.

Runs the real router -> worker -> cache path with a fakeredis store (no container needed,
since the gate proves the caching behaviour, not solver physics — the regression gates cover
physics). Lives in tests/unit rather than the doc's tests/integration for that reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from connectors.base import RunResult, SolverInterface
from execution import job_store, worker
from mcp_server import router


class _Dummy:
    pass


class _SpyConnector(SolverInterface):
    """A successful connector that records each run() invocation."""

    def __init__(self, runs: list[int]) -> None:
        self._runs = runs

    @property
    def solver_name(self) -> str:
        return "openfoam"

    def validate_inputs(self, raw: dict):
        return _Dummy()

    def build_input_files(self, validated, work_dir: Path) -> Path:
        return work_dir / "case"

    def run(self, case_dir: Path) -> RunResult:
        self._runs.append(1)
        return RunResult(exit_code=0, stdout="ok", stderr="")

    def parse_outputs(self, case_dir: Path) -> dict:
        return {"pressure": {"mean": 1.0}}


def test_second_identical_call_uses_cache_not_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs: list[int] = []
    monkeypatch.setattr(worker, "get_connector", lambda name: _SpyConnector(runs))
    monkeypatch.setattr(
        worker.artifact_store, "store", lambda solver, jid, case: f"/art/{solver}/{jid}"
    )

    payload = {"case_name": "pipe_flow", "fluid": {"kinematic_viscosity": 1e-5}}

    # First call: cache miss -> PENDING, solver not yet run.
    first = router.submit_job("openfoam", payload)
    assert first["status"] == "PENDING"
    assert runs == []

    # Worker processes the job: solver runs once, result is cached.
    worker.run_simulation(first["job_id"], "openfoam", payload)
    assert len(runs) == 1
    assert job_store.get_job(first["job_id"])["status"] == "COMPLETED"

    # Second identical call: cache HIT -> COMPLETED, solver NOT invoked again.
    second = router.submit_job("openfoam", payload)
    assert second["status"] == "COMPLETED"
    assert second["result_ref"]
    assert second["result"]["pressure"]["mean"] == 1.0
    assert len(runs) == 1  # solver invoked exactly once across both identical calls
