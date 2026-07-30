"""
mcp_server/schemas/lammps.py — LAMMPSInput Pydantic model.

The validated contract for a molecular-dynamics request. Prototype scope (docs/phase-2.1):
  - units:     lj (reduced units) — the canonical LAMMPS "melt" benchmark
  - config:    script-generated fcc lattice (no external data file)
  - potential: Lennard-Jones (lj/cut)
  - ensemble:  NVT

The single-species LJ fluid uses one atom type (the reduced-unit melt example); the enums
hold the Prototype's allowed values now and widen in Phase 4 (full ensemble / potential /
units support) without changing field types. case_name is path-traversal guarded.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcp_server.schemas._validators import validate_safe_segment


# ---------------------------------------------------------------------------
# Constrained-choice enums
# ---------------------------------------------------------------------------

class LammpsUnits(str, Enum):
    """LAMMPS units system. Prototype: lj (reduced) only."""

    LJ = "lj"


class LatticeStyle(str, Enum):
    """Lattice for the script-generated initial configuration."""

    FCC = "fcc"


class PotentialType(str, Enum):
    """Interatomic potential. Prototype: Lennard-Jones only."""

    LENNARD_JONES = "lennard_jones"


class Ensemble(str, Enum):
    """Thermodynamic ensemble. Prototype: NVT only."""

    NVT = "nvt"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class LatticeSpec(BaseModel):
    """Script-generated initial configuration (lattice + create_atoms)."""

    model_config = ConfigDict(extra="forbid")

    style: LatticeStyle = Field(
        LatticeStyle.FCC, description="Lattice style. Default: fcc."
    )
    reduced_density: float = Field(
        ...,
        gt=0,
        description="Reduced number density passed to `lattice fcc <rho>` (e.g. 0.8442).",
    )
    replicate: tuple[int, int, int] = Field(
        ...,
        description="Box size in lattice units (nx, ny, nz); each >= 1.",
    )

    @field_validator("replicate")
    @classmethod
    def _check_replicate(cls, v: tuple[int, int, int]) -> tuple[int, int, int]:
        if any(n < 1 for n in v):
            raise ValueError("replicate counts must each be >= 1")
        return v


class PotentialSpec(BaseModel):
    """Lennard-Jones potential parameters (reduced units)."""

    model_config = ConfigDict(extra="forbid")

    type: PotentialType = Field(
        PotentialType.LENNARD_JONES, description="Potential type. Default: lennard_jones."
    )
    epsilon: float = Field(1.0, gt=0, description="LJ well depth (reduced). Default 1.0.")
    sigma: float = Field(1.0, gt=0, description="LJ length scale (reduced). Default 1.0.")
    cutoff: float = Field(
        ..., gt=0, description="Pair cutoff distance in sigma units (e.g. 2.5)."
    )


class EnsembleSpec(BaseModel):
    """NVT ensemble parameters."""

    model_config = ConfigDict(extra="forbid")

    type: Ensemble = Field(Ensemble.NVT, description="Ensemble. Default: nvt.")
    temperature: float = Field(
        ..., gt=0, description="Target temperature (reduced T*, e.g. 3.0)."
    )


# ---------------------------------------------------------------------------
# Top-level input model
# ---------------------------------------------------------------------------

class LAMMPSInput(BaseModel):
    """Validated input for an NVT Lennard-Jones molecular-dynamics run (reduced units)."""

    model_config = ConfigDict(extra="forbid")

    case_name: str = Field(
        ...,
        description=(
            "Name of the case directory created under /work. "
            "A single safe path segment (no separators, no traversal)."
        ),
    )
    units: LammpsUnits = Field(
        LammpsUnits.LJ, description="Units system. Prototype: lj only."
    )
    lattice: LatticeSpec
    potential: PotentialSpec
    ensemble: EnsembleSpec
    timestep: float = Field(..., gt=0, description="Integration timestep (reduced).")
    n_steps: int = Field(..., gt=0, description="Number of MD steps to run.")
    output_frequency: int = Field(
        ..., gt=0, description="Thermo output interval in steps."
    )

    @field_validator("case_name")
    @classmethod
    def _check_case_name(cls, v: str) -> str:
        return validate_safe_segment(v)
