"""
Demo: cache HIT / MISS / FRESH logs for the argon_equilibration simulation.

Submits the SAME identical request twice and shows the structured logs that prove
cost-effectiveness. Every domain log carries `job_id` — the stable trace key for one
simulation across the router and worker (the HTTP correlation_id changes per poll):
  - run 1: router logs `event=cache_miss`, worker logs `event=run_completed` (solver runs once)
  - run 2: router logs `event=cache_hit`  (no Celery, no solver; the LLM still runs, but the
           collapsed status-poll loop means fewer round-trips)

Each cache decision names the MCP `tool` (run_md_simulation / run_cfd_simulation) and
the `solver` it routed to.

It drives the real router -> worker -> cache path with fakeredis and a stub solver,
so it needs no Docker/Celery/Redis — the point is the LOGS, not the physics.

Run from the project root:
    .venv/bin/python Demo/cache_logs_demo.py

Grep the live system the same way:
    grep '"event": "cache_hit"'      # served from cache (cost saved)
    grep '"event": "cache_miss"'     # fresh run dispatched to solver
    grep '"event": "run_completed"'  # fresh solver run finished + cached
    grep '"job_id": "<id>"'          # the full trace for one simulation
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the project importable when run as `python Demo/cache_logs_demo.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("LOG_FORMAT", "json")
os.environ.setdefault("LOG_LEVEL", "INFO")

import fakeredis

from connectors.base import RunResult, SolverInterface
from execution import cache, job_store, worker
from mcp_server import router
from observability import configure_logging, set_correlation_id


class _SpyLammps(SolverInterface):
    """Stand-in LAMMPS connector that 'runs' instantly and returns argon results."""

    def __init__(self, runs: list[int]) -> None:
        self._runs = runs

    @property
    def solver_name(self) -> str:
        return "lammps"

    def validate_inputs(self, raw: dict):
        return raw

    def build_input_files(self, validated, work_dir: Path) -> Path:
        return work_dir / "case"

    def run(self, case_dir: Path) -> RunResult:
        self._runs.append(1)
        return RunResult(exit_code=0, stdout="LAMMPS done", stderr="")

    def parse_outputs(self, case_dir: Path) -> dict:
        return {
            "temperature": {"mean": 1.49},
            "pressure": {"mean": 6.27},
            "energy": {"total": -4.16},
        }


def main() -> None:
    configure_logging()

    # Wire fakeredis + stub the solver and Celery dispatch (no broker here).
    job_store.set_client(fakeredis.FakeStrictRedis(decode_responses=True))
    cache.set_client(fakeredis.FakeStrictRedis(decode_responses=True))
    runs: list[int] = []
    worker.get_connector = lambda name: _SpyLammps(runs)  # type: ignore[assignment]
    worker.artifact_store.store = lambda jid, case: f"/artifacts/{jid}"  # type: ignore[assignment]
    router._dispatch = lambda *args, **kwargs: None  # type: ignore[assignment]

    payload = {
        "case_name": "argon_equilibration",
        "units": "lj",
        "lattice": {"style": "fcc", "reduced_density": 0.8442, "replicate": [10, 10, 10]},
        "pair": {"style": "lj/cut", "epsilon": 1.0, "sigma": 1.0, "cutoff": 2.5},
        "ensemble": {"type": "nvt", "temperature": 1.5},
        "timestep": 0.005,
        "steps": 2000,
        "dump_every": 100,
    }

    print("\n=== RUN 1: first submission (expect MISS, then FRESH) ===")
    first = router.submit_job("lammps", payload, tool_name="run_md_simulation")
    set_correlation_id(first["job_id"])
    worker.run_simulation(first["job_id"], "lammps", payload)

    print("\n=== RUN 2: identical submission (expect HIT, no solver run) ===")
    set_correlation_id(None)
    second = router.submit_job("lammps", payload, tool_name="run_md_simulation")

    print(f"\nsolver run() invocations across both submissions: {len(runs)}")
    print(f"run 1 status: {first['status']}  ->  run 2 status: {second['status']}")

    job_store.set_client(None)
    cache.set_client(None)


if __name__ == "__main__":
    main()
