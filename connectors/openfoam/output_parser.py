"""
connectors/openfoam/output_parser.py — read simpleFoam results (Step 1.6).

Reads the final time-directory field files (p, U) from a finished OpenFOAM case and returns
a compact structured summary (min/max/mean) the agent can reason about. The full field files
remain on /work as artifacts for retrieval; only summaries cross the MCP boundary.

OpenFOAM internalField comes in two forms, both handled here:
  - uniform:     `internalField   uniform 0;`            (or `uniform (0 0 0)` for vectors)
  - nonuniform:  `internalField   nonuniform List<scalar> N ( v1 v2 ... );`
                 `internalField   nonuniform List<vector> N ( (x y z) ... );`
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from connectors.base import ParseError

# Match a single float token (handles 1, 1.0, -1.2e-05).
_FLOAT = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
_VECTOR_RE = re.compile(rf"\(\s*({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s*\)")


class OutputParseError(ParseError):
    """Raised when expected result files are missing or unparseable (stage='parse')."""


def _latest_time_dir(case_dir: Path) -> Path:
    """Return the highest-numbered time directory in the case (the converged result)."""
    times: list[tuple[float, Path]] = []
    for child in case_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            times.append((float(child.name), child))
        except ValueError:
            continue  # skip system/, constant/, polyMesh, etc.
    if not times:
        raise OutputParseError(f"No time directories found in {case_dir}")
    return max(times, key=lambda t: t[0])[1]


def _internal_region(text: str) -> str:
    """Slice out the internalField block (from 'internalField' to 'boundaryField')."""
    start = text.find("internalField")
    if start == -1:
        raise OutputParseError("field file has no internalField entry")
    end = text.find("boundaryField", start)
    return text[start:] if end == -1 else text[start:end]


def _read_scalar_field(path: Path) -> list[float]:
    if not path.is_file():
        raise OutputParseError(f"missing scalar field file: {path}")
    region = _internal_region(path.read_text())
    if "nonuniform" not in region:
        match = re.search(rf"uniform\s+({_FLOAT})", region)
        if not match:
            raise OutputParseError(f"could not parse uniform scalar in {path}")
        return [float(match.group(1))]
    body = region[region.index("(") + 1 : region.rindex(")")]
    return [float(tok) for tok in body.split()]


def _read_vector_field(path: Path) -> list[tuple[float, float, float]]:
    if not path.is_file():
        raise OutputParseError(f"missing vector field file: {path}")
    region = _internal_region(path.read_text())
    if "nonuniform" not in region:
        match = re.search(rf"uniform\s+\(\s*({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s*\)", region)
        if not match:
            raise OutputParseError(f"could not parse uniform vector in {path}")
        return [(float(match.group(1)), float(match.group(2)), float(match.group(3)))]
    vectors = [
        (float(a), float(b), float(c)) for a, b, c in _VECTOR_RE.findall(region)
    ]
    if not vectors:
        raise OutputParseError(f"could not parse nonuniform vector list in {path}")
    return vectors


def _stats(values: list[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def parse_outputs(case_dir: Path) -> dict[str, Any]:
    """Parse the final-time pressure and velocity fields into a structured summary."""
    case_dir = Path(case_dir)
    latest = _latest_time_dir(case_dir)

    pressure = _read_scalar_field(latest / "p")
    velocity = _read_vector_field(latest / "U")
    magnitudes = [math.sqrt(x * x + y * y + z * z) for x, y, z in velocity]
    n = len(velocity)

    return {
        "time": latest.name,
        "cells": n,
        "pressure": {**_stats(pressure), "units": "m^2/s^2 (kinematic)"},
        "velocity": {
            "magnitude": _stats(magnitudes),
            "mean_vector": [
                sum(c[i] for c in velocity) / n for i in range(3)
            ],
            "units": "m/s",
        },
    }
