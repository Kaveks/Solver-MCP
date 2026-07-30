#!/usr/bin/env bash
# shell-scripts/run-fastapi-server.sh
#
# Start the Solver-MCP MCP server using Gunicorn with Uvicorn workers.
#
# Gunicorn manages 3 Uvicorn worker processes. Each worker handles requests
# independently. Gunicorn handles worker lifecycle: spawning, monitoring,
# and restarting workers that crash.
#
# This script is called by entrypoint.sh inside the Solver-MCP-mcp container.
# It is not intended to be run directly in development outside Docker.
#
# Environment variables (all read from config/settings.py via the app)
# ─────────────────────────────────────────────────────────────────────
#   HOST          Bind address. Default: 0.0.0.0
#   PORT          Bind port.    Default: 8000
#   LOG_LEVEL     Gunicorn/Uvicorn log level. Default: info
#
# Worker count
# ─────────────────────────────────────────────────────────────────────
# Fixed at 3. This is the right number for a single container handling
# concurrent MCP tool calls and HTTP job status polls. Each worker is
# an async Uvicorn process — it handles many concurrent requests within
# itself via asyncio. Three workers gives concurrency without the memory
# overhead of more workers sharing the same container resources.
#
# Do not increase beyond 3 in the Prototype (single machine, limited RAM).
# In Production, horizontal pod scaling handles throughput — keep workers
# at 3 per pod and scale pods instead.

set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
LOG_LEVEL="${LOG_LEVEL:-info}"
WORKERS="${GUNICORN_WORKERS:-3}"

echo "[run-fastapi-server] Starting Gunicorn with ${WORKERS} Uvicorn workers"
echo "[run-fastapi-server] Binding: ${HOST}:${PORT}"
echo "[run-fastapi-server] Log level: ${LOG_LEVEL}"

# MCP streamable-HTTP transport uses per-process session state.
# With multiple workers and no session affinity, sessions created in one
# worker 404 on the next. Set GUNICORN_WORKERS=1 if using the HTTP
# transport without sticky sessions (Production path).
# Prototype uses stdio transport — the default of 3 workers is correct there.
exec gunicorn mcp_server.app:app \
    --bind "${HOST}:${PORT}" \
    --workers "${WORKERS}" \
    --worker-class uvicorn.workers.UvicornWorker \
    --log-level "${LOG_LEVEL}" \
    --access-logfile - \
    --error-logfile - \
    --timeout 120 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --forwarded-allow-ips "*"