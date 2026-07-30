"""
connectors/openfoam/case_builder.py — write a simpleFoam case directory (Step 1.4).

Turns a validated OpenFOAMInput into a complete OpenFOAM case on the shared /work volume:

    <work_dir>/<case_name>/
      ├── system/    controlDict, fvSchemes, fvSolution
      ├── constant/  transportProperties, momentumTransport, polyMesh/ (from polymesh_ref)
      └── 0/         U, p, k, (epsilon|omega), nut

This module is the ONLY component that knows OpenFOAM file formats. The connector
orchestrates; the parser reads outputs. It is pure Python (pathlib + shutil) and writes no
files outside <work_dir>/<case_name>.

Mesh provenance (Q6): the case is pre-meshed. polymesh_ref points at an existing polyMesh
directory under /work; build_case copies it into constant/polyMesh.

Patch names: OpenFOAM boundary fields are written per patch. The pre-meshed case is assumed
to use the conventional names 'inlet', 'outlet', and 'walls' (the Phase 1.4 regression mesh
uses these). If a mesh uses different patch names this is the place that must change.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from connectors.base import BuildError
from mcp_server.schemas.openfoam import OpenFOAMInput, TurbulenceModel

# Conventional patch names for the single-inlet pipe-style Prototype case.
_INLET = "inlet"
_OUTLET = "outlet"
_WALLS = "walls"


# ---------------------------------------------------------------------------
# OpenFOAM dictionary header
# ---------------------------------------------------------------------------

def _header(obj_class: str, obj_name: str) -> str:
    return (
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        "    format      ascii;\n"
        f"    class       {obj_class};\n"
        f"    object      {obj_name};\n"
        "}\n"
    )


def _vec(values: tuple[float, float, float]) -> str:
    return f"({values[0]} {values[1]} {values[2]})"


# ---------------------------------------------------------------------------
# Turbulence-model-dependent helpers
# ---------------------------------------------------------------------------

def _dissipation_field(model: TurbulenceModel) -> str:
    """Name of the second turbulence field: epsilon for kEpsilon, omega for kOmegaSST."""
    return "epsilon" if model == TurbulenceModel.K_EPSILON else "omega"


def _dissipation_wall_function(model: TurbulenceModel) -> str:
    return (
        "epsilonWallFunction"
        if model == TurbulenceModel.K_EPSILON
        else "omegaWallFunction"
    )


# ---------------------------------------------------------------------------
# system/
# ---------------------------------------------------------------------------

def _control_dict(inp: OpenFOAMInput) -> str:
    return (
        _header("dictionary", "controlDict")
        + "\n"
        + "application     simpleFoam;\n"
        "startFrom       startTime;\n"
        "startTime       0;\n"
        "stopAt          endTime;\n"
        f"endTime         {inp.controls.iterations};\n"
        "deltaT          1;\n"
        "writeControl    timeStep;\n"
        f"writeInterval   {inp.controls.write_interval};\n"
        "purgeWrite      0;\n"
        "writeFormat     ascii;\n"
        "writePrecision  6;\n"
        "writeCompression off;\n"
        "timeFormat      general;\n"
        "timePrecision   6;\n"
        "runTimeModifiable true;\n"
    )


def _fv_schemes(inp: OpenFOAMInput) -> str:
    diss = _dissipation_field(inp.fluid.turbulence_model)
    return (
        _header("dictionary", "fvSchemes")
        + "\n"
        "ddtSchemes      { default steadyState; }\n"
        "gradSchemes     { default Gauss linear; }\n"
        "divSchemes\n{\n"
        "    default         none;\n"
        "    div(phi,U)      bounded Gauss upwind;\n"
        "    div(phi,k)      bounded Gauss upwind;\n"
        f"    div(phi,{diss})  bounded Gauss upwind;\n"
        "    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n"
        "}\n"
        "laplacianSchemes { default Gauss linear corrected; }\n"
        "interpolationSchemes { default linear; }\n"
        "snGradSchemes   { default corrected; }\n"
    )


def _fv_solution(inp: OpenFOAMInput) -> str:
    res = inp.controls.convergence_residual
    rf = inp.controls.relaxation_factors or {}
    diss = _dissipation_field(inp.fluid.turbulence_model)
    u_rf = rf.get("U", 0.7)
    p_rf = rf.get("p", 0.3)
    k_rf = rf.get("k", 0.7)
    d_rf = rf.get(diss, 0.7)
    return (
        _header("dictionary", "fvSolution")
        + "\n"
        "solvers\n{\n"
        "    p\n    {\n"
        "        solver          GAMG;\n"
        "        tolerance       1e-06;\n"
        "        relTol          0.1;\n"
        "        smoother        GaussSeidel;\n"
        "    }\n"
        f'    "(U|k|{diss})"\n    {{\n'
        "        solver          smoothSolver;\n"
        "        smoother        symGaussSeidel;\n"
        "        tolerance       1e-05;\n"
        "        relTol          0.1;\n"
        "    }\n"
        "}\n\n"
        "SIMPLE\n{\n"
        "    nNonOrthogonalCorrectors 0;\n"
        "    consistent      no;\n"
        "    residualControl\n    {\n"
        f"        p               {res};\n"
        f"        U               {res};\n"
        f'        "(k|{diss})"      {res};\n'
        "    }\n"
        "}\n\n"
        "relaxationFactors\n{\n"
        "    fields\n    {\n"
        f"        p               {p_rf};\n"
        "    }\n"
        "    equations\n    {\n"
        f"        U               {u_rf};\n"
        f"        k               {k_rf};\n"
        f"        {diss}         {d_rf};\n"
        "    }\n"
        "}\n"
    )


# ---------------------------------------------------------------------------
# constant/
# ---------------------------------------------------------------------------

def _transport_properties(inp: OpenFOAMInput) -> str:
    return (
        _header("dictionary", "transportProperties")
        + "\n"
        "transportModel  Newtonian;\n"
        f"nu              [0 2 -1 0 0 0 0] {inp.fluid.kinematic_viscosity};\n"
    )


def _momentum_transport(inp: OpenFOAMInput) -> str:
    return (
        _header("dictionary", "momentumTransport")
        + "\n"
        "simulationType  RAS;\n"
        "RAS\n{\n"
        f"    model           {inp.fluid.turbulence_model.value};\n"
        "    turbulence      on;\n"
        "    printCoeffs     on;\n"
        "}\n"
    )


# ---------------------------------------------------------------------------
# 0/ field files
# ---------------------------------------------------------------------------

def _field_U(inp: OpenFOAMInput) -> str:
    v = _vec(inp.boundary_conditions.inlet_velocity)
    return (
        _header("volVectorField", "U")
        + "\n"
        "dimensions      [0 1 -1 0 0 0 0];\n"
        "internalField   uniform (0 0 0);\n"
        "boundaryField\n{\n"
        f"    {_INLET}\n    {{\n        type            fixedValue;\n        value           uniform {v};\n    }}\n"
        f"    {_OUTLET}\n    {{\n        type            inletOutlet;\n        inletValue      uniform (0 0 0);\n        value           uniform (0 0 0);\n    }}\n"
        f"    {_WALLS}\n    {{\n        type            noSlip;\n    }}\n"
        "}\n"
    )


def _field_p(inp: OpenFOAMInput) -> str:
    p = inp.boundary_conditions.outlet_pressure
    return (
        _header("volScalarField", "p")
        + "\n"
        "dimensions      [0 2 -2 0 0 0 0];\n"
        "internalField   uniform 0;\n"
        "boundaryField\n{\n"
        f"    {_INLET}\n    {{\n        type            zeroGradient;\n    }}\n"
        f"    {_OUTLET}\n    {{\n        type            fixedValue;\n        value           uniform {p};\n    }}\n"
        f"    {_WALLS}\n    {{\n        type            zeroGradient;\n    }}\n"
        "}\n"
    )


def _field_k(inp: OpenFOAMInput) -> str:
    k = inp.boundary_conditions.inlet_k
    return (
        _header("volScalarField", "k")
        + "\n"
        "dimensions      [0 2 -2 0 0 0 0];\n"
        f"internalField   uniform {k};\n"
        "boundaryField\n{\n"
        f"    {_INLET}\n    {{\n        type            fixedValue;\n        value           uniform {k};\n    }}\n"
        f"    {_OUTLET}\n    {{\n        type            inletOutlet;\n        inletValue      uniform {k};\n        value           uniform {k};\n    }}\n"
        f"    {_WALLS}\n    {{\n        type            kqRWallFunction;\n        value           uniform {k};\n    }}\n"
        "}\n"
    )


def _field_dissipation(inp: OpenFOAMInput) -> str:
    name = _dissipation_field(inp.fluid.turbulence_model)
    wall_fn = _dissipation_wall_function(inp.fluid.turbulence_model)
    value = inp.boundary_conditions.inlet_turbulence_dissipation
    # epsilon has dimensions [0 2 -3 ...]; omega has [0 0 -1 ...].
    dims = "[0 2 -3 0 0 0 0]" if name == "epsilon" else "[0 0 -1 0 0 0 0]"
    return (
        _header("volScalarField", name)
        + "\n"
        f"dimensions      {dims};\n"
        f"internalField   uniform {value};\n"
        "boundaryField\n{\n"
        f"    {_INLET}\n    {{\n        type            fixedValue;\n        value           uniform {value};\n    }}\n"
        f"    {_OUTLET}\n    {{\n        type            inletOutlet;\n        inletValue      uniform {value};\n        value           uniform {value};\n    }}\n"
        f"    {_WALLS}\n    {{\n        type            {wall_fn};\n        value           uniform {value};\n    }}\n"
        "}\n"
    )


def _field_nut() -> str:
    return (
        _header("volScalarField", "nut")
        + "\n"
        "dimensions      [0 2 -1 0 0 0 0];\n"
        "internalField   uniform 0;\n"
        "boundaryField\n{\n"
        f"    {_INLET}\n    {{\n        type            calculated;\n        value           uniform 0;\n    }}\n"
        f"    {_OUTLET}\n    {{\n        type            calculated;\n        value           uniform 0;\n    }}\n"
        f"    {_WALLS}\n    {{\n        type            nutkWallFunction;\n        value           uniform 0;\n    }}\n"
        "}\n"
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build_case(validated: OpenFOAMInput, work_dir: Path) -> Path:
    """Write the full simpleFoam case under work_dir and return the case directory.

    Raises BuildError if the referenced polyMesh does not exist on /work — a missing mesh is
    a build-stage failure the worker reports as stage='build'.
    """
    work_dir = Path(work_dir)
    case_dir = work_dir / validated.case_name
    system = case_dir / "system"
    constant = case_dir / "constant"
    zero = case_dir / "0"
    for directory in (system, constant, zero):
        directory.mkdir(parents=True, exist_ok=True)

    # Place the pre-meshed polyMesh.
    mesh_src = work_dir / validated.mesh.polymesh_ref
    if not mesh_src.is_dir():
        raise BuildError(
            f"polyMesh not found at {mesh_src} (polymesh_ref={validated.mesh.polymesh_ref!r})"
        )
    shutil.copytree(mesh_src, constant / "polyMesh", dirs_exist_ok=True)

    # system/
    (system / "controlDict").write_text(_control_dict(validated))
    (system / "fvSchemes").write_text(_fv_schemes(validated))
    (system / "fvSolution").write_text(_fv_solution(validated))

    # constant/
    (constant / "transportProperties").write_text(_transport_properties(validated))
    (constant / "momentumTransport").write_text(_momentum_transport(validated))

    # 0/
    (zero / "U").write_text(_field_U(validated))
    (zero / "p").write_text(_field_p(validated))
    (zero / "k").write_text(_field_k(validated))
    (zero / _dissipation_field(validated.fluid.turbulence_model)).write_text(
        _field_dissipation(validated)
    )
    (zero / "nut").write_text(_field_nut())

    return case_dir
