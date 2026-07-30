"""
connectors/lammps/output_parser.py — read LAMMPS thermo output (Step 2.4).

Parses the thermodynamic table from log.lammps into a per-step trajectory plus an
equilibrium summary (late-time averages). The dump files (per-atom data) stay on /work as
artifacts; only the compact summary crosses the MCP boundary.

The thermo table is located by its header row (contains 'Step' and 'Temp'); columns are
mapped case-insensitively so the parser is robust to LAMMPS column ordering. Reads stop at
the first non-numeric / mismatched row (e.g. 'Loop time of ...').
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from connectors.base import ParseError

_REQUIRED = ("step", "temp", "press", "toteng", "poteng")


def _parse_thermo(text: str) -> tuple[dict[str, int], list[list[float]]]:
    """Return (column-index map, numeric rows) for the first thermo table in the log."""
    lines = text.splitlines()
    columns: list[str] | None = None
    data_start = 0
    for i, line in enumerate(lines):
        tokens = line.split()
        lowered = [t.lower() for t in tokens]
        # The real thermo header starts with 'Step'. Guard against the input-script echo
        # line ('thermo_style custom step temp ...'), which also contains 'step'/'temp'.
        if lowered and lowered[0] == "step" and "temp" in lowered:
            columns = tokens
            data_start = i + 1
            break
    if columns is None:
        raise ParseError("no thermo header found in LAMMPS log")

    col = {name.lower(): idx for idx, name in enumerate(columns)}
    missing = [c for c in _REQUIRED if c not in col]
    if missing:
        raise ParseError(f"thermo table missing columns: {missing}")

    rows: list[list[float]] = []
    for line in lines[data_start:]:
        tokens = line.split()
        if len(tokens) != len(columns):
            break
        try:
            rows.append([float(t) for t in tokens])
        except ValueError:
            break
    if not rows:
        raise ParseError("no thermo data rows in LAMMPS log")
    return col, rows


def parse_outputs(case_dir: Path) -> dict[str, Any]:
    """Parse log.lammps into a trajectory and an equilibrium summary."""
    log = Path(case_dir) / "log.lammps"
    if not log.is_file():
        raise ParseError(f"missing LAMMPS log file: {log}")

    col, rows = _parse_thermo(log.read_text())

    def column(name: str) -> list[float]:
        return [row[col[name]] for row in rows]

    steps = column("step")
    temp = column("temp")
    press = column("press")
    etotal = column("toteng")
    poteng = column("poteng")

    # Average the second half of the run as the equilibrated portion.
    eq = slice(len(rows) // 2, None)

    def mean(values: list[float]) -> float:
        window = values[eq]
        return sum(window) / len(window)

    return {
        "steps": int(steps[-1]),
        "trajectory_points": len(rows),
        "equilibrium": {
            "temperature": mean(temp),
            "pressure": mean(press),
            "total_energy": mean(etotal),
            "potential_energy": mean(poteng),
        },
        "trajectory": [
            {"step": int(steps[i]), "temp": temp[i], "press": press[i], "etotal": etotal[i]}
            for i in range(len(rows))
        ],
    }
