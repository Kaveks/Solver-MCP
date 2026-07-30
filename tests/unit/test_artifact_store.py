"""
Unit tests for the artifact store (Layer 3).

Artifacts are grouped by solver — LOCAL_ARTIFACT_PATH/<solver>/<job_id> — so the volume is
self-describing (openfoam/<id>/system/controlDict vs lammps/<id>/log.lammps) without knowing
the tools. These verify the grouped layout and that the returned result_ref points at it.

Settings are injected by monkeypatching artifact_store.get_settings so the tests never depend
on a real .env or the cached settings singleton.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from config.settings import ArtifactStoreType
from execution import artifact_store


def _local_settings(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        ARTIFACT_STORE_TYPE=ArtifactStoreType.LOCAL,
        LOCAL_ARTIFACT_PATH=root,
    )


def _make_case(base: Path) -> Path:
    """Build a minimal case directory (a nested file + a top-level file) under ``base``."""
    case = base / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("controlDict")
    (case / "log.solver").write_text("solver log")
    return case


def test_store_groups_by_solver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "artifacts"
    monkeypatch.setattr(artifact_store, "get_settings", lambda: _local_settings(root))

    ref = artifact_store.store("openfoam", "job-1", _make_case(tmp_path))

    assert ref == str(root / "openfoam" / "job-1")
    assert (root / "openfoam" / "job-1" / "system" / "controlDict").read_text() == "controlDict"


def test_store_separates_same_job_id_across_solvers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The solver segment keeps an identical job_id from two solvers in distinct directories.
    root = tmp_path / "artifacts"
    monkeypatch.setattr(artifact_store, "get_settings", lambda: _local_settings(root))

    of_ref = artifact_store.store("openfoam", "shared-id", _make_case(tmp_path / "a"))
    lmp_ref = artifact_store.store("lammps", "shared-id", _make_case(tmp_path / "b"))

    assert of_ref != lmp_ref
    assert (root / "openfoam" / "shared-id").is_dir()
    assert (root / "lammps" / "shared-id").is_dir()


def test_store_overwrites_existing_job_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A re-run of the same (solver, job_id) replaces prior contents (rmtree before copytree).
    root = tmp_path / "artifacts"
    monkeypatch.setattr(artifact_store, "get_settings", lambda: _local_settings(root))

    first = tmp_path / "first"
    first.mkdir()
    (first / "old.txt").write_text("old")
    artifact_store.store("lammps", "job-x", first)

    second = tmp_path / "second"
    second.mkdir()
    (second / "new.txt").write_text("new")
    artifact_store.store("lammps", "job-x", second)

    dest = root / "lammps" / "job-x"
    assert (dest / "new.txt").exists()
    assert not (dest / "old.txt").exists()


def test_store_rejects_non_local_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = SimpleNamespace(
        ARTIFACT_STORE_TYPE=ArtifactStoreType.S3, LOCAL_ARTIFACT_PATH=tmp_path
    )
    monkeypatch.setattr(artifact_store, "get_settings", lambda: settings)

    with pytest.raises(NotImplementedError):
        artifact_store.store("openfoam", "job-1", _make_case(tmp_path))
