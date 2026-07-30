"""
connectors/lammps/connector.py — LAMMPSConnector (Layer 2, Step 2.3).

Implements the SolverInterface contract for LAMMPS by composing the schema (validate), the
script_builder (build), the runner (run), and output_parser (parse). Adding LAMMPS touched
only files under connectors/lammps/ plus one registry entry and one MCP tool registration —
the architecture rule holds (no MCP server / router / execution-layer change).

run() delegates to the same SolverRunner abstraction as OpenFOAM; only the container name and
command differ. LAMMPS needs no environment sourcing (lmp is on PATH in the image).
"""

from __future__ import annotations

from pathlib import Path

from config import get_settings
from connectors.base import RunResult, SolverInterface
from connectors.lammps import output_parser, script_builder
from execution.runner import SolverRunner, get_runner
from mcp_server.schemas.lammps import LAMMPSInput


class LAMMPSConnector(SolverInterface):
    """SolverInterface implementation for LAMMPS NVT Lennard-Jones (Prototype)."""

    def __init__(self, runner: SolverRunner | None = None) -> None:
        self._runner = runner if runner is not None else get_runner()

    @property
    def solver_name(self) -> str:
        return "lammps"

    def validate_inputs(self, raw: dict) -> LAMMPSInput:
        return LAMMPSInput.model_validate(raw)

    def build_input_files(self, validated: LAMMPSInput, work_dir: Path) -> Path:
        return script_builder.build_script(validated, work_dir)

    def run(self, case_dir: Path) -> RunResult:
        """Invoke the LAMMPS binary on in.lammps in the isolated lammps-svc container."""
        settings = get_settings()
        command = ["bash", "-lc", f"cd {case_dir} && {settings.LAMMPS_BINARY} -in in.lammps"]
        return self._runner.run(container=settings.LAMMPS_CONTAINER, command=command)

    def parse_outputs(self, case_dir: Path) -> dict:
        return output_parser.parse_outputs(case_dir)

    @staticmethod
    def classify_run_failure(result: RunResult) -> dict:
        """Map a non-zero lmp run to a structured {stage, code, message} error."""
        text = f"{result.stderr}\n{result.stdout}".lower()
        if "lost atoms" in text or "out of range" in text:
            code = "UNSTABLE"
        elif "cannot open" in text or "no such file" in text:
            code = "FILE_MISSING"
        else:
            code = "SOLVER_ERROR"
        message = (result.stderr.strip() or result.stdout.strip()
                   or "lmp exited with a non-zero status.")
        return {"stage": "solver", "code": code, "message": message[:500]}
