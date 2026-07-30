"""
Unit tests for the OpenFOAM connector components (docs/phase-1.3).

This file covers the pure-Python pieces that need no running solver:
  - case_builder.build_case  (Step 1.4)
  - output_parser            (Step 1.6) — added in Unit 3

No solver is invoked here (testing rule: unit tests never run a real solver).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from connectors.base import BuildError, RunResult
from connectors.openfoam.case_builder import build_case
from connectors.openfoam.connector import OpenFOAMConnector
from connectors.openfoam.output_parser import OutputParseError, parse_outputs
from execution.runner import SolverRunner
from mcp_server.schemas.openfoam import OpenFOAMInput
from pydantic import ValidationError


def _valid_input(turbulence_model: str = "kEpsilon") -> OpenFOAMInput:
    return OpenFOAMInput.model_validate(
        {
            "case_name": "pipe_flow",
            "mesh": {"polymesh_ref": "meshes/pipe"},
            "fluid": {
                "kinematic_viscosity": 1e-5,
                "turbulence_model": turbulence_model,
            },
            "boundary_conditions": {
                "inlet_velocity": [1.0, 0.0, 0.0],
                "outlet_pressure": 0.0,
                "inlet_k": 0.1,
                "inlet_turbulence_dissipation": 0.5,
            },
            "controls": {"iterations": 1000, "write_interval": 100},
        }
    )


def _make_mesh(work_dir: Path) -> None:
    """Create a fake pre-existing polyMesh directory at work_dir/meshes/pipe."""
    mesh = work_dir / "meshes" / "pipe"
    mesh.mkdir(parents=True)
    (mesh / "boundary").write_text("// fake polyMesh boundary\n")
    (mesh / "points").write_text("// fake points\n")


def test_build_creates_full_case_structure(tmp_path: Path) -> None:
    _make_mesh(tmp_path)
    case = build_case(_valid_input(), tmp_path)

    assert case == tmp_path / "pipe_flow"
    for rel in (
        "system/controlDict",
        "system/fvSchemes",
        "system/fvSolution",
        "constant/transportProperties",
        "constant/momentumTransport",
        "constant/polyMesh/boundary",
        "0/U",
        "0/p",
        "0/k",
        "0/epsilon",
        "0/nut",
    ):
        assert (case / rel).is_file(), f"missing {rel}"


def test_control_dict_maps_controls(tmp_path: Path) -> None:
    _make_mesh(tmp_path)
    case = build_case(_valid_input(), tmp_path)
    text = (case / "system" / "controlDict").read_text()
    assert "application     simpleFoam;" in text
    assert "endTime" in text and "1000" in text
    assert "writeInterval" in text and "100;" in text


def test_transport_and_turbulence_mapped(tmp_path: Path) -> None:
    _make_mesh(tmp_path)
    case = build_case(_valid_input(), tmp_path)
    assert "1e-05" in (case / "constant" / "transportProperties").read_text()
    assert "kEpsilon" in (case / "constant" / "momentumTransport").read_text()


def test_field_U_has_inlet_velocity(tmp_path: Path) -> None:
    _make_mesh(tmp_path)
    case = build_case(_valid_input(), tmp_path)
    text = (case / "0" / "U").read_text()
    assert "(1.0 0.0 0.0)" in text
    assert "noSlip" in text  # wall BC


def test_kepsilon_writes_epsilon_field_only(tmp_path: Path) -> None:
    _make_mesh(tmp_path)
    case = build_case(_valid_input("kEpsilon"), tmp_path)
    assert (case / "0" / "epsilon").is_file()
    assert not (case / "0" / "omega").exists()
    assert "epsilonWallFunction" in (case / "0" / "epsilon").read_text()


def test_komega_writes_omega_field_only(tmp_path: Path) -> None:
    _make_mesh(tmp_path)
    case = build_case(_valid_input("kOmegaSST"), tmp_path)
    assert (case / "0" / "omega").is_file()
    assert not (case / "0" / "epsilon").exists()
    assert "omegaWallFunction" in (case / "0" / "omega").read_text()


def test_missing_mesh_raises(tmp_path: Path) -> None:
    # No mesh created -> build is a stage='build' failure (BuildError).
    with pytest.raises(BuildError):
        build_case(_valid_input(), tmp_path)


# ── output_parser (Step 1.6) ─────────────────────────────────────────────────

def _write_scalar(path: Path, values: list[float]) -> None:
    body = "\n".join(str(v) for v in values)
    path.write_text(
        "FoamFile { object p; }\n"
        "dimensions      [0 2 -2 0 0 0 0];\n"
        f"internalField   nonuniform List<scalar>\n{len(values)}\n(\n{body}\n)\n;\n"
        "boundaryField { }\n"
    )


def _write_vector(path: Path, vectors: list[tuple[float, float, float]]) -> None:
    body = "\n".join(f"({x} {y} {z})" for x, y, z in vectors)
    path.write_text(
        "FoamFile { object U; }\n"
        "dimensions      [0 1 -1 0 0 0 0];\n"
        f"internalField   nonuniform List<vector>\n{len(vectors)}\n(\n{body}\n)\n;\n"
        "boundaryField { }\n"
    )


def _finished_case(case_dir: Path, time: str, p: list[float], u: list[tuple]) -> None:
    (case_dir / "system").mkdir(parents=True, exist_ok=True)
    (case_dir / "constant").mkdir(parents=True, exist_ok=True)
    time_dir = case_dir / time
    time_dir.mkdir(parents=True, exist_ok=True)
    _write_scalar(time_dir / "p", p)
    _write_vector(time_dir / "U", u)


def test_parse_outputs_summary(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _finished_case(case, "100", [1.0, 2.0, 3.0], [(1.0, 0.0, 0.0), (3.0, 0.0, 0.0)])
    result = parse_outputs(case)

    assert result["time"] == "100"
    assert result["cells"] == 2
    assert result["pressure"]["min"] == 1.0
    assert result["pressure"]["max"] == 3.0
    assert result["pressure"]["mean"] == 2.0
    assert result["velocity"]["magnitude"]["min"] == 1.0
    assert result["velocity"]["magnitude"]["max"] == 3.0
    assert result["velocity"]["magnitude"]["mean"] == 2.0
    assert result["velocity"]["mean_vector"] == [2.0, 0.0, 0.0]


def test_parse_picks_latest_time_dir(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _finished_case(case, "0", [0.0], [(0.0, 0.0, 0.0)])
    _finished_case(case, "100", [5.0], [(5.0, 0.0, 0.0)])
    _finished_case(case, "200", [9.0], [(9.0, 0.0, 0.0)])
    result = parse_outputs(case)
    assert result["time"] == "200"
    assert result["pressure"]["mean"] == 9.0


def test_parse_uniform_fields(tmp_path: Path) -> None:
    case = tmp_path / "case"
    time_dir = case / "50"
    time_dir.mkdir(parents=True)
    (time_dir / "p").write_text(
        "FoamFile { object p; }\ninternalField   uniform 5;\nboundaryField { }\n"
    )
    (time_dir / "U").write_text(
        "FoamFile { object U; }\ninternalField   uniform (2 0 0);\nboundaryField { }\n"
    )
    result = parse_outputs(case)
    assert result["pressure"]["mean"] == 5.0
    assert result["velocity"]["magnitude"]["mean"] == 2.0


def test_parse_no_time_dir_raises(tmp_path: Path) -> None:
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    with pytest.raises(OutputParseError):
        parse_outputs(case)


def test_parse_missing_velocity_raises(tmp_path: Path) -> None:
    case = tmp_path / "case"
    time_dir = case / "100"
    time_dir.mkdir(parents=True)
    _write_scalar(time_dir / "p", [1.0])  # no U file
    with pytest.raises(OutputParseError):
        parse_outputs(case)


# ── OpenFOAMConnector (Step 1.5) — with a fake runner, no real solver ────────

class _FakeRunner(SolverRunner):
    """Records the exec call and returns a preset RunResult."""

    def __init__(self, result: RunResult) -> None:
        self._result = result
        self.calls: list[tuple[str, list[str]]] = []

    def run(self, *, container: str, command: list[str]) -> RunResult:
        self.calls.append((container, command))
        return self._result


def _connector(result: RunResult | None = None) -> OpenFOAMConnector:
    runner = _FakeRunner(result or RunResult(exit_code=0, stdout="End", stderr=""))
    return OpenFOAMConnector(runner=runner)


def test_connector_solver_name() -> None:
    assert _connector().solver_name == "openfoam"


def test_connector_validate_inputs_ok_and_bad() -> None:
    connector = _connector()
    model = connector.validate_inputs(
        {
            "case_name": "pipe_flow",
            "mesh": {"polymesh_ref": "meshes/pipe"},
            "fluid": {"kinematic_viscosity": 1e-5},
            "boundary_conditions": {
                "inlet_velocity": [1, 0, 0],
                "inlet_k": 0.1,
                "inlet_turbulence_dissipation": 0.5,
            },
            "controls": {"iterations": 10, "write_interval": 5},
        }
    )
    assert isinstance(model, OpenFOAMInput)
    with pytest.raises(ValidationError):
        connector.validate_inputs({"case_name": "x"})  # missing required sections


def test_connector_build_delegates(tmp_path: Path) -> None:
    _make_mesh(tmp_path)
    connector = _connector()
    case = connector.build_input_files(_valid_input(), tmp_path)
    assert (case / "system" / "controlDict").is_file()


def test_connector_run_builds_simplefoam_command(tmp_path: Path) -> None:
    runner = _FakeRunner(RunResult(exit_code=0, stdout="End", stderr=""))
    connector = OpenFOAMConnector(runner=runner)
    result = connector.run(tmp_path / "pipe_flow")
    assert result.success
    container, command = runner.calls[0]
    assert container == "Solver-MCP-openfoam"
    joined = " ".join(command)
    assert "simpleFoam -case" in joined
    assert "source" in joined and "bashrc" in joined


def test_connector_parse_delegates(tmp_path: Path) -> None:
    case = tmp_path / "case"
    _finished_case(case, "100", [2.0, 4.0], [(2.0, 0.0, 0.0), (4.0, 0.0, 0.0)])
    summary = _connector().parse_outputs(case)
    assert summary["pressure"]["mean"] == 3.0


def test_classify_run_failure_diverged() -> None:
    result = RunResult(exit_code=1, stdout="", stderr="Floating point exception (diverged)")
    err = OpenFOAMConnector.classify_run_failure(result)
    assert err["stage"] == "solver"
    assert err["code"] == "DIVERGED"


def test_classify_run_failure_missing_mesh() -> None:
    result = RunResult(exit_code=1, stdout="", stderr="cannot find file polyMesh/points")
    err = OpenFOAMConnector.classify_run_failure(result)
    assert err["code"] == "MESH_OR_FILE_MISSING"


def test_classify_run_failure_generic() -> None:
    result = RunResult(exit_code=1, stdout="", stderr="some unexpected solver problem")
    err = OpenFOAMConnector.classify_run_failure(result)
    assert err["code"] == "SOLVER_ERROR"
    assert err["stage"] == "solver"


# ── LAMMPS script_builder (docs/phase-2.1, Step 2.2) ─────────────────────────

from connectors.lammps.script_builder import build_script, render_script
from mcp_server.schemas.lammps import LAMMPSInput


def _lammps_input() -> LAMMPSInput:
    return LAMMPSInput.model_validate(
        {
            "case_name": "lj_argon",
            "units": "lj",
            "lattice": {"style": "fcc", "reduced_density": 0.8442, "replicate": [10, 10, 10]},
            "potential": {"type": "lennard_jones", "epsilon": 1.0, "sigma": 1.0, "cutoff": 2.5},
            "ensemble": {"type": "nvt", "temperature": 3.0},
            "timestep": 0.005,
            "n_steps": 1000,
            "output_frequency": 50,
        }
    )


def test_lammps_script_has_expected_sections() -> None:
    script = render_script(_lammps_input())
    assert "units           lj" in script
    assert "atom_style      atomic" in script
    assert "lattice         fcc 0.8442" in script
    assert "region          box block 0 10 0 10 0 10" in script
    assert "create_atoms    1 box" in script
    assert "pair_style      lj/cut 2.5" in script
    assert "pair_coeff      1 1 1.0 1.0" in script
    assert "velocity        all create 3.0" in script
    assert "fix             1 all nvt temp 3.0 3.0" in script
    assert "timestep        0.005" in script
    assert "thermo          50" in script
    assert "thermo_style    custom step temp press pe ke etotal" in script
    assert "run             1000" in script


def test_lammps_build_script_writes_file(tmp_path: Path) -> None:
    case = build_script(_lammps_input(), tmp_path)
    assert case == tmp_path / "lj_argon"
    assert (case / "in.lammps").is_file()
    assert "units           lj" in (case / "in.lammps").read_text()


def test_lammps_script_reflects_overrides() -> None:
    model = _lammps_input().model_copy(update={"n_steps": 5000, "output_frequency": 200})
    script = render_script(model)
    assert "run             5000" in script
    assert "thermo          200" in script


# ── LAMMPSConnector + output_parser (docs/phase-2.2, Steps 2.3-2.4) ──────────

from connectors.lammps.connector import LAMMPSConnector
from connectors.lammps.output_parser import parse_outputs as lammps_parse

_LAMMPS_LOG = """\
LAMMPS (2 Aug 2023)
Per MPI rank memory allocation
Step Temp Press PotEng KinEng TotEng
0 3.0 1.5 -5.0 4.5 -0.5
50 2.8 1.2 -4.8 4.2 -0.6
100 2.9 1.3 -4.9 4.35 -0.55
Loop time of 0.5 on 1 procs for 100 steps
"""


def _lammps_connector(result: RunResult | None = None) -> LAMMPSConnector:
    runner = _FakeRunner(result or RunResult(exit_code=0, stdout="done", stderr=""))
    return LAMMPSConnector(runner=runner)


def test_lammps_connector_solver_name() -> None:
    assert _lammps_connector().solver_name == "lammps"


def test_lammps_connector_validate_and_build(tmp_path: Path) -> None:
    connector = _lammps_connector()
    model = connector.validate_inputs(VALID_LAMMPS_PAYLOAD)
    case = connector.build_input_files(model, tmp_path)
    assert (case / "in.lammps").is_file()
    with pytest.raises(ValidationError):
        connector.validate_inputs({"case_name": "x"})


def test_lammps_connector_run_builds_lmp_command(tmp_path: Path) -> None:
    runner = _FakeRunner(RunResult(exit_code=0, stdout="done", stderr=""))
    connector = LAMMPSConnector(runner=runner)
    connector.run(tmp_path / "lj_argon")
    container, command = runner.calls[0]
    assert container == "Solver-MCP-lammps"
    joined = " ".join(command)
    assert "lmp_serial -in in.lammps" in joined


def test_lammps_classify_failure() -> None:
    unstable = RunResult(exit_code=1, stdout="", stderr="ERROR: Lost atoms: original 4000")
    assert LAMMPSConnector.classify_run_failure(unstable)["code"] == "UNSTABLE"
    generic = RunResult(exit_code=1, stdout="", stderr="ERROR: something else")
    assert LAMMPSConnector.classify_run_failure(generic)["code"] == "SOLVER_ERROR"


def test_lammps_parse_outputs(tmp_path: Path) -> None:
    case = tmp_path / "lj_argon"
    case.mkdir()
    (case / "log.lammps").write_text(_LAMMPS_LOG)
    summary = lammps_parse(case)
    assert summary["steps"] == 100
    assert summary["trajectory_points"] == 3
    # equilibrium averages the second half (steps 50, 100)
    assert abs(summary["equilibrium"]["temperature"] - 2.85) < 1e-9
    assert abs(summary["equilibrium"]["pressure"] - 1.25) < 1e-9


def test_lammps_parse_missing_log_raises(tmp_path: Path) -> None:
    from connectors.base import ParseError

    case = tmp_path / "empty"
    case.mkdir()
    with pytest.raises(ParseError):
        lammps_parse(case)


VALID_LAMMPS_PAYLOAD = {
    "case_name": "lj_argon",
    "units": "lj",
    "lattice": {"style": "fcc", "reduced_density": 0.8442, "replicate": [10, 10, 10]},
    "potential": {"type": "lennard_jones", "epsilon": 1.0, "sigma": 1.0, "cutoff": 2.5},
    "ensemble": {"type": "nvt", "temperature": 3.0},
    "timestep": 0.005,
    "n_steps": 1000,
    "output_frequency": 50,
}


# ── FreecadConnector stub (docs/phase-3.2, Step 3.4) ─────────────────────────

from connectors.freecad import FreecadConnector
from mcp_server.schemas.freecad import FreecadInput


def test_freecad_connector_validates_and_is_not_implemented() -> None:
    connector = FreecadConnector()
    assert connector.solver_name == "freecad"
    model = connector.validate_inputs(
        {"case_name": "bracket", "geometry_ref": "geo/bracket.step"}
    )
    assert isinstance(model, FreecadInput)
    with pytest.raises(NotImplementedError):
        connector.run(Path("/work/bracket"))


def test_freecad_not_implemented_response_is_structured() -> None:
    response = FreecadConnector.not_implemented()
    assert response["status"] == "NOT_IMPLEMENTED"
    assert response["error"]["code"] == "NOT_IMPLEMENTED"
    assert response["solver"] == "freecad"
