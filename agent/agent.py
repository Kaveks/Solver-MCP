"""
agent/agent.py — LLM-agnostic agent builder for Solver-MCP MCP Connector

This module builds the LangChain agent that drives Solver-MCP simulations.
The LLM is selected at runtime from settings.LLM_PROVIDER. No LLM is hardcoded.
Adding a new provider means adding one entry to _PROVIDER_MAP — nothing else changes.

All configuration is read from config.get_settings(), never from os.environ directly.

Supported providers
-------------------
  openai      GPT-4o via OpenAI API         LLM_PROVIDER=openai
  anthropic   Claude (any model) via API    LLM_PROVIDER=anthropic
  azure       Azure OpenAI deployment       LLM_PROVIDER=azure
  ollama        Any local Ollama model      LLM_PROVIDER=ollama
  google_genai  Google Gemini via API       LLM_PROVIDER=google_genai

Usage
-----
    from agent.agent import build_agent

    agent = await build_agent()
    result = await agent.ainvoke(
        {"messages": [("user", "Run a pipe flow simulation...")]}
    )

build_agent() is async because the MCP client discovers tools over an async transport.

Smoke test (run from project root):

    python -m agent.agent

The smoke test only exercises build_llm() — it sends one short message to the configured
provider to confirm the API key is valid and the provider is reachable. It does not start
the MCP server or build the agent.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_mcp_adapters.client import MultiServerMCPClient

from agent.prompts import SYSTEM_PROMPT, solver_directive
from config import get_settings
from config.settings import LLMProvider, MCPTransport

logger = logging.getLogger(__name__)

# The single simulation tool each solver exposes. When the web UI binds a solver, the
# agent is given only that solver's run tool plus get_job_status, so it is structurally
# incapable of dispatching a different solver — routing becomes deterministic.
_RUN_TOOL_BY_SOLVER = {
    "openfoam": "run_cfd_simulation",
    "lammps": "run_md_simulation",
    "freecad": "run_fem_simulation",
}
_POLL_TOOL = "get_job_status"


# ---------------------------------------------------------------------------
# LLM builders — one function per provider
#
# Each takes the settings singleton and returns a configured BaseChatModel.
# Provider packages are imported lazily inside each builder so that importing
# this module never requires every provider SDK to be installed — only the one
# matching the active LLM_PROVIDER is needed at runtime.
# ---------------------------------------------------------------------------

def _build_openai(s: Any) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=s.OPENAI_MODEL,
        api_key=s.OPENAI_API_KEY,
        temperature=0,
    )


def _build_anthropic(s: Any) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=s.ANTHROPIC_MODEL,
        api_key=s.ANTHROPIC_API_KEY,
        temperature=0.2,
        max_tokens=8192,
    )


def _build_azure(s: Any) -> BaseChatModel:
    from langchain_openai import AzureChatOpenAI

    return AzureChatOpenAI(
        azure_deployment=s.AZURE_OPENAI_DEPLOYMENT,
        azure_endpoint=s.AZURE_OPENAI_ENDPOINT,
        api_key=s.AZURE_OPENAI_API_KEY,
        api_version=s.AZURE_OPENAI_API_VERSION,
        temperature=0,
    )


def _build_ollama(s: Any) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=s.OLLAMA_MODEL,
        base_url=s.OLLAMA_BASE_URL,
        temperature=0,
    )


def _build_google_genai(s: Any) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=s.GEMINI_MODEL,
        google_api_key=s.GOOGLE_API_KEY,
        temperature=0,
    )


_PROVIDER_MAP: dict[LLMProvider, Any] = {
    LLMProvider.OPENAI: _build_openai,
    LLMProvider.ANTHROPIC: _build_anthropic,
    LLMProvider.AZURE: _build_azure,
    LLMProvider.OLLAMA: _build_ollama,
    LLMProvider.GOOGLE_GENAI: _build_google_genai,
}


def build_llm() -> BaseChatModel:
    """
    Build and return a LangChain chat model from the application settings.

    Validation of required credentials is handled by Settings at startup.
    This function will not be reached if credentials for the active provider are missing.
    """
    s = get_settings()
    logger.info("Using LLM provider: %s", s.LLM_PROVIDER)
    return _PROVIDER_MAP[s.LLM_PROVIDER](s)


# ---------------------------------------------------------------------------
# MCP client builder
# ---------------------------------------------------------------------------

def _build_mcp_client() -> MultiServerMCPClient:
    """
    Build the MCP client based on the configured transport.

    stdio  — Prototype: launches the MCP server as a local subprocess.
    http   — Production: connects to the running MCP server over streamable HTTP at /mcp/.
    """
    s = get_settings()

    if s.MCP_TRANSPORT == MCPTransport.STDIO:
        return MultiServerMCPClient(
            {
                "Solver-MCP": {
                    "command": "python",
                    "args": ["-m", "mcp_server.server"],
                    "transport": "stdio",
                }
            }
        )

    # Streamable HTTP transport (Production). The server mounts FastMCP via
    # mcp.http_app() at /mcp, which speaks streamable HTTP (not SSE), so the
    # client connects to /mcp/ with transport "streamable_http".
    headers = {}
    if s.MCP_API_KEY is not None:
        headers["X-API-Key"] = s.MCP_API_KEY.get_secret_value()

    return MultiServerMCPClient(
        {
            "Solver-MCP": {
                "url": f"{s.MCP_SERVER_URL}/mcp/",
                "transport": "streamable_http",
                "headers": headers,
            }
        }
    )


# ---------------------------------------------------------------------------
# Agent builder
# ---------------------------------------------------------------------------

async def build_agent(allowed_solver: str | None = None) -> Any:
    """
    Build and return a LangChain agent wired to the Solver-MCP MCP server.

    The LLM and MCP transport are determined by application settings. Tools are
    discovered from the MCP server over its async transport, so this function is async.

    If ``allowed_solver`` is one of the registered solver names (openfoam | lammps |
    freecad), the agent is restricted to that solver's run tool plus get_job_status and
    given a directive forbidding any other solver — the web UI uses this so the solver the
    engineer picked is the only one that can run. With ``allowed_solver`` left None (the
    CLI harness, agent/chat.py) the agent keeps every tool and chooses for itself.

    Returns a compiled LangGraph agent. Invoke it with a message list:

        result = await agent.ainvoke({"messages": [("user", "...")]})
    """
    llm = build_llm()
    mcp_client = _build_mcp_client()
    tools = await mcp_client.get_tools()

    if not tools:
        logger.warning(
            "No tools returned from the MCP server. "
            "Check that the MCP server is running and reachable."
        )

    system_prompt = SYSTEM_PROMPT
    run_tool = _RUN_TOOL_BY_SOLVER.get(allowed_solver) if allowed_solver else None
    if run_tool:
        allowed = {run_tool, _POLL_TOOL}
        restricted = [t for t in tools if getattr(t, "name", None) in allowed]
        # Only narrow the toolset if the run tool was actually discovered; otherwise keep
        # the full set so a discovery hiccup degrades to non-deterministic rather than to
        # an agent with no simulation tool at all.
        if any(getattr(t, "name", None) == run_tool for t in restricted):
            tools = restricted
            system_prompt = SYSTEM_PROMPT + solver_directive(allowed_solver)
            logger.info("agent restricted to solver %r (tools: %s)", allowed_solver,
                        [getattr(t, "name", "?") for t in tools])
        else:
            logger.warning("solver %r selected but %r not discovered; keeping all tools",
                           allowed_solver, run_tool)

    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s"
    )

    s = get_settings()
    print("\nSolver-MCP — LLM provider smoke test")
    print("=" * 44)
    print(f"LLM_PROVIDER : {s.LLM_PROVIDER}")
    print(f"MCP_TRANSPORT: {s.MCP_TRANSPORT}")
    print()

    try:
        llm = build_llm()
        print(f"LLM built: {llm.__class__.__name__}")
        response = llm.invoke("Reply with the single word: ready")
        print(f"LLM response: {response.content.strip()}")
        print("\nSmoke test passed.")
    except Exception as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
