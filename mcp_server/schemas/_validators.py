"""
mcp_server/schemas/_validators.py — shared path-safety validators.

The first line of the solver-isolation guarantee (CLAUDE.md): any user-supplied string that
becomes a path on the shared /work volume is validated here, before any file is written.
Used by every solver schema (OpenFOAM, LAMMPS, FreeCAD).
"""

from __future__ import annotations

import re

# A single path segment: letters, digits, dot, underscore, hyphen. No separators.
SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_safe_segment(value: str) -> str:
    """Reject anything that is not a single, safe path segment (no separators, no traversal)."""
    if not value or value in (".", ".."):
        raise ValueError("must be a non-empty path segment, not '.' or '..'")
    if not SEGMENT_RE.match(value):
        raise ValueError(
            "must contain only letters, digits, '.', '_' or '-' and no path separators"
        )
    return value


def validate_safe_relpath(value: str) -> str:
    """Reject absolute paths, backslashes, null bytes, and any '..' traversal."""
    if not value:
        raise ValueError("must be a non-empty relative path")
    if value.startswith("/") or value.startswith("\\"):
        raise ValueError("must be a relative path, not absolute")
    if "\\" in value or "\x00" in value:
        raise ValueError("must not contain backslashes or null bytes")
    for segment in value.split("/"):
        if segment in ("", ".", ".."):
            raise ValueError("must not contain empty, '.' or '..' path segments")
        if not SEGMENT_RE.match(segment):
            raise ValueError(f"invalid path segment: {segment!r}")
    return value
