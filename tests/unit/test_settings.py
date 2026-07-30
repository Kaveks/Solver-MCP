"""
Unit tests for config/settings.py and the config package public API.

Covers the scaffolding-gap fix from docs/phase-1.1-scaffolding-and-stack.md (gap 1):
get_settings() must be importable from `config` and return a cached singleton, and the
settings model must fail clearly when the active provider's credential is missing.

These tests never touch a real .env file: the missing-credential test passes
_env_file=None to isolate from any developer .env, and the singleton test sets the
required values via the environment (which takes precedence over .env).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import get_settings
from config.settings import Settings

_PROVIDER_VARS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
    "MCP_API_KEY",
]


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any provider credentials inherited from the host environment."""
    for var in _PROVIDER_VARS:
        monkeypatch.delenv(var, raising=False)


def test_get_settings_importable_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_settings() is importable from `config` and returns a cached singleton."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()

    assert first is second, "get_settings() must return the same cached instance"
    assert first.LLM_PROVIDER.value == "anthropic"

    get_settings.cache_clear()


def test_missing_provider_credential_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a provider without its credential raises a clear validation error."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    assert "OPENAI_API_KEY" in str(excinfo.value)
