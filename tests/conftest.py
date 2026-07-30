"""
Shared pytest fixtures for the Solver-MCP test suite.

Provides a minimal valid baseline environment so modules that read settings (e.g.
execution.worker constructs its Celery app from settings at import) work under test
without a real .env file. Individual tests override these via monkeypatch as needed —
for example, test_settings.py deletes provider credentials to assert failure behaviour.

The settings cache is cleared around each test so the baseline (or a test's overrides)
take effect deterministically.
"""

from __future__ import annotations

import pytest

import config.settings as settings_module
from config.settings import get_settings


@pytest.fixture(autouse=True)
def baseline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tests from any developer .env and provide a minimal valid environment.

    A real .env in the project root would otherwise leak into get_settings(), so we
    disable the dotenv source for the duration of each test and supply the few values
    the suite needs via the environment. Individual tests override these as needed.
    """
    monkeypatch.setitem(settings_module.Settings.model_config, "env_file", None)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
