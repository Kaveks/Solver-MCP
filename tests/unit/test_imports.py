"""
Import regression guard for the scaffolding modules.

Covers gaps 1-3 from docs/phase-1.1-scaffolding-and-stack.md: importing these modules
must not raise. This is the cheap early warning that the config export, the prompts
module, and the (migrated) agent module all load cleanly before the Docker stack is even
built. If any of these break again, this test fails before a container would.

Importing agent.agent exercises its top-level imports (langchain.agents.create_agent and
langchain_mcp_adapters) without constructing an LLM or contacting any provider — the
settings singleton is only read inside functions, not at import time.

mcp_server.app and execution.worker are added here in docs/phase-1.1 Unit B, now that
those modules exist. execution.worker reads settings at import to build its Celery app,
so the baseline-env fixture in conftest.py supplies a valid environment.
"""

from __future__ import annotations

import importlib

import pytest

_SCAFFOLDING_MODULES = [
    "config",
    "config.settings",
    "agent.prompts",
    "agent.agent",
    "mcp_server.app",
    "execution.worker",
]


@pytest.mark.parametrize("module_name", _SCAFFOLDING_MODULES)
def test_module_imports_cleanly(module_name: str) -> None:
    """Each scaffolding module imports without raising."""
    importlib.import_module(module_name)
