"""
Integration test for the OpenFOAM exec path (docs/phase-1.3, Step 1.5).

Verifies the real mechanism: the DockerExecRunner can exec into the isolated, running
openfoam-svc container and reach simpleFoam after sourcing the OpenFOAM environment. This
confirms the Q3 decision (Docker socket + docker exec) and the explicit env sourcing work
against the actual image.

The full mesh -> simpleFoam -> parse end-to-end with a real pipe-flow mesh is the Phase 1.4
regression test (run by the worker inside the stack, sharing the /work volume).

Skipped automatically unless the openfoam-svc container is running:
    docker compose up -d openfoam-svc
"""

from __future__ import annotations

import pytest

docker = pytest.importorskip("docker")

from execution.runner import DockerExecRunner  # noqa: E402

_CONTAINER = "Solver-MCP-openfoam"
_BASHRC = "/opt/openfoam10/etc/bashrc"


def _container_running() -> bool:
    try:
        client = docker.from_env()
        return client.containers.get(_CONTAINER).status == "running"
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _container_running(),
    reason=f"{_CONTAINER} not running (start it with: docker compose up -d openfoam-svc)",
)


def test_exec_reaches_simplefoam_after_sourcing_env() -> None:
    runner = DockerExecRunner()
    result = runner.run(
        container=_CONTAINER,
        command=["bash", "-lc", f"source {_BASHRC} && which simpleFoam"],
    )
    assert result.exit_code == 0, f"stderr: {result.stderr}"
    assert "simpleFoam" in result.stdout


def test_exec_nonzero_exit_is_captured() -> None:
    runner = DockerExecRunner()
    result = runner.run(
        container=_CONTAINER,
        command=["bash", "-lc", "exit 7"],
    )
    assert result.exit_code == 7
    assert result.success is False
