"""
execution/cache.py — SHA-256 simulation cache (Layer 3).

Before any solver is invoked, the router computes a cache key from the normalised inputs and
checks Redis for a completed result with that key. On a hit the cached result is returned
without enqueuing a job or running the solver, and submit returns COMPLETED immediately so the
agent's status-polling loop collapses (each skipped poll is one fewer LLM round-trip). The LLM
itself still runs on every request — to turn the prompt into the tool call and to interpret the
result — so this cache saves the solver run and the poll loop, not the LLM call. The worker
stores each completed result under its key.

Two-layer cache design (both keyed on the SAME SHA-256 of the normalised (solver, payload)):

  Layer 1 — Solver cache (key: ``cache:{sha256hex}``):
    Stores the numeric result + result_ref. On a hit the solver and the agent's polling
    loop are skipped. Read by the router before dispatch, written by the worker on success.

  Layer 2 — Interpretation cache (key: ``interp:{sha256hex}``):
    Stores the final prose interpretation the agent produced for that result. On a hit the
    final LLM interpretation call is skipped. Falls through gracefully if Redis is
    unavailable. LLM call #1 (tool selection) is never skipped — something must always
    translate the natural-language prompt into a structured tool call.

Normalisation IS the contract (CLAUDE.md): inputs are made canonical before hashing so that
two semantically-identical requests hash identically —
  - dict keys sorted (handled by json.dumps sort_keys),
  - float precision rounded (so 0.8442 and 0.84420000000001 collide),
  - serialised to compact JSON.

The Redis client is module-level and lazy (import never connects); tests inject fakeredis via
set_client(). Cache-unavailable fall-through behaviour is added in docs/phase-3.2.
"""

from __future__ import annotations

import hashlib
import json
from math import floor, log10
from typing import Any

from config import get_settings
from observability import get_logger

logger = get_logger(__name__)

# Significant figures retained when normalising floats before hashing.
_FLOAT_SIGFIGS = 12

_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        import redis

        _client = redis.Redis.from_url(
            get_settings().REDIS_URL.get_secret_value(), decode_responses=True
        )
    return _client


def set_client(client: Any) -> None:
    """Override the Redis client (used by tests to inject fakeredis)."""
    global _client
    _client = client


def _normalise(value: Any) -> Any:
    """Recursively canonicalise a payload: round floats, normalise containers."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if value == 0:
            return 0.0
        digits = _FLOAT_SIGFIGS - int(floor(log10(abs(value)))) - 1
        return round(value, digits)
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    return value


def cache_key(solver_name: str, payload: dict[str, Any]) -> str:
    """Return the SHA-256 cache key for a (solver, payload) pair."""
    canonical = {"solver": solver_name, "payload": _normalise(payload)}
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _key(key_hash: str) -> str:
    return f"cache:{key_hash}"


def get(key_hash: str) -> dict[str, Any] | None:
    """Return the cached result for a key, or None on a miss.

    Cache-unavailable fall-through: if Redis is unreachable, log a warning and return None
    (treated as a miss) so the job proceeds to the solver — an outage degrades performance,
    never correctness (CLAUDE.md caching rule).
    """
    try:
        raw = _get_client().get(_key(key_hash))
    except Exception as exc:
        logger.warning("cache lookup unavailable, falling through to solver: %s", exc)
        return None
    return json.loads(raw) if raw is not None else None


def store(key_hash: str, result_ref: str, result: dict[str, Any]) -> None:
    """Store a completed result under its cache key.

    A failed store is not a failed job: log a warning and continue.
    """
    try:
        _get_client().set(
            _key(key_hash), json.dumps({"result_ref": result_ref, "result": result})
        )
    except Exception as exc:
        logger.warning("cache store unavailable, result not cached: %s", exc)


# ── Layer 2: interpretation cache ─────────────────────────────────────────────
# Keyed on the SAME SHA-256 as the solver cache above (the normalised (solver, payload)
# hash), under an `interp:` prefix so it never collides with the `cache:` numeric record.
# Stores the final prose the agent produced for a result; on a hit the final LLM
# interpretation call is skipped. LLM call #1 (tool selection) is never skipped — something
# must always turn the natural-language prompt into a structured tool call. Same lazy Redis
# client and graceful fall-through as Layer 1: a cache outage degrades to a fresh LLM
# interpretation, never an error.


def _interpretation_key(key_hash: str) -> str:
    return f"interp:{key_hash}"


def get_interpretation(key_hash: str) -> str | None:
    """Return the cached prose interpretation for a result key, or None on a miss.

    Cache-unavailable fall-through: if Redis is unreachable, log a warning and return None
    so the agent interprets fresh. A cache outage never blocks a response.
    """
    try:
        return _get_client().get(_interpretation_key(key_hash))
    except Exception as exc:
        logger.warning(
            "interpretation cache lookup unavailable, falling through to LLM: %s", exc
        )
        return None


def store_interpretation(key_hash: str, interpretation: str) -> None:
    """Store the prose interpretation under interp:{key_hash}.

    A failed store is not a failed request: log a warning and continue (it will be
    regenerated next time). Empty or whitespace-only interpretations are never stored.
    """
    if not interpretation or not interpretation.strip():
        return
    try:
        _get_client().set(_interpretation_key(key_hash), interpretation)
    except Exception as exc:
        logger.warning(
            "interpretation cache store unavailable, interpretation not cached: %s", exc
        )


# ── Solver-intro cache ───────────────────────────────────────────────────────
# The per-solver introduction text is produced by an LLM but does not change between
# deployments, so it is cached with a long TTL: the intro endpoint serves it from cache
# on every sidenav selection and calls the LLM at most once per TTL window. Keyed by a
# hash of the (fixed-per-solver) prompt, so a changed prompt naturally gets a new entry.
# Same Redis client and fall-through behaviour as the simulation cache above.

# 28 days — the intro is not expected to change month-to-month (developer decision).
INTRO_TTL_SECONDS = 28 * 24 * 60 * 60


def _intro_key(prompt: str) -> str:
    digest = hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()
    return f"intro:{digest}"


def get_intro(prompt: str) -> str | None:
    """Return the cached intro text for a prompt, or None on a miss/outage."""
    try:
        return _get_client().get(_intro_key(prompt))
    except Exception as exc:
        logger.warning("intro cache lookup unavailable, regenerating: %s", exc)
        return None


def store_intro(prompt: str, text: str) -> None:
    """Cache an intro text under its prompt hash for INTRO_TTL_SECONDS.

    A failed store is not a failed request: log a warning and continue.
    """
    try:
        _get_client().set(_intro_key(prompt), text, ex=INTRO_TTL_SECONDS)
    except Exception as exc:
        logger.warning("intro cache store unavailable, not cached: %s", exc)
