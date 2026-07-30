"""
connectors/base.py — SolverInterface abstract base class (Layer 2).

Every solver connector implements this one contract. Adding a new solver means creating one
new file that implements SolverInterface — no changes to the MCP server, tool router, or
execution layer (architecture rule in CLAUDE.md). OpenFOAM is the first implementer
(docs/phase-1.3); LAMMPS (docs/phase-2.2) and FreeCAD (docs/phase-3.2 stub, docs/phase-4.2
full) follow the same five-member contract.

The five required members:
  - solver_name       property, the registry key (e.g. "openfoam")
  - validate_inputs   raw dict -> validated Pydantic model (raises on invalid)
  - build_input_files validated model + work dir -> case directory written on /work
  - run               case directory -> RunResult (exit code, logs, success)
  - parse_outputs     case directory -> structured result dict

Separation of duties mirrors the OpenFOAM file/CLI pattern: the connector orchestrates;
a builder writes solver-specific input files; a parser reads solver-specific outputs.
Layer 4 (the solver container) holds no business logic — it only runs the binary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel


class BuildError(Exception):
    """Raised by build_input_files when input files cannot be written (stage='build')."""


class ParseError(Exception):
    """Raised by parse_outputs when results cannot be read (stage='parse')."""


@dataclass(frozen=True)
class RunResult:
    """Uniform result of invoking a solver binary.

    success is derived from the exit code so callers do not repeat the `exit_code == 0`
    check; stdout/stderr carry the captured logs for error classification.
    """

    exit_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class SolverInterface(ABC):
    """Abstract contract every solver connector must implement."""

    @property
    @abstractmethod
    def solver_name(self) -> str:
        """Registry key for this solver (e.g. 'openfoam'). Stable, lowercase."""

    @abstractmethod
    def validate_inputs(self, raw: dict) -> BaseModel:
        """Validate a raw input payload into this solver's typed schema model.

        Raises a pydantic ValidationError if the payload is invalid. Returns the validated
        model on success.
        """

    @abstractmethod
    def build_input_files(self, validated: BaseModel, work_dir: Path) -> Path:
        """Write the solver's input files under work_dir and return the case directory.

        The returned path is the root the solver is invoked from (the OpenFOAM case
        directory, the directory holding the LAMMPS script, etc.).
        """

    @abstractmethod
    def run(self, case_dir: Path) -> RunResult:
        """Invoke the solver binary against case_dir and capture its result.

        Implementations execute inside the isolated solver container. The mechanism by
        which the worker reaches that container is an execution-layer concern, not part of
        this contract.
        """

    @abstractmethod
    def parse_outputs(self, case_dir: Path) -> dict:
        """Read the solver's output files from case_dir and return a structured summary."""
