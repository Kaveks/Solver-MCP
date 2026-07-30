"""
mcp_server/app.py — FastAPI application for the Solver-MCP MCP Connector (Layer 2).

This is the entry point Uvicorn/Gunicorn starts:

    uvicorn mcp_server.app:app --host 0.0.0.0 --port 8000

Scope note: this mounts the FastMCP server at /mcp, includes the health, job-status, and
Engineering Simulations API routes, configures structured logging + tracing at startup, and
binds a correlation ID per request. Still to come in later, sequenced scopes:

- static X-API-Key authentication middleware  -> docs/phase-1.2 Unit 2 / Phase 4 auth

Importing this module stays side-effect-free with respect to settings: logging/tracing are
configured at startup (the lifespan), not at construction.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from config import get_settings
from mcp_server.routes.health import router as health_router
from mcp_server.routes.jobs import router as jobs_router
from mcp_server.routes.simulations import router as simulations_router
from mcp_server.routes.ui import router as ui_router
from mcp_server.server import mcp
from observability import configure_logging, init_tracing, set_correlation_id


def create_app() -> FastAPI:
    """Build and return the FastAPI application.

    Side-effect-free with respect to settings: no configuration is read at construction
    time. Logging and tracing are configured in the lifespan startup, alongside the FastMCP
    session manager (whose own lifespan is chained in).
    """
    mcp_app = mcp.http_app(path="/")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        init_tracing()
        async with mcp_app.lifespan(app):
            yield

    app = FastAPI(
        title="Solver-MCP MCP Connector",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        header = get_settings().CORRELATION_ID_HEADER
        # Reuse an inbound correlation ID if the caller supplied one, else mint a new one.
        correlation_id = request.headers.get(header) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        set_correlation_id(correlation_id)  # bind into the logging context
        response = await call_next(request)
        response.headers[header] = correlation_id
        return response

    app.include_router(health_router)
    app.include_router(jobs_router)
    app.include_router(simulations_router)
    app.include_router(ui_router)

    # Static files (UI assets: /static/app.js). Created on import so the mount
    # never fails on a fresh checkout that has no built assets yet.
    STATIC_DIR = Path(__file__).parent / "static"
    STATIC_DIR.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.mount("/mcp", mcp_app)
    return app


app = create_app()
