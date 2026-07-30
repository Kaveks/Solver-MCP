"""
execution/runner.py — SolverRunner abstraction (Layer 3).

How the worker invokes a solver inside its isolated container. This is the seam that keeps
the connector code identical between Prototype and Production (CLAUDE.md "same code quality"):

    Prototype   RUNNER_BACKEND=docker  -> DockerExecRunner  (docker exec via the Docker socket)
    Production  RUNNER_BACKEND=k8s     -> K8sJobRunner       (submit a Kubernetes Job; Phase 4)

The connector (Layer 2) builds the command and calls runner.run(...); it never knows which
backend it has. Switching tracks is one env var (RUNNER_BACKEND) and one runner class — no
connector or test changes. This also honours the layer boundary: Layer 2 does not invoke the
solver directly; the actual container invocation happens here in Layer 3.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from config import get_settings
from config.settings import RunnerBackend
from connectors.base import RunResult


class SolverRunner(ABC):
    """Invokes a solver command inside its isolated container and returns a RunResult."""

    @abstractmethod
    def run(self, *, container: str, command: list[str]) -> RunResult:
        """Execute `command` in `container` and capture exit code, stdout, and stderr."""


class DockerExecRunner(SolverRunner):
    """Prototype runner: `docker exec` into the running solver container via docker-py.

    The Docker client is created lazily on first run so importing/constructing this class
    never requires a reachable Docker daemon (keeps unit imports side-effect-free).
    """

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            import docker  # imported lazily so docker-py is only needed at run time

            self._client = docker.from_env()
        return self._client

    def run(self, *, container: str, command: list[str]) -> RunResult:
        client = self._get_client()
        target = client.containers.get(container)
        # demux=True splits stdout and stderr so solver errors can be classified.
        result = target.exec_run(cmd=command, demux=True)
        stdout_bytes, stderr_bytes = result.output
        return RunResult(
            exit_code=result.exit_code if result.exit_code is not None else -1,
            stdout=(stdout_bytes or b"").decode(errors="replace"),
            stderr=(stderr_bytes or b"").decode(errors="replace"),
        )


class K8sJobRunner(SolverRunner):
    """Production runner: submit a Kubernetes Job. Implemented in Phase 4 (docs/phase-4.x).

    Registered now so the backend selection is complete and the contract is visible; calling
    it before Phase 4 fails loudly rather than silently degrading.
    """

    def run(self, *, container: str, command: list[str]) -> RunResult:
        raise NotImplementedError(
            "K8sJobRunner is implemented in Phase 4. Set RUNNER_BACKEND=docker for the Prototype."
        )


_RUNNERS: dict[RunnerBackend, type[SolverRunner]] = {
    RunnerBackend.DOCKER: DockerExecRunner,
    RunnerBackend.K8S: K8sJobRunner,
}


def get_runner() -> SolverRunner:
    """Return the SolverRunner for the configured RUNNER_BACKEND."""
    return _RUNNERS[get_settings().RUNNER_BACKEND]()
