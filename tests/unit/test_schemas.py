"""
Unit tests for the solver input schemas (docs/phase-1.2, Step 1.2 — tests-first).

Valid inputs must be accepted; invalid inputs must be rejected, including — as a
first-class case — path traversal in any path-bearing field (solver-isolation rule).
No connector code is exercised here; this is pure schema validation.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from mcp_server.schemas import FreecadInput, LAMMPSInput, OpenFOAMInput

VALID_OPENFOAM: dict = {
    "case_name": "pipe_flow",
    "solver": "simpleFoam",
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


def _payload(**overrides) -> dict:
    """Deep-copy the valid payload and apply top-level overrides."""
    data = copy.deepcopy(VALID_OPENFOAM)
    data.update(overrides)
    return data


# ── Valid ────────────────────────────────────────────────────────────────────

def test_valid_payload_accepted() -> None:
    model = OpenFOAMInput.model_validate(VALID_OPENFOAM)
    assert model.case_name == "pipe_flow"
    assert model.solver.value == "simpleFoam"
    assert model.mesh.polymesh_ref == "meshes/pipe"
    assert model.boundary_conditions.inlet_velocity == (1.0, 0.0, 0.0)


def test_solver_defaults_to_simplefoam() -> None:
    data = _payload()
    data.pop("solver")
    model = OpenFOAMInput.model_validate(data)
    assert model.solver.value == "simpleFoam"


# ── Path traversal (first-class isolation guard) ─────────────────────────────

@pytest.mark.parametrize("bad_case_name", ["../evil", "..", "a/b", "/abs", "with space"])
def test_case_name_rejects_traversal_and_separators(bad_case_name: str) -> None:
    with pytest.raises(ValidationError):
        OpenFOAMInput.model_validate(_payload(case_name=bad_case_name))


@pytest.mark.parametrize(
    "bad_ref", ["../../etc/passwd", "/absolute/path", "meshes/../../x", "a\\b", ""]
)
def test_polymesh_ref_rejects_traversal(bad_ref: str) -> None:
    data = _payload()
    data["mesh"] = {"polymesh_ref": bad_ref}
    with pytest.raises(ValidationError):
        OpenFOAMInput.model_validate(data)


# ── Out of range / wrong type / missing / unsupported ────────────────────────

def test_negative_viscosity_rejected() -> None:
    data = _payload()
    data["fluid"] = {"kinematic_viscosity": -1.0}
    with pytest.raises(ValidationError):
        OpenFOAMInput.model_validate(data)


@pytest.mark.parametrize("bad_iterations", [0, -10])
def test_non_positive_iterations_rejected(bad_iterations: int) -> None:
    data = _payload()
    data["controls"] = {"iterations": bad_iterations, "write_interval": 100}
    with pytest.raises(ValidationError):
        OpenFOAMInput.model_validate(data)


def test_unsupported_turbulence_model_rejected() -> None:
    data = _payload()
    data["fluid"] = {"kinematic_viscosity": 1e-5, "turbulence_model": "made_up"}
    with pytest.raises(ValidationError):
        OpenFOAMInput.model_validate(data)


def test_unsupported_solver_rejected() -> None:
    with pytest.raises(ValidationError):
        OpenFOAMInput.model_validate(_payload(solver="pimpleFoam"))


def test_inlet_velocity_wrong_length_rejected() -> None:
    data = _payload()
    data["boundary_conditions"] = {
        "inlet_velocity": [1.0, 0.0],
        "inlet_k": 0.1,
        "inlet_turbulence_dissipation": 0.5,
    }
    with pytest.raises(ValidationError):
        OpenFOAMInput.model_validate(data)


def test_missing_required_section_rejected() -> None:
    data = _payload()
    data.pop("fluid")
    with pytest.raises(ValidationError):
        OpenFOAMInput.model_validate(data)


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        OpenFOAMInput.model_validate(_payload(unexpected="x"))


# ── De-technicalised defaults and turbulence derivation ──────────────────────

def test_mesh_defaults_to_seeded_polymesh() -> None:
    """mesh may be omitted entirely; it defaults to the seeded polyMesh location."""
    data = _payload()
    data.pop("mesh")
    model = OpenFOAMInput.model_validate(data)
    assert model.mesh.polymesh_ref == "mesh/constant/polyMesh"


def test_controls_iterations_and_write_interval_default() -> None:
    data = _payload()
    data.pop("controls")
    model = OpenFOAMInput.model_validate(data)
    assert model.controls.iterations == 1000
    assert model.controls.write_interval == 100


def test_turbulence_inlets_derived_from_velocity_kepsilon() -> None:
    """Omitting inlet_k / dissipation derives them from velocity (kEpsilon)."""
    data = _payload()
    data["boundary_conditions"] = {"inlet_velocity": [1.0, 0.0, 0.0]}
    model = OpenFOAMInput.model_validate(data)
    # k = 1.5 * (|U| * I)^2 = 1.5 * (1.0 * 0.05)^2
    assert model.boundary_conditions.inlet_k == pytest.approx(0.00375)
    # epsilon = C_mu^0.75 * k^1.5 / L  (matches the hand-tuned demo value ~0.005)
    assert model.boundary_conditions.inlet_turbulence_dissipation == pytest.approx(
        0.09**0.75 * 0.00375**1.5 / 0.007
    )


def test_turbulence_inlets_derived_komega() -> None:
    """The dissipation derivation switches to the omega formula for kOmegaSST."""
    data = _payload()
    data["fluid"] = {"kinematic_viscosity": 1e-5, "turbulence_model": "kOmegaSST"}
    data["boundary_conditions"] = {"inlet_velocity": [1.0, 0.0, 0.0]}
    model = OpenFOAMInput.model_validate(data)
    # omega = sqrt(k) / (C_mu^0.25 * L)
    assert model.boundary_conditions.inlet_turbulence_dissipation == pytest.approx(
        (0.00375**0.5) / (0.09**0.25 * 0.007)
    )


def test_explicit_turbulence_inlets_are_not_overridden() -> None:
    data = _payload()
    data["boundary_conditions"] = {
        "inlet_velocity": [1.0, 0.0, 0.0],
        "inlet_k": 0.2,
        "inlet_turbulence_dissipation": 0.9,
    }
    model = OpenFOAMInput.model_validate(data)
    assert model.boundary_conditions.inlet_k == 0.2
    assert model.boundary_conditions.inlet_turbulence_dissipation == 0.9


def test_zero_velocity_with_omitted_turbulence_rejected() -> None:
    data = _payload()
    data["boundary_conditions"] = {"inlet_velocity": [0.0, 0.0, 0.0]}
    with pytest.raises(ValidationError):
        OpenFOAMInput.model_validate(data)


# ── LAMMPSInput (docs/phase-2.1, Step 2.1) ───────────────────────────────────

VALID_LAMMPS: dict = {
    "case_name": "lj_argon",
    "units": "lj",
    "lattice": {"style": "fcc", "reduced_density": 0.8442, "replicate": [10, 10, 10]},
    "potential": {"type": "lennard_jones", "epsilon": 1.0, "sigma": 1.0, "cutoff": 2.5},
    "ensemble": {"type": "nvt", "temperature": 3.0},
    "timestep": 0.005,
    "n_steps": 1000,
    "output_frequency": 50,
}


def _lammps(**overrides) -> dict:
    data = copy.deepcopy(VALID_LAMMPS)
    data.update(overrides)
    return data


def test_lammps_valid_payload_accepted() -> None:
    model = LAMMPSInput.model_validate(VALID_LAMMPS)
    assert model.case_name == "lj_argon"
    assert model.units.value == "lj"
    assert model.ensemble.temperature == 3.0
    assert model.lattice.replicate == (10, 10, 10)


def test_lammps_defaults_applied() -> None:
    data = _lammps()
    data.pop("units")
    data["potential"] = {"cutoff": 2.5}  # epsilon/sigma/type default
    model = LAMMPSInput.model_validate(data)
    assert model.units.value == "lj"
    assert model.potential.epsilon == 1.0


@pytest.mark.parametrize("bad_case_name", ["../evil", "lj/argon", "..", "/abs"])
def test_lammps_case_name_rejects_traversal(bad_case_name: str) -> None:
    with pytest.raises(ValidationError):
        LAMMPSInput.model_validate(_lammps(case_name=bad_case_name))


@pytest.mark.parametrize("field,value", [("timestep", 0), ("n_steps", 0), ("output_frequency", -5)])
def test_lammps_non_positive_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        LAMMPSInput.model_validate(_lammps(**{field: value}))


def test_lammps_unsupported_ensemble_rejected() -> None:
    data = _lammps()
    data["ensemble"] = {"type": "npt", "temperature": 3.0}
    with pytest.raises(ValidationError):
        LAMMPSInput.model_validate(data)


def test_lammps_unsupported_potential_rejected() -> None:
    data = _lammps()
    data["potential"] = {"type": "eam", "cutoff": 2.5}
    with pytest.raises(ValidationError):
        LAMMPSInput.model_validate(data)


def test_lammps_negative_temperature_rejected() -> None:
    data = _lammps()
    data["ensemble"] = {"type": "nvt", "temperature": -1.0}
    with pytest.raises(ValidationError):
        LAMMPSInput.model_validate(data)


def test_lammps_zero_replicate_rejected() -> None:
    data = _lammps()
    data["lattice"] = {"reduced_density": 0.8442, "replicate": [10, 0, 10]}
    with pytest.raises(ValidationError):
        LAMMPSInput.model_validate(data)


def test_lammps_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        LAMMPSInput.model_validate(_lammps(unexpected="x"))


# ── FreecadInput (docs/phase-3.2, Step 3.4 stub) ─────────────────────────────

VALID_FREECAD: dict = {
    "case_name": "bracket",
    "geometry_ref": "geometry/bracket.step",
    "analysis_type": "static",
}


def test_freecad_valid_payload_accepted() -> None:
    model = FreecadInput.model_validate(VALID_FREECAD)
    assert model.case_name == "bracket"
    assert model.geometry_ref == "geometry/bracket.step"
    assert model.analysis_type.value == "static"


@pytest.mark.parametrize("bad", ["../etc/passwd", "/abs/x.step", "a\\b", "geo/../x"])
def test_freecad_geometry_ref_rejects_traversal(bad: str) -> None:
    data = dict(VALID_FREECAD, geometry_ref=bad)
    with pytest.raises(ValidationError):
        FreecadInput.model_validate(data)


def test_freecad_case_name_rejects_separators() -> None:
    data = dict(VALID_FREECAD, case_name="a/b")
    with pytest.raises(ValidationError):
        FreecadInput.model_validate(data)


def test_freecad_unknown_field_rejected() -> None:
    data = dict(VALID_FREECAD, unexpected="x")
    with pytest.raises(ValidationError):
        FreecadInput.model_validate(data)
