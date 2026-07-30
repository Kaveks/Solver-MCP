"""
connectors/freecad/connector.py — FreecadConnector (Layer 2, Step 3.4 stub).

A stub that implements the SolverInterface contract so FreeCAD is a registered, discoverable
third solver — proving the registry/contract accept it with no infrastructure change — but
whose execution returns a structured NOT_IMPLEMENTED. The full headless FreeCAD workflow
(geometry import, FEM Workbench, meshing, solve, parse) is implemented in docs/phase-4.2,
which fills in build_input_files / run / parse_outputs with no router or server change.

`validate_inputs` works (so bad input is still rejected cleanly); the execution methods raise
NotImplementedError. The agent-facing NOT_IMPLEMENTED response is `not_implemented()`, returned
by the run_fem_simulation tool — a distinct, explicit "unsupported" signal rather than a
silent failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from connectors.base import RunResult, SolverInterface
from mcp_server.schemas.freecad import FreecadInput

_NOT_IMPLEMENTED_MESSAGE = (
    "The FreeCAD connector is a stub in the Prototype. Structural FEM (geometry import, "
    "meshing, solve) is implemented in the Production track (Phase 4)."
)


class FreecadConnector(SolverInterface):
    """Stub SolverInterface implementation for FreeCAD (Prototype)."""

    @property
    def solver_name(self) -> str:
        return "freecad"

    def validate_inputs(self, raw: dict) -> FreecadInput:
        return FreecadInput.model_validate(raw)

    def build_input_files(self, validated: FreecadInput, work_dir: Path) -> Path:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    def run(self, case_dir: Path) -> RunResult:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    def parse_outputs(self, case_dir: Path) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    @staticmethod
    def not_implemented() -> dict[str, Any]:
        """The structured NOT_IMPLEMENTED response returned to the agent."""
        return {
            "status": "NOT_IMPLEMENTED",
            "solver": "freecad",
            "error": {
                "stage": "solver",
                "code": "NOT_IMPLEMENTED",
                "message": _NOT_IMPLEMENTED_MESSAGE,
            },
        }
