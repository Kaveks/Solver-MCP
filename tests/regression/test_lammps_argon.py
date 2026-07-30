"""
Phase 2 regression gate (docs/phase-2.2, Step 2.6).

Drives the real worker path on a Lennard-Jones argon NVT case and asserts the equilibrium
properties fall within expected ranges:

    job_store.create_job -> worker.run_simulation -> LAMMPSConnector
        -> script_builder -> real lmp (DockerExecRunner) -> output_parser
        -> artifact_store -> job_store COMPLETED

A dedicated lammps container is started with a same-path bind mount so host and container
paths match. The Celery broker transport and the HTTP submit hop are not exercised here
(both are unit-tested); everything else is the production code.

The robust physical check: under NVT, the equilibrium temperature tracks the thermostat
setpoint (here T* = 1.5) — the LAMMPS analogue of the OpenFOAM mass-conservation check.

Skipped unless Docker and the Solver-MCP/lammps-svc image are available.
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

from execution import cache, job_store, worker  # noqa: E402

_IMAGE = "Solver-MCP/lammps-svc:latest"
_CONTAINER = "Solver-MCP-lammps-regtest"
_HERE = Path(__file__).parent / "lammps"
_SETPOINT = 1.5


def _image_available() -> bool:
    try:
        docker.from_env().images.get(_IMAGE)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _image_available(),
    reason=f"{_IMAGE} not available (build it with: docker compose build lammps-svc)",
)


@pytest.fixture(scope="module")
def lammps_container() -> tuple[str, Path]:
    """Start a lammps container with a same-path bind mount."""
    work = Path(tempfile.mkdtemp(prefix="femlmp_"))
    client = docker.from_env()
    try:
        client.containers.get(_CONTAINER).remove(force=True)
    except Exception:
        pass
    client.containers.run(
        _IMAGE,
        detach=True,
        name=_CONTAINER,
        volumes={str(work): {"bind": str(work), "mode": "rw"}},
        network_mode="none",
    )
    time.sleep(1)
    try:
        yield _CONTAINER, work
    finally:
        try:
            client.containers.get(_CONTAINER).remove(force=True)
        except Exception:
            pass
        shutil.rmtree(work, ignore_errors=True)


def test_lj_argon_within_expected_ranges(
    lammps_container: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    container, work = lammps_container

    from config.settings import get_settings

    monkeypatch.setenv("LAMMPS_CONTAINER", container)
    monkeypatch.setenv("WORK_DIR", str(work))
    monkeypatch.setenv("LOCAL_ARTIFACT_PATH", str(work / "artifacts"))
    monkeypatch.setenv("ARTIFACT_STORE_TYPE", "local")
    get_settings.cache_clear()
    job_store.set_client(fakeredis.FakeStrictRedis(decode_responses=True))
    cache.set_client(fakeredis.FakeStrictRedis(decode_responses=True))

    payload = {
        "case_name": "lj_argon",
        "units": "lj",
        "lattice": {"style": "fcc", "reduced_density": 0.8442, "replicate": [5, 5, 5]},
        "potential": {"type": "lennard_jones", "epsilon": 1.0, "sigma": 1.0, "cutoff": 2.5},
        "ensemble": {"type": "nvt", "temperature": _SETPOINT},
        "timestep": 0.005,
        "n_steps": 2000,
        "output_frequency": 100,
    }

    job_id = "regression-lj-argon"
    job_store.create_job(job_id, "lammps", payload)
    worker.run_simulation(job_id, "lammps", payload)

    record = job_store.get_job(job_id)
    assert record["status"] == "COMPLETED", f"job failed: {record.get('error')}"
    assert record["result_ref"]

    eq = record["result"]["equilibrium"]
    ranges = json.loads((_HERE / "expected_ranges.json").read_text())

    def _in(name: str, value: float) -> None:
        low, high = ranges[name]
        assert low <= value <= high, f"{name}={value} not in [{low}, {high}]"

    _in("temperature", eq["temperature"])
    _in("pressure", eq["pressure"])
    _in("total_energy", eq["total_energy"])

    job_store.set_client(None)
    cache.set_client(None)
    get_settings.cache_clear()
