"""
Unit tests for the HTTP API request/response models (mcp_server/schemas/api.py)
and the typed endpoints that use them.

Covers two things:
  - the models themselves: defaults, literal constraints, and that JobView's
    optional fields stay absent (not null) on the wire via exclude_none.
  - the endpoints: request bodies are now validated at the HTTP boundary (so a
    malformed payload is a structured 422, not a deferred worker failure), and the
    responses match the documented JobView / NotImplementedView shapes.

No solver or Redis is exercised: submissions only create a PENDING record, and the
chat endpoint is checked on its no-message short-circuit.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mcp_server.app import app
from mcp_server.schemas.api import (
    ErrorDetail,
    JobView,
    NotImplementedView,
    ReadyResponse,
    SolverIntroRequest,
    SolverIntroResponse,
)

# Reuse the canonical valid payloads the schema/server tests use.
VALID_CFD: dict = {
    "case_name": "pipe_flow",
    "mesh": {"polymesh_ref": "meshes/pipe"},
    "fluid": {"kinematic_viscosity": 1e-5, "turbulence_model": "kEpsilon"},
    "boundary_conditions": {
        "inlet_velocity": [1.0, 0.0, 0.0],
        "outlet_pressure": 0.0,
        "inlet_k": 0.1,
        "inlet_turbulence_dissipation": 0.5,
    },
    "controls": {"iterations": 1000, "write_interval": 100},
}

VALID_MD: dict = {
    "case_name": "lj_argon",
    "units": "lj",
    "lattice": {"style": "fcc", "reduced_density": 0.8442, "replicate": [10, 10, 10]},
    "potential": {"type": "lennard_jones", "epsilon": 1.0, "sigma": 1.0, "cutoff": 2.5},
    "ensemble": {"type": "nvt", "temperature": 3.0},
    "timestep": 0.005,
    "n_steps": 1000,
    "output_frequency": 50,
}

VALID_FEM: dict = {"case_name": "bracket", "geometry_ref": "geo/bracket.step"}

client = TestClient(app)


# ── Models ───────────────────────────────────────────────────────────────────

def test_jobview_omits_absent_fields() -> None:
    """A PENDING job serialises to just job_id + status (exclude_none drops the rest)."""
    view = JobView(job_id="abc", status="PENDING")
    assert view.model_dump(exclude_none=True) == {"job_id": "abc", "status": "PENDING"}


def test_jobview_completed_carries_result() -> None:
    view = JobView(job_id="abc", status="COMPLETED", result_ref="ref", result={"k": 1})
    dumped = view.model_dump(exclude_none=True)
    assert dumped["result_ref"] == "ref"
    assert dumped["result"] == {"k": 1}
    assert "error" not in dumped


def test_jobview_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        JobView(job_id="abc", status="WAT")


def test_error_detail_requires_all_fields() -> None:
    err = ErrorDetail(stage="solver", code="X", message="boom")
    assert err.stage == "solver"
    with pytest.raises(ValidationError):
        ErrorDetail(stage="solver", code="X")  # missing message


def test_not_implemented_view_matches_stub_shape() -> None:
    from connectors.freecad.connector import FreecadConnector

    view = NotImplementedView(**FreecadConnector.not_implemented())
    assert view.status == "NOT_IMPLEMENTED"
    assert view.solver == "freecad"
    assert view.error.code == "NOT_IMPLEMENTED"


def test_ready_response_excludes_reason_when_none() -> None:
    assert ReadyResponse(status="ready").model_dump(exclude_none=True) == {"status": "ready"}


def test_solver_intro_request_default_message() -> None:
    assert SolverIntroRequest().message == ""
    assert SolverIntroRequest(message="hi").message == "hi"


def test_solver_intro_response_shape() -> None:
    assert SolverIntroResponse(response="hello").model_dump() == {"response": "hello"}


# ── Endpoints ────────────────────────────────────────────────────────────────

def test_submit_cfd_valid_returns_pending_jobview() -> None:
    resp = client.post("/api/submit/cfd", json=VALID_CFD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PENDING"
    assert "job_id" in body
    # exclude_none: a fresh PENDING job carries no result/error keys.
    assert "result" not in body and "error" not in body


def test_submit_cfd_invalid_is_422_at_boundary() -> None:
    bad = {"case_name": "x"}  # missing required mesh/fluid/bc/controls
    resp = client.post("/api/submit/cfd", json=bad)
    assert resp.status_code == 422


def test_submit_md_valid_returns_pending_jobview() -> None:
    resp = client.post("/api/submit/md", json=VALID_MD)
    assert resp.status_code == 200
    assert resp.json()["status"] == "PENDING"


def test_submit_fem_returns_not_implemented() -> None:
    resp = client.post("/api/submit/fem", json=VALID_FEM)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT_IMPLEMENTED"
    assert body["error"]["code"] == "NOT_IMPLEMENTED"


def test_solver_intro_empty_message_short_circuits() -> None:
    # Empty prompt returns "" without ever building the LLM (no key needed).
    resp = client.post("/api/solver-intro", json={"message": "   "})
    assert resp.status_code == 200
    assert resp.json() == {"response": ""}


def test_solver_intro_caches_and_calls_llm_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # First call misses the cache and runs the LLM; the identical second call is served
    # from cache with no LLM round-trip. (fakeredis is injected by the unit conftest.)
    from agent import agent as agent_mod

    calls = {"n": 0}

    class _FakeOut:
        content = "Generated intro."

    class _FakeLLM:
        async def ainvoke(self, _messages: object) -> _FakeOut:
            calls["n"] += 1
            return _FakeOut()

    monkeypatch.setattr(agent_mod, "build_llm", lambda: _FakeLLM())

    body = {"message": "Introduce the OpenFOAM connector."}
    first = client.post("/api/solver-intro", json=body)
    second = client.post("/api/solver-intro", json=body)

    assert first.json() == {"response": "Generated intro."}
    assert second.json() == {"response": "Generated intro."}
    assert calls["n"] == 1  # second request hit the cache, not the LLM


def test_chat_empty_message_streams_done_event() -> None:
    # GET /api/chat is the SSE chat path; an empty message emits a single `done`
    # event and returns without building the agent (no LLM key needed).
    resp = client.get("/api/chat", params={"message": ""})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert '"type": "done"' in resp.text
    assert '"response": ""' in resp.text


# ── Backend-sourced, per-device job history (GET /api/jobs) ───────────────────
# The backend (Redis) is the single source of truth; the list is scoped by owner so each
# device sees only its own jobs. fakeredis is injected into job_store by the unit conftest.

def _make_completed_job(job_id: str, owner: str, case_name: str) -> None:
    from execution import job_store

    job_store.create_job(job_id, "openfoam", {"case_name": case_name}, owner=owner)
    job_store.set_status(job_id, "COMPLETED", result_ref=f"/art/{job_id}",
                         result={"pressure": {"mean": 1.0}})
    job_store.set_interpretation(job_id, f"Interpretation for {case_name}.")


def test_api_jobs_scoped_to_owner() -> None:
    _make_completed_job("job-a1", "device-A", "pipe_a")
    _make_completed_job("job-a2", "device-A", "pipe_b")
    _make_completed_job("job-b1", "device-B", "argon")

    resp = client.get("/api/jobs", params={"owner": "device-A"})
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    ids = {j["job_id"] for j in jobs}
    assert ids == {"job-a1", "job-a2"}  # device-B's job is excluded
    # List view carries the fields the history UI renders.
    j = jobs[0]
    assert j["case_name"] in {"pipe_a", "pipe_b"}
    assert j["solver"] == "openfoam"
    assert j["interpretation"].startswith("Interpretation for")
    assert j["result"]["pressure"]["mean"] == 1.0
    assert j["created_at"]


def test_api_jobs_empty_for_unknown_owner() -> None:
    _make_completed_job("job-x", "device-A", "pipe_a")
    resp = client.get("/api/jobs", params={"owner": "nobody"})
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []
