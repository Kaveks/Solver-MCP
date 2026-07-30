"""
Unit tests for the SolverInterface ABC (docs/phase-1.3, Step 1.4 — the contract).

The ABC must be impossible to instantiate directly; a subclass implementing all five
members must instantiate; a subclass missing any member must be rejected. RunResult.success
must follow the exit code.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from connectors.base import RunResult, SolverInterface


class _Dummy(BaseModel):
    value: int = 0


class _CompleteConnector(SolverInterface):
    @property
    def solver_name(self) -> str:
        return "dummy"

    def validate_inputs(self, raw: dict) -> BaseModel:
        return _Dummy(**raw)

    def build_input_files(self, validated: BaseModel, work_dir: Path) -> Path:
        return work_dir / "case"

    def run(self, case_dir: Path) -> RunResult:
        return RunResult(exit_code=0, stdout="", stderr="")

    def parse_outputs(self, case_dir: Path) -> dict:
        return {"ok": True}


class _IncompleteConnector(SolverInterface):
    # Missing run() and parse_outputs() on purpose.
    @property
    def solver_name(self) -> str:
        return "incomplete"

    def validate_inputs(self, raw: dict) -> BaseModel:
        return _Dummy(**raw)

    def build_input_files(self, validated: BaseModel, work_dir: Path) -> Path:
        return work_dir


def test_cannot_instantiate_abc_directly() -> None:
    with pytest.raises(TypeError):
        SolverInterface()  # type: ignore[abstract]


def test_incomplete_subclass_rejected() -> None:
    with pytest.raises(TypeError):
        _IncompleteConnector()  # type: ignore[abstract]


def test_complete_subclass_instantiates() -> None:
    connector = _CompleteConnector()
    assert connector.solver_name == "dummy"
    assert connector.build_input_files(_Dummy(), Path("/work")) == Path("/work/case")
    assert connector.parse_outputs(Path("/work/case")) == {"ok": True}


def test_run_result_success_follows_exit_code() -> None:
    assert RunResult(exit_code=0, stdout="done", stderr="").success is True
    assert RunResult(exit_code=1, stdout="", stderr="diverged").success is False
