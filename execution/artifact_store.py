"""
execution/artifact_store.py — artifact storage adapter (Layer 3).

Persists a finished case's output files and returns an opaque result_ref the job record
carries. The Prototype uses the local filesystem (a Docker volume); Production swaps the S3
adapter in behind this same interface (docs/phase-4.1) with no change to the worker.

Selected by ARTIFACT_STORE_TYPE. Only `local` is implemented in the Prototype.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from config import get_settings
from config.settings import ArtifactStoreType


def store(solver_name: str, job_id: str, case_dir: Path) -> str:
    """Persist the case outputs for a job and return a result_ref.

    Local adapter: copies the case directory to LOCAL_ARTIFACT_PATH/<solver_name>/<job_id>
    and returns that path as the reference. Grouping by solver makes the artifact volume
    self-describing — a reader can tell at a glance which files came from which solver
    (e.g. openfoam/<id>/system/controlDict vs lammps/<id>/log.lammps) without knowing the
    tools. ``solver_name`` is a registry-validated value (openfoam | lammps | freecad), so
    it is a single safe path segment, not user input.
    """
    settings = get_settings()
    if settings.ARTIFACT_STORE_TYPE != ArtifactStoreType.LOCAL:
        raise NotImplementedError(
            f"Artifact store {settings.ARTIFACT_STORE_TYPE} is implemented in Phase 4; "
            "use ARTIFACT_STORE_TYPE=local for the Prototype."
        )

    dest = Path(settings.LOCAL_ARTIFACT_PATH) / solver_name / job_id
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(case_dir, dest)
    return str(dest)
