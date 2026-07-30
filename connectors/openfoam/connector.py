"""
connectors/openfoam/connector.py — OpenFOAMConnector (Layer 2, Step 1.5).

Implements the SolverInterface contract for OpenFOAM by composing the pieces built in this
phase: the schema (validate), case_builder (build), the runner (run), and output_parser
(parse). Adding OpenFOAM required only files under connectors/openfoam/ plus a registry
entry — no change to the MCP server, router, or execution layer (architecture rule).

The connector builds the simpleFoam command and delegates the actual invocation to a
SolverRunner (Layer 3), so it never execs the solver itself and stays backend-agnostic
(docker exec in Prototype, K8s Job in Production).
"""

from __future__ import annotations

from pathlib import Path

from config import get_settings
from connectors.base import RunResult, SolverInterface
from connectors.openfoam import case_builder, output_parser
from execution.runner import SolverRunner, get_runner
from mcp_server.schemas.openfoam import OpenFOAMInput


class OpenFOAMConnector(SolverInterface):
    """SolverInterface implementation for OpenFOAM simpleFoam (Prototype)."""

    def __init__(self, runner: SolverRunner | None = None) -> None:
        # Runner is injected for testing; defaults to the configured backend.
        self._runner = runner if runner is not None else get_runner()

    @property
    def solver_name(self) -> str:
        return "openfoam"

    def validate_inputs(self, raw: dict) -> OpenFOAMInput:
        """Validate a raw payload into OpenFOAMInput (raises ValidationError if invalid)."""
        return OpenFOAMInput.model_validate(raw)

    def build_input_files(self, validated: OpenFOAMInput, work_dir: Path) -> Path:
        """Write the simpleFoam case directory; raises BuildError on missing mesh."""
        return case_builder.build_case(validated, work_dir)

    def run(self, case_dir: Path) -> RunResult:
        """Invoke simpleFoam in the isolated openfoam-svc container via the runner.

        The OpenFOAM environment is sourced explicitly because the container runs as a
        non-root UID rather than the image's openfoam user.
        """
        settings = get_settings()
        command = [
            "bash",
            "-lc",
            f"source {settings.OPENFOAM_BASHRC} && simpleFoam -case {case_dir}",
        ]
        return self._runner.run(
            container=settings.OPENFOAM_CONTAINER, command=command
        )

    def parse_outputs(self, case_dir: Path) -> dict:
        """Parse the final-time pressure/velocity fields (raises OutputParseError)."""
        return output_parser.parse_outputs(case_dir)

    @staticmethod
    def classify_run_failure(result: RunResult) -> dict:
        """Map a non-zero simpleFoam run to a structured {stage, code, message} error.

        Inspects stderr to classify the common failure modes. Used by the worker
        (docs/phase-1.4) when result.success is False.
        """
        text = f"{result.stderr}\n{result.stdout}".lower()
        if "cannot find file" in text or "polymesh" in text or "no such file" in text:
            code = "MESH_OR_FILE_MISSING"
        elif "diverg" in text or "floating point exception" in text or "nan" in text:
            code = "DIVERGED"
        else:
            code = "SOLVER_ERROR"
        message = (result.stderr.strip() or result.stdout.strip()
                   or "simpleFoam exited with a non-zero status.")
        return {"stage": "solver", "code": code, "message": message[:500]}
