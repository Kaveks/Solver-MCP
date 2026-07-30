"""
Unit tests for the Celery worker task (docs/phase-1.4, Step 1.7).

Drives run_simulation with a fake connector (no real solver) and a fakeredis-backed job
store, asserting the status transitions and that each failure mode is recorded as a
structured {stage, code, message} error. artifact_store.store is stubbed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from connectors.base import BuildError, ParseError, RunResult, SolverInterface
from execution import job_store, worker
from mcp_server.schemas import OpenFOAMInput


class _Dummy:
    pass


class _FakeConnector(SolverInterface):
    def __init__(
        self,
        *,
        run_result: RunResult | None = None,
        validate_fail: bool = False,
        build_fail: bool = False,
        parse_fail: bool = False,
    ) -> None:
        self._run_result = run_result or RunResult(exit_code=0, stdout="End", stderr="")
        self._validate_fail = validate_fail
        self._build_fail = build_fail
        self._parse_fail = parse_fail

    @property
    def solver_name(self) -> str:
        return "fake"

    def validate_inputs(self, raw: dict):
        if self._validate_fail:
            OpenFOAMInput.model_validate({})  # raises ValidationError
        return _Dummy()

    def build_input_files(self, validated, work_dir: Path) -> Path:
        if self._build_fail:
            raise BuildError("mesh missing")
        return work_dir / "case"

    def run(self, case_dir: Path) -> RunResult:
        return self._run_result

    def parse_outputs(self, case_dir: Path) -> dict:
        if self._parse_fail:
            raise ParseError("could not parse results")
        return {"pressure": {"mean": 1.0}}


def _setup(monkeypatch: pytest.MonkeyPatch, connector: _FakeConnector) -> str:
    job_id = "job-1"
    job_store.create_job(job_id, "fake", {"any": "payload"})
    monkeypatch.setattr(worker, "get_connector", lambda name: connector)
    monkeypatch.setattr(
        worker.artifact_store, "store", lambda solver, jid, case: f"/artifacts/{solver}/{jid}"
    )
    return job_id


def test_success_transitions_to_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _setup(monkeypatch, _FakeConnector())
    worker.run_simulation(job_id, "fake", {"any": "payload"})
    record = job_store.get_job(job_id)
    assert record["status"] == "COMPLETED"
    assert record["result_ref"] == f"/artifacts/fake/{job_id}"
    assert record["result"]["pressure"]["mean"] == 1.0


def test_validation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _setup(monkeypatch, _FakeConnector(validate_fail=True))
    worker.run_simulation(job_id, "fake", {})
    record = job_store.get_job(job_id)
    assert record["status"] == "FAILED"
    assert record["error"]["stage"] == "validation"


def test_build_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _setup(monkeypatch, _FakeConnector(build_fail=True))
    worker.run_simulation(job_id, "fake", {})
    record = job_store.get_job(job_id)
    assert record["error"]["stage"] == "build"


def test_solver_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    bad_run = RunResult(exit_code=1, stdout="", stderr="diverged")
    job_id = _setup(monkeypatch, _FakeConnector(run_result=bad_run))
    worker.run_simulation(job_id, "fake", {})
    record = job_store.get_job(job_id)
    assert record["error"]["stage"] == "solver"


def test_parse_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _setup(monkeypatch, _FakeConnector(parse_fail=True))
    worker.run_simulation(job_id, "fake", {})
    record = job_store.get_job(job_id)
    assert record["error"]["stage"] == "parse"
