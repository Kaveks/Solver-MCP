"""
mcp_server/schemas/openfoam.py — OpenFOAMInput Pydantic model.

The validated contract for a CFD simulation request. This is the seam between the input
the agent sends and everything that writes files to /work: every field is constrained, and
any field that becomes a path on the shared volume is guarded against path traversal BEFORE
a single file is written (solver-isolation rule in CLAUDE.md).

Prototype scope (docs/phase-1.2):
  - solver:        simpleFoam only (steady, turbulent, incompressible)
  - mesh:          a reference to an already-generated polyMesh on /work
                   (Q6 decision: meshing happens upstream in the Prototype)

The flow-regime and turbulence-model enums hold the Prototype's allowed values now and
widen in Phase 4 without changing field types.

De-technicalised defaults (so a prompt need only state the physics it cares about):
  - mesh.polymesh_ref defaults to the deterministic location openfoam-svc seeds on
    startup ('mesh/constant/polyMesh'); a prompt never has to name the mesh.
  - The turbulence inlet quantities (inlet_k, inlet_turbulence_dissipation) are optional.
    When omitted they are DERIVED from the inlet velocity using the standard turbulence
    estimation formulas (intensity + length scale), so a prompt only states velocity and
    viscosity. Supply them explicitly to override the derivation.
"""

from __future__ import annotations

import math
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mcp_server.schemas._validators import (
    validate_safe_relpath as _validate_safe_relpath,
)
from mcp_server.schemas._validators import (
    validate_safe_segment as _validate_safe_segment,
)

# ---------------------------------------------------------------------------
# Constrained-choice enums
# ---------------------------------------------------------------------------

class FlowRegime(str, Enum):
    """OpenFOAM solver / flow regime. Prototype supports simpleFoam only."""

    SIMPLE_FOAM = "simpleFoam"


class TurbulenceModel(str, Enum):
    """RAS turbulence model for the steady turbulent case."""

    K_EPSILON = "kEpsilon"
    K_OMEGA_SST = "kOmegaSST"


# ---------------------------------------------------------------------------
# Turbulence-estimation constants (used to DERIVE inlet k / epsilon / omega)
# ---------------------------------------------------------------------------

# C_mu: empirical RAS constant used in the standard inlet turbulence formulas.
_C_MU = 0.09

# The Prototype's seeded mesh is a fixed 0.1 x 0.1 m square duct (see
# tests/regression/openfoam/blockMeshDict). The default turbulence length scale is the
# usual fully-developed-duct estimate L = 0.07 * hydraulic_diameter ~= 0.07 * 0.1.
_DEFAULT_MESH_POLYMESH_REF = "mesh/constant/polyMesh"
_DEFAULT_TURBULENCE_INTENSITY = 0.05  # 5% — standard internal-flow default
_DEFAULT_TURBULENCE_LENGTH_SCALE = 0.007  # 0.07 * 0.1 m duct hydraulic diameter


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class MeshSpec(BaseModel):
    """Reference to a pre-generated polyMesh on the shared /work volume (Q6)."""

    model_config = ConfigDict(extra="forbid")

    polymesh_ref: str = Field(
        _DEFAULT_MESH_POLYMESH_REF,
        description=(
            "Relative path on /work to an existing polyMesh directory. Defaults to "
            "'mesh/constant/polyMesh', the location openfoam-svc seeds on startup, so a "
            "prompt never has to name the mesh. Traversal-guarded."
        ),
    )

    @field_validator("polymesh_ref")
    @classmethod
    def _check_polymesh_ref(cls, v: str) -> str:
        return _validate_safe_relpath(v)


class FluidProperties(BaseModel):
    """Incompressible fluid and turbulence model."""

    model_config = ConfigDict(extra="forbid")

    kinematic_viscosity: float = Field(
        ...,
        gt=0,
        description="Kinematic viscosity nu in m^2/s. Must be positive.",
    )
    turbulence_model: TurbulenceModel = Field(
        TurbulenceModel.K_EPSILON,
        description="RAS turbulence model. Default: kEpsilon.",
    )


class BoundaryConditions(BaseModel):
    """Inlet / outlet / wall boundary values for a single-inlet pipe-style case.

    inlet_turbulence_dissipation carries epsilon when turbulence_model is kEpsilon and
    omega when it is kOmegaSST — its meaning follows the chosen model.

    inlet_k and inlet_turbulence_dissipation are optional: when omitted they are derived
    from inlet_velocity by OpenFOAMInput (see _derive_turbulence_inlets) using
    turbulence_intensity and turbulence_length_scale. Provide them to override.
    """

    model_config = ConfigDict(extra="forbid")

    inlet_velocity: tuple[float, float, float] = Field(
        ...,
        description="Inlet velocity vector (Ux, Uy, Uz) in m/s.",
    )
    outlet_pressure: float = Field(
        0.0,
        description="Outlet gauge pressure (kinematic, m^2/s^2). Default 0.",
    )
    inlet_k: float | None = Field(
        None,
        gt=0,
        description=(
            "Inlet turbulent kinetic energy k in m^2/s^2. Optional — derived from "
            "inlet_velocity and turbulence_intensity when omitted. Must be positive."
        ),
    )
    inlet_turbulence_dissipation: float | None = Field(
        None,
        gt=0,
        description=(
            "Inlet turbulence dissipation: epsilon (kEpsilon) or omega (kOmegaSST). "
            "Optional — derived from inlet_k and turbulence_length_scale when omitted. "
            "Must be positive."
        ),
    )
    turbulence_intensity: float = Field(
        _DEFAULT_TURBULENCE_INTENSITY,
        gt=0,
        lt=1,
        description=(
            "Turbulence intensity fraction used to derive inlet_k when it is omitted. "
            "Default 0.05 (5%), the standard internal-flow value."
        ),
    )
    turbulence_length_scale: float = Field(
        _DEFAULT_TURBULENCE_LENGTH_SCALE,
        gt=0,
        description=(
            "Turbulence length scale (m) used to derive the inlet dissipation when it is "
            "omitted. Default 0.007 m (0.07 * the seeded 0.1 m duct hydraulic diameter)."
        ),
    )


class SolverControls(BaseModel):
    """Steady-state run controls (controlDict / fvSolution)."""

    model_config = ConfigDict(extra="forbid")

    iterations: int = Field(
        1000,
        gt=0,
        description=(
            "Maximum number of SIMPLE iterations (steady end time). Default 1000; the "
            "run stops earlier once convergence_residual is met."
        ),
    )
    convergence_residual: float = Field(
        1e-4,
        gt=0,
        lt=1,
        description="Residual convergence criterion. Default 1e-4.",
    )
    write_interval: int = Field(
        100,
        gt=0,
        description="Iteration interval between result writes. Default 100.",
    )
    relaxation_factors: dict[str, float] | None = Field(
        None,
        description=(
            "Optional under-relaxation factors per field (e.g. {'p': 0.3, 'U': 0.7}). "
            "case_builder applies sensible defaults when omitted."
        ),
    )


# ---------------------------------------------------------------------------
# Top-level input model
# ---------------------------------------------------------------------------

class OpenFOAMInput(BaseModel):
    """Validated input for a simpleFoam steady turbulent incompressible CFD run."""

    model_config = ConfigDict(extra="forbid")

    case_name: str = Field(
        ...,
        description=(
            "Name of the case directory created under /work. "
            "A single safe path segment (no separators, no traversal)."
        ),
    )
    solver: FlowRegime = Field(
        FlowRegime.SIMPLE_FOAM,
        description="Solver / flow regime. Prototype: simpleFoam only.",
    )
    mesh: MeshSpec = Field(
        default_factory=MeshSpec,
        description="Mesh reference. Defaults to the seeded 'mesh/constant/polyMesh'.",
    )
    fluid: FluidProperties
    boundary_conditions: BoundaryConditions
    controls: SolverControls = Field(default_factory=SolverControls)

    @field_validator("case_name")
    @classmethod
    def _check_case_name(cls, v: str) -> str:
        return _validate_safe_segment(v)

    @model_validator(mode="after")
    def _derive_turbulence_inlets(self) -> "OpenFOAMInput":
        """Fill inlet_k / inlet_turbulence_dissipation from velocity when omitted.

        Uses the standard RAS inlet-estimation formulas so a prompt only needs to state
        the inlet velocity:
            k       = 1.5 * (|U| * I)^2
            epsilon = C_mu^0.75 * k^1.5 / L      (kEpsilon)
            omega   = sqrt(k) / (C_mu^0.25 * L)  (kOmegaSST)
        where I is turbulence_intensity and L is turbulence_length_scale. A zero-velocity
        inlet cannot be derived; the explicit values must then be supplied.
        """
        bc = self.boundary_conditions
        needs_derivation = (
            bc.inlet_k is None or bc.inlet_turbulence_dissipation is None
        )
        u_mag = math.sqrt(sum(component**2 for component in bc.inlet_velocity))
        if needs_derivation and u_mag <= 0:
            raise ValueError(
                "cannot derive turbulence inlets from a zero-magnitude inlet_velocity; "
                "provide inlet_k and inlet_turbulence_dissipation explicitly"
            )

        if bc.inlet_k is None:
            bc.inlet_k = 1.5 * (u_mag * bc.turbulence_intensity) ** 2

        if bc.inlet_turbulence_dissipation is None:
            length = bc.turbulence_length_scale
            if self.fluid.turbulence_model == TurbulenceModel.K_EPSILON:
                bc.inlet_turbulence_dissipation = (
                    _C_MU**0.75 * bc.inlet_k**1.5 / length
                )
            else:
                bc.inlet_turbulence_dissipation = math.sqrt(bc.inlet_k) / (
                    _C_MU**0.25 * length
                )

        return self
