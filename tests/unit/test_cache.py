"""
Unit tests for the SHA-256 simulation cache (docs/phase-3.1, Step 3.1).

Normalisation is the contract: semantically-identical inputs must hash identically (key
order, float-representation noise) and genuinely different inputs must differ. Store/get
round-trips. The cache client is fakeredis (injected by the unit conftest).
"""

from __future__ import annotations

import pytest

from execution import cache


def test_key_is_order_independent() -> None:
    a = {"b": 1, "a": 2, "nested": {"y": 1, "x": 2}}
    b = {"a": 2, "nested": {"x": 2, "y": 1}, "b": 1}
    assert cache.cache_key("openfoam", a) == cache.cache_key("openfoam", b)


def test_key_ignores_float_noise() -> None:
    a = {"density": 0.8442}
    b = {"density": 0.8442000000001}
    assert cache.cache_key("lammps", a) == cache.cache_key("lammps", b)


def test_key_differs_on_different_inputs() -> None:
    assert cache.cache_key("openfoam", {"x": 1}) != cache.cache_key("openfoam", {"x": 2})


def test_key_differs_by_solver() -> None:
    payload = {"x": 1}
    assert cache.cache_key("openfoam", payload) != cache.cache_key("lammps", payload)


def test_list_and_tuple_hash_equal() -> None:
    assert cache.cache_key("openfoam", {"v": [1.0, 0.0, 0.0]}) == cache.cache_key(
        "openfoam", {"v": (1.0, 0.0, 0.0)}
    )


def test_store_and_get_roundtrip() -> None:
    key = cache.cache_key("openfoam", {"case": "pipe"})
    assert cache.get(key) is None
    cache.store(key, "/artifacts/job-1", {"pressure": {"mean": 1.0}})
    cached = cache.get(key)
    assert cached["result_ref"] == "/artifacts/job-1"
    assert cached["result"]["pressure"]["mean"] == 1.0


def test_both_solver_payloads_hash() -> None:
    of = {"case_name": "pipe", "fluid": {"kinematic_viscosity": 1e-5}}
    lj = {"case_name": "argon", "ensemble": {"temperature": 1.5}}
    assert cache.cache_key("openfoam", of) != cache.cache_key("lammps", lj)
    # deterministic
    assert cache.cache_key("openfoam", of) == cache.cache_key("openfoam", of)


def test_router_returns_cached_completed_without_dispatch() -> None:
    from mcp_server import router

    payload = {"case_name": "pipe", "anything": 1}
    cache.store(
        cache.cache_key("openfoam", payload), "/artifacts/cached", {"pressure": {"mean": 9.0}}
    )
    result = router.submit_job("openfoam", payload)
    assert result["status"] == "COMPLETED"
    assert result["result_ref"] == "/artifacts/cached"


# ── Solver-intro cache ───────────────────────────────────────────────────────

def test_intro_get_miss_then_roundtrip() -> None:
    prompt = "Introduce the OpenFOAM connector."
    assert cache.get_intro(prompt) is None
    cache.store_intro(prompt, "I run steady turbulent CFD.")
    assert cache.get_intro(prompt) == "I run steady turbulent CFD."


def test_intro_is_keyed_by_prompt() -> None:
    cache.store_intro("prompt A", "answer A")
    cache.store_intro("prompt B", "answer B")
    assert cache.get_intro("prompt A") == "answer A"
    assert cache.get_intro("prompt B") == "answer B"


def test_intro_store_sets_28_day_ttl() -> None:
    cache.store_intro("ttl prompt", "cached text")
    ttl = cache._get_client().ttl(cache._intro_key("ttl prompt"))
    # Within a second of the configured 28-day TTL.
    assert 0 < ttl <= cache.INTRO_TTL_SECONDS
    assert ttl > cache.INTRO_TTL_SECONDS - 5


# ── Layer 2: interpretation cache ─────────────────────────────────────────────
# fakeredis is injected by the unit conftest (autouse), so these use cache directly.


class TestInterpretationCache:
    def test_store_and_retrieve_interpretation(self) -> None:
        cache.store_interpretation("abc123", "The simulation converged.")
        assert cache.get_interpretation("abc123") == "The simulation converged."

    def test_get_interpretation_miss_returns_none(self) -> None:
        assert cache.get_interpretation("nonexistent") is None

    def test_store_empty_interpretation_is_ignored(self) -> None:
        cache.store_interpretation("abc123", "")
        assert cache.get_interpretation("abc123") is None

    def test_store_whitespace_interpretation_is_ignored(self) -> None:
        cache.store_interpretation("abc123", "   ")
        assert cache.get_interpretation("abc123") is None

    def test_interpretation_uses_interp_prefix(self) -> None:
        # interp:{hash} must never collide with the solver cache's cache:{hash}.
        cache.store_interpretation("abc123", "Some result.")
        assert cache.get("abc123") is None  # solver cache untouched
        assert cache.get_interpretation("abc123") == "Some result."

    def test_get_interpretation_redis_unavailable_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_error(*args, **kwargs):
            raise ConnectionError("Redis down")

        monkeypatch.setattr(cache, "_get_client", raise_error)
        assert cache.get_interpretation("abc123") is None  # fall-through, not an exception

    def test_store_interpretation_redis_unavailable_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_error(*args, **kwargs):
            raise ConnectionError("Redis down")

        monkeypatch.setattr(cache, "_get_client", raise_error)
        cache.store_interpretation("abc123", "Some result.")  # must not raise

    def test_get_interpretation_connectionerror_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The /api/chat timeout recovery (Concern 1) depends on this: if Redis raises a
        # ConnectionError during the interpretation lookup, get_interpretation must fall
        # through to None, never propagate the exception into the SSE loop.
        def raise_conn_error(*args, **kwargs):
            raise ConnectionError("Redis down")

        monkeypatch.setattr(cache, "_get_client", raise_conn_error)
        assert cache.get_interpretation("timeout-key") is None

    def test_store_interpretation_empty_string_does_not_raise(self) -> None:
        # The segment-reset guard (Concern 5) can call store_interpretation with an empty
        # string; the empty/whitespace check must swallow it silently — nothing stored, no
        # error raised.
        cache.store_interpretation("empty-key", "")  # must not raise
        assert cache.get_interpretation("empty-key") is None


def test_interpretation_key_matches_solver_cache_key() -> None:
    """Layer 2 shares Layer 1's key: the app derives it by validating the raw tool args
    through the same model the router uses, so the two SHA-256 keys are identical."""
    from mcp_server.routes.simulations import _interpretation_cache_key
    from mcp_server.schemas.openfoam import OpenFOAMInput

    sim_args = {
        "case_name": "pipe",
        "fluid": {"kinematic_viscosity": 1e-5},
        "boundary_conditions": {"inlet_velocity": [1.0, 0.0, 0.0]},
    }
    expected = cache.cache_key("openfoam", OpenFOAMInput.model_validate(sim_args).model_dump())
    assert _interpretation_cache_key("openfoam", sim_args) == expected


def test_interpretation_key_none_on_bad_args() -> None:
    from mcp_server.routes.simulations import _interpretation_cache_key

    assert _interpretation_cache_key("openfoam", "not-a-dict") is None
    assert _interpretation_cache_key(None, {"case_name": "x"}) is None
    assert _interpretation_cache_key("openfoam", {"bogus": True}) is None  # fails validation

