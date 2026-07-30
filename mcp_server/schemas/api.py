"""
mcp_server/schemas/api.py — HTTP request/response models for the Layer 2 web API.

The solver *input* contracts live in their own modules (openfoam.py, lammps.py,
freecad.py) and double as the request bodies for the /api/submit/* endpoints. This
module holds the shapes that are specific to the HTTP surface: the job view returned
by /jobs and /api/submit/*, the health/readiness probes, the chat request/response,
and the structured error envelope.

Every model mirrors a shape that already exists in the codebase rather than inventing a
new one:
  - JobView            -> execution.job_store.public_view (CLAUDE.md /jobs shape)
  - ErrorDetail        -> the {stage, code, message} error contract (CLAUDE.md)
  - NotImplementedView -> connectors.freecad.connector.not_implemented()

Optional fields default to None and routes serialise with response_model_exclude_none,
so the JSON on the wire stays identical to the dicts these endpoints returned before.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Job lifecycle states, kept in one place so JobView and any future consumer agree.
JobStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]


class ErrorDetail(BaseModel):
    """The structured error envelope returned across all layers (CLAUDE.md).

    Never a raw stack trace: stage classifies where it failed, code is a stable
    machine-readable token, message is human-readable.
    """

    stage: str = Field(description="Where it failed: validation | build | solver | parse.")
    code: str = Field(description="Stable machine-readable error token.")
    message: str = Field(description="Human-readable explanation.")


class JobView(BaseModel):
    """Public view of a simulation job — the shape of execution.job_store.public_view.

    Returned by GET /jobs/{job_id} and the POST /api/submit/* endpoints. result_ref and
    result are present only when COMPLETED; error only when FAILED. Routes use
    response_model_exclude_none so absent fields are omitted, not serialised as null.
    """

    job_id: str
    status: JobStatus
    result_ref: str | None = None
    result: dict[str, Any] | None = None
    error: ErrorDetail | None = None


class NotImplementedView(BaseModel):
    """Structured NOT_IMPLEMENTED response for the FreeCAD stub (Prototype)."""

    status: Literal["NOT_IMPLEMENTED"]
    solver: str
    error: ErrorDetail


class HealthResponse(BaseModel):
    """Liveness probe body."""

    status: str


class ReadyResponse(BaseModel):
    """Readiness probe body; reason is present only when not ready."""

    status: str
    reason: str | None = None


class SolverIntroRequest(BaseModel):
    """Body for POST /api/solver-intro.

    message is the intro prompt for the selected solver. This endpoint runs a single
    plain LLM completion (no tools, no MCP, no simulation), so it needs nothing else.
    The conversational chat lives at GET /api/chat.
    """

    message: str = ""


class SolverIntroResponse(BaseModel):
    """Body returned by POST /api/solver-intro: just the generated intro text."""

    response: str
