"""
Unit tests for the FastMCP server, tool router, and the HTTP /jobs route
(docs/phase-1.2, Step 1.3).

Tool discovery must list both tools with their schemas. A valid submission returns a mocked
PENDING record; the job is then retrievable by id over both MCP and HTTP. Invalid input is
rejected with a structured error and no Python stack trace.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from mcp_server import router as solver_router
from mcp_server.app import app
from mcp_server.server import mcp

VALID: dict = {
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


# ── MCP tools (in-memory client) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_discovery_lists_all_tools() -> None:
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert {
        "run_cfd_simulation",
        "run_md_simulation",
        "run_fem_simulation",
        "get_job_status",
    } <= names


@pytest.mark.asyncio
async def test_fem_tool_returns_not_implemented() -> None:
    payload = {"case_name": "bracket", "geometry_ref": "geo/bracket.step"}
    async with Client(mcp) as client:
        result = await client.call_tool("run_fem_simulation", {"simulation": payload})
    assert result.data["status"] == "NOT_IMPLEMENTED"
    assert result.data["error"]["code"] == "NOT_IMPLEMENTED"


@pytest.mark.asyncio
async def test_md_tool_valid_submission_returns_pending() -> None:
    payload = {
        "case_name": "lj_argon",
        "lattice": {"reduced_density": 0.8442, "replicate": [5, 5, 5]},
        "potential": {"cutoff": 2.5},
        "ensemble": {"temperature": 3.0},
        "timestep": 0.005,
        "n_steps": 100,
        "output_frequency": 50,
    }
    async with Client(mcp) as client:
        result = await client.call_tool("run_md_simulation", {"simulation": payload})
    assert result.data["status"] == "PENDING"
    assert result.data["job_id"]


@pytest.mark.asyncio
async def test_cfd_tool_exposes_input_schema() -> None:
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    schema = tools["run_cfd_simulation"].inputSchema
    assert "simulation" in (schema.get("properties") or {})


@pytest.mark.asyncio
async def test_valid_submission_returns_pending() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("run_cfd_simulation", {"simulation": VALID})
    assert result.data["status"] == "PENDING"
    assert result.data["job_id"]


@pytest.mark.asyncio
async def test_status_roundtrip_returns_pending() -> None:
    async with Client(mcp) as client:
        submitted = await client.call_tool("run_cfd_simulation", {"simulation": VALID})
        job_id = submitted.data["job_id"]
        status = await client.call_tool("get_job_status", {"job_id": job_id})
    assert status.data["job_id"] == job_id
    assert status.data["status"] == "PENDING"


@pytest.mark.asyncio
async def test_invalid_submission_structured_no_stacktrace() -> None:
    bad = {**VALID, "fluid": {"kinematic_viscosity": -1}}
    async with Client(mcp) as client:
        with pytest.raises(Exception) as excinfo:  # FastMCP ToolError
            await client.call_tool("run_cfd_simulation", {"simulation": bad})
    text = str(excinfo.value)
    assert "Traceback" not in text
    assert "greater than 0" in text


@pytest.mark.asyncio
async def test_status_not_found_is_structured() -> None:
    async with Client(mcp) as client:
        status = await client.call_tool("get_job_status", {"job_id": "does-not-exist"})
    assert status.data["error"]["code"] == "JOB_NOT_FOUND"


# ── HTTP /jobs route ─────────────────────────────────────────────────────────

def test_http_jobs_returns_record() -> None:
    record = solver_router.submit_job("openfoam", VALID)
    with TestClient(app) as client:
        response = client.get(f"/jobs/{record['job_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == record["job_id"]
    assert body["status"] == "PENDING"


def test_http_jobs_unknown_id_returns_404() -> None:
    with TestClient(app) as client:
        response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "JOB_NOT_FOUND"
