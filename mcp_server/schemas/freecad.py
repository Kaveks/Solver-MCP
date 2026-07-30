"""
mcp_server/schemas/freecad.py — FreecadInput Pydantic model.

The validated contract for a structural-FEM request. In the Prototype the FreeCAD connector
is a stub (returns NOT_IMPLEMENTED), so this model is intentionally minimal — enough for the
tool to validate input and be discoverable. The full Production contract (material, mesh
backend, constraints, loads, result fields) is added in docs/phase-4.2.

Path-bearing fields (case_name, geometry_ref) are traversal-guarded like every solver schema.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcp_server.schemas._validators import validate_safe_relpath, validate_safe_segment


class AnalysisType(str, Enum):
    """FEM analysis type. Prototype contract: static only."""

    STATIC = "static"


class FreecadInput(BaseModel):
    """Validated input for a FreeCAD structural-FEM run (stub in the Prototype)."""

    model_config = ConfigDict(extra="forbid")

    case_name: str = Field(
        ...,
        description="Case directory name under /work. A single safe path segment.",
    )
    geometry_ref: str = Field(
        ...,
        description=(
            "Relative path on /work to the geometry file (STEP or FCStd). Traversal-guarded."
        ),
    )
    analysis_type: AnalysisType = Field(
        AnalysisType.STATIC, description="Analysis type. Default: static."
    )

    @field_validator("case_name")
    @classmethod
    def _check_case_name(cls, v: str) -> str:
        return validate_safe_segment(v)

    @field_validator("geometry_ref")
    @classmethod
    def _check_geometry_ref(cls, v: str) -> str:
        return validate_safe_relpath(v)
