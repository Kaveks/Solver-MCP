"""
mcp_server/routes/jobs.py — job status / result retrieval over HTTP.

The agent submits a simulation via the MCP tool and gets back a job_id; it then polls this
endpoint to check status and retrieve the result reference.

    GET /jobs/{job_id}  ->  { "job_id", "status", "result_ref"? , "error"? }

Reads from the same in-memory job store as the MCP tools (docs/phase-1.2). docs/phase-1.4
swaps that store for Redis without changing this route.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from mcp_server import router as solver_router
from mcp_server.schemas.api import JobView

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobView, response_model_exclude_none=True)
async def get_job(job_id: str) -> JobView:
    """Return the current status and result for a simulation job, or 404 if unknown."""
    record = solver_router.get_job(job_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "stage": "validation",
                "code": "JOB_NOT_FOUND",
                "message": f"No job exists with id {job_id!r}.",
            },
        )
    return JobView(**record)
