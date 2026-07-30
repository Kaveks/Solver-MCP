"""
Phase 1 regression gate (docs/phase-1.4, Step 1.8).

Drives the real worker path on a known duct-flow case and asserts the parsed results fall
within expected ranges:

    job_store.create_job -> worker.run_simulation -> OpenFOAMConnector
        -> case_builder -> real simpleFoam (DockerExecRunner) -> output_parser
        -> artifact_store -> job_store COMPLETED

A dedicated openfoam container is started with a same-path bind mount so host and container
paths match; blockMesh generates the mesh. The Celery broker transport and the HTTP submit
hop are not exercised here (both are unit-tested); everything else is the production code.

Skipped unless Docker and the Solver-MCP/openfoam-svc image are available.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

import pytest

docker = pytest.importorskip("docker")

import fakeredis  # noqa: E402

from execution import artifact_store, cache, job_store, worker  # noqa: E402
from execution.runner import DockerExecRunner  # noqa: E402

_IMAGE = "Solver-MCP/openfoam-svc:latest"
_CONTAINER = "Solver-MCP-openfoam-regtest"
_BASHRC = "/opt/openfoam10/etc/bashrc"
_HERE = Path(__file__).parent / "openfoam"


def _image_available() -> bool:
    try:
        docker.from_env().images.get(_IMAGE)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _image_available(),
    reason=f"{_IMAGE} not available (build it with: docker compose build openfoam-svc)",
)


@pytest.fixture(scope="module")
def openfoam_case() -> tuple[str, Path]:
    """Start an openfoam container (same-path bind mount) and generate the duct mesh."""
    work = Path(tempfile.mkdtemp(prefix="femreg_"))
    client = docker.from_env()
    runner = DockerExecRunner()

    try:
        old = client.containers.get(_CONTAINER)
        old.remove(force=True)
    except Exception:
        pass

    container = client.containers.run(
        _IMAGE,
        detach=True,
        name=_CONTAINER,
        volumes={str(work): {"bind": str(work), "mode": "rw"}},
        network_mode="none",
    )
    time.sleep(1)

    # Mesh case: blockMeshDict + a minimal controlDict so blockMesh has a valid case.
    mesh = work / "mesh"
    (mesh / "system").mkdir(parents=True)
    (mesh / "constant").mkdir(parents=True)
    (mesh / "system" / "blockMeshDict").write_text((_HERE / "blockMeshDict").read_text())
    (mesh / "system" / "controlDict").write_text(
        "FoamFile{version 2.0;format ascii;class dictionary;object controlDict;}\n"
        "application simpleFoam; startTime 0; endTime 1; deltaT 1; writeInterval 1;\n"
    )
    result = runner.run(
        container=_CONTAINER,
        command=["bash", "-lc", f"source {_BASHRC} && blockMesh -case {mesh}"],
    )
    assert result.exit_code == 0, f"blockMesh failed: {result.stderr[-1500:]}"

    try:
        yield _CONTAINER, work
    finally:
        try:
            client.containers.get(_CONTAINER).remove(force=True)
        except Exception:
            pass
        shutil.rmtree(work, ignore_errors=True)


def test_pipe_flow_within_expected_ranges(
    openfoam_case: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    container, work = openfoam_case

    # Point the production code at this container / work dir; use fakeredis for the store.
    from config.settings import get_settings

    monkeypatch.setenv("OPENFOAM_CONTAINER", container)
    monkeypatch.setenv("WORK_DIR", str(work))
    monkeypatch.setenv("LOCAL_ARTIFACT_PATH", str(work / "artifacts"))
    monkeypatch.setenv("ARTIFACT_STORE_TYPE", "local")
    get_settings.cache_clear()
    job_store.set_client(fakeredis.FakeStrictRedis(decode_responses=True))
    cache.set_client(fakeredis.FakeStrictRedis(decode_responses=True))

    payload = {
        "case_name": "pipe_flow",
        "mesh": {"polymesh_ref": "mesh/constant/polyMesh"},
        "fluid": {"kinematic_viscosity": 1e-5, "turbulence_model": "kEpsilon"},
        "boundary_conditions": {
            "inlet_velocity": [1.0, 0.0, 0.0],
            "outlet_pressure": 0.0,
            "inlet_k": 0.00375,
            "inlet_turbulence_dissipation": 0.005,
        },
        "controls": {"iterations": 500, "write_interval": 100},
    }

    job_id = "regression-pipe-flow"
    job_store.create_job(job_id, "openfoam", payload)
    worker.run_simulation(job_id, "openfoam", payload)

    record = job_store.get_job(job_id)
    assert record["status"] == "COMPLETED", f"job failed: {record.get('error')}"
    assert record["result_ref"]
    assert (work / "artifacts" / "openfoam" / job_id).is_dir()  # artifact persisted (grouped by solver)

    summary = record["result"]
    ranges = json.loads((_HERE / "expected_ranges.json").read_text())

    def _in(name: str, value: float) -> None:
        low, high = ranges[name]
        assert low <= value <= high, f"{name}={value} not in [{low}, {high}]"

    vmag = summary["velocity"]["magnitude"]
    _in("velocity_magnitude_mean", vmag["mean"])
    _in("velocity_magnitude_max", vmag["max"])
    _in("velocity_magnitude_min", vmag["min"])
    _in("pressure_mean", summary["pressure"]["mean"])
    _in("pressure_max", summary["pressure"]["max"])
    _in("mean_vector_x", summary["velocity"]["mean_vector"][0])

    job_store.set_client(None)
    cache.set_client(None)
    get_settings.cache_clear()
