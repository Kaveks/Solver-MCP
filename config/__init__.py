"""
config — central configuration package for the Solver-MCP MCP Connector.

Public API
----------
    from config import get_settings

    settings = get_settings()

`get_settings()` returns a cached singleton built and validated from the environment
(and the .env file). No module outside this package reads os.environ directly.

The constrained-choice enums are re-exported here so other modules can compare against
them without importing from config.settings directly:

    from config import LLMProvider, MCPTransport
"""

from config.settings import (
    ArtifactStoreType,
    LLMProvider,
    LogFormat,
    LogLevel,
    MCPTransport,
    RunnerBackend,
    Settings,
    get_settings,
)

__all__ = [
    "get_settings",
    "Settings",
    "LLMProvider",
    "MCPTransport",
    "ArtifactStoreType",
    "RunnerBackend",
    "LogLevel",
    "LogFormat",
]
