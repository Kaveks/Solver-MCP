"""
observability/tracing.py — LangSmith tracing setup (Step 3.2).

Tracing is configured entirely from settings/env — never hardcoded. When disabled (no key /
LANGSMITH_TRACING unset) this is a no-op and the app runs unchanged; tracing is never a hard
dependency. When enabled, it exports the env vars the langsmith/langchain SDKs read, so a
trace and its logs can be correlated by the same identifier.
"""

from __future__ import annotations

import os

from config import get_settings


def init_tracing() -> bool:
    """Enable LangSmith tracing from settings. Returns True if enabled, False if a no-op."""
    settings = get_settings()
    if not settings.LANGSMITH_TRACING or settings.LANGSMITH_API_KEY is None:
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY.get_secret_value()
    if settings.LANGSMITH_PROJECT:
        os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
    return True
