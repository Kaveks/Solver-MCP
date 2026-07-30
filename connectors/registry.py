"""
connectors/registry.py — solver name -> connector lookup (Layer 2).

The single data-driven registry of solvers. Adding a solver is one entry here plus its
connector file — no control-flow change anywhere (the router-decision from docs/phase-1.2).
The worker uses get_connector() to drive a job's SolverInterface lifecycle; the router uses
known_solvers() to validate the solver name on submission.

Registered so far: openfoam (docs/phase-1.3). LAMMPS is added in docs/phase-2.2 and FreeCAD
in docs/phase-3.2 — each as one new line here.
"""

from __future__ import annotations

from connectors.base import SolverInterface
from connectors.freecad import FreecadConnector
from connectors.lammps import LAMMPSConnector
from connectors.openfoam import OpenFOAMConnector

_CONNECTORS: dict[str, type[SolverInterface]] = {
    "openfoam": OpenFOAMConnector,
    "lammps": LAMMPSConnector,
    "freecad": FreecadConnector,
}


def known_solvers() -> set[str]:
    """Return the set of registered solver names."""
    return set(_CONNECTORS)


def get_connector(solver_name: str) -> SolverInterface:
    """Instantiate the connector for a registered solver name."""
    try:
        connector_cls = _CONNECTORS[solver_name]
    except KeyError:
        raise ValueError(f"Unknown solver {solver_name!r}; not in the connector registry.")
    return connector_cls()
