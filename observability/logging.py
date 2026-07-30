"""
observability/logging.py — structured logging with a correlation ID (Step 3.2).

A single correlation ID is generated at the MCP request boundary and bound here via a
contextvar, so every log record emitted while handling that request carries the same ID —
making one simulation greppable across Layers 2-4. Output format and level follow settings
(LOG_FORMAT, LOG_LEVEL); JSON for aggregators, text for local development.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

from config import get_settings
from config.settings import LogFormat

# The current request's correlation ID. Each async request runs in its own context, so this
# is naturally request-scoped without locking.
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Standard LogRecord attributes — anything else on a record is treated as structured extra.
_STD_ATTRS = set(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
) | {"message", "asctime", "taskName"}


def set_correlation_id(correlation_id: str | None) -> None:
    _correlation_id.set(correlation_id)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


class JsonFormatter(logging.Formatter):
    """Render each record as a single JSON line including the correlation ID and extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "function": record.funcName,
            "message": record.getMessage(),
            "correlation_id": _correlation_id.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable single line including the correlation ID."""

    def format(self, record: logging.LogRecord) -> str:
        cid = _correlation_id.get() or "-"
        return f"{record.levelname:<7} {record.name} [{cid}] {record.getMessage()}"


# Third-party loggers whose INFO chatter (per-request transport/session/tool-list lines and
# HTTP access logs) drowns the domain trace. Pinned to WARNING so a single simulation reads
# as a few precise lines; their warnings/errors still surface.
_NOISY_LOGGERS = (
    "mcp.server.streamable_http_manager",
    "mcp.server.streamable_http",
    "mcp.server.lowlevel.server",
    # Client side: the agent opens a fresh MCP session per tool call, each emitting
    # "Received session ID" / "Negotiated protocol version" — pure transport noise.
    "mcp.client.streamable_http",
    "mcp.client.session",
    "uvicorn.access",
)


class _DropMcpTransportFilter(logging.Filter):
    """Suppress httpx access lines for the internal MCP transport (the …/mcp/ endpoint).

    httpx logs one line per HTTP round-trip, and the agent makes several round-trips to the
    local MCP server per tool call — so a single simulation emits a dozen-plus identical
    /mcp/ lines. They are dropped here, while outbound calls (notably the Anthropic API at
    api.anthropic.com) do not match the path and stay visible — httpx is the same logger for
    both, so a blanket level change would lose the LLM calls too. Net effect: the trace keeps
    the cache decision, the agent-bind line, and the real LLM calls; MCP plumbing is hidden.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "/mcp/" not in record.getMessage()


def configure_logging() -> None:
    """Configure the root logger's handler/level/format from settings. Idempotent."""
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    if settings.LOG_FORMAT == LogFormat.JSON:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.value)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Keep httpx at its inherited level (so the Anthropic call stays) but filter out the
    # internal MCP round-trips. Guard against stacking filters on idempotent re-config.
    httpx_logger = logging.getLogger("httpx")
    if not any(isinstance(f, _DropMcpTransportFilter) for f in httpx_logger.filters):
        httpx_logger.addFilter(_DropMcpTransportFilter())


def get_logger(name: str) -> logging.Logger:
    """Return a logger; records carry the current correlation ID via the configured handler."""
    return logging.getLogger(name)
