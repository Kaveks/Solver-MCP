"""
mcp_server/server.py — FastMCP server and tool registration (Layer 2).

Creates the FastMCP instance and registers the simulation tools. This module knows nothing
about HTTP routing — it is imported and mounted by mcp_server/app.py. Tool inputs are typed
with the Pydantic schemas from mcp_server/schemas, so the MCP client discovers the full,
validated input contract (function-calling schema for the agent).

Scope (docs/phase-1.2, Step 1.3): tools return a MOCKED PENDING record via the router. Real
Celery dispatch is wired in docs/phase-1.4 without changing these signatures. run_md_simulation
(LAMMPS) is registered in docs/phase-2.2 and the FreeCAD tool in docs/phase-3.2 — each as an
added tool here plus a registry entry in router.py, with no change to existing tools.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from connectors.freecad import FreecadConnector
from mcp_server import router
from mcp_server.schemas import FreecadInput, LAMMPSInput, OpenFOAMInput

mcp: FastMCP = FastMCP("Solver-MCP")


@mcp.tool
def run_cfd_simulation(simulation: OpenFOAMInput) -> dict[str, Any]:
    """Submit a CFD simulation (OpenFOAM simpleFoam, steady turbulent incompressible).

    Returns a job record with a job_id and status PENDING. The run is asynchronous: poll
    get_job_status  tool with the returned job_id until it reaches COMPLETED or FAILED.
    """
    return router.submit_job("openfoam", simulation.model_dump(), tool_name="run_cfd_simulation")


@mcp.tool
def run_md_simulation(simulation: LAMMPSInput) -> dict[str, Any]:
    """Submit a molecular-dynamics simulation (LAMMPS, NVT Lennard-Jones, reduced units).

    Returns a job record with a job_id and status PENDING. The run is asynchronous: poll
    get_job_status with the returned job_id until it reaches COMPLETED or FAILED.
    """
    return router.submit_job("lammps", simulation.model_dump(), tool_name="run_md_simulation")


@mcp.tool
def run_fem_simulation(simulation: FreecadInput) -> dict[str, Any]:
    """Submit a structural finite-element simulation (FreeCAD).

    NOT IMPLEMENTED in the Prototype: input is validated and the tool is discoverable, but
    the connector is a stub. Returns a structured NOT_IMPLEMENTED response; the full FreeCAD
    workflow is available in the Production track (Phase 4).
    """
    return FreecadConnector.not_implemented()


@mcp.tool
def get_job_status(job_id: str) -> dict[str, Any]:
    """Return the status and result of a previously submitted simulation job.

    Response includes job_id and status (PENDING | RUNNING | COMPLETED | FAILED); result_ref
    when COMPLETED, error when FAILED. If the job_id is unknown, returns a structured error.
    """
    record = router.get_job(job_id)
    if record is None:
        return {
            "job_id": job_id,
            "status": "NOT_FOUND",
            "error": {
                "stage": "validation",
                "code": "JOB_NOT_FOUND",
                "message": f"No job exists with id {job_id!r}.",
            },
        }
    return record
