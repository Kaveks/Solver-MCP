#!/usr/bin/env bash
# shell-scripts/entrypoint.sh
#
# Docker ENTRYPOINT for the Solver-MCP-mcp container.
#
# Responsibilities
# ─────────────────────────────────────────────────────────────────────
# 1. Ensure every shell script in shell-scripts/ is executable.
#    This guards against scripts losing their execute bit during a
#    Docker COPY (which can happen depending on the host OS and umask).
#
# 2. Wait for Redis to be reachable before starting the server.
#    The MCP server cannot function without Redis (job queue and cache).
#    Failing fast here gives a clear error rather than a silent crash
#    mid-request.
#
# 3. Delegate to the command passed as arguments ($@).
#    The Dockerfile CMD sets this to run-fastapi-server.sh.
#    This keeps the entrypoint generic — the same entrypoint works for
#    any command passed to docker run or docker-compose.
#
# Usage (set in Dockerfile)
# ─────────────────────────────────────────────────────────────────────
#   ENTRYPOINT ["shell-scripts/entrypoint.sh"]
#   CMD ["shell-scripts/run-fastapi-server.sh"]
#
# Environment variables
# ─────────────────────────────────────────────────────────────────────
#   REDIS_URL         Full Redis URL. Parsed to extract host and port.
#                     Default: redis://redis-svc:6379/0
#   REDIS_WAIT_SECS   Max seconds to wait for Redis. Default: 30

set -euo pipefail

REDIS_URL="${REDIS_URL:-redis://redis-svc:6379/0}"
REDIS_WAIT_SECS="${REDIS_WAIT_SECS:-30}"

# ── Step 1: Ensure all shell scripts are executable ──────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[entrypoint] Setting execute permissions on ${SCRIPT_DIR}/*.sh"
chmod +x "${SCRIPT_DIR}"/*.sh
echo "[entrypoint] Permissions set."

# ── Step 2: Wait for Redis ───────────────────────────────────────────

# Parse host and port from REDIS_URL
# Handles: redis://host:port/db  and  redis://host/db (default port 6379)
REDIS_HOST=$(echo "${REDIS_URL}" | sed -E 's|redis://([^:/]+).*|\1|')
REDIS_PORT=$(echo "${REDIS_URL}" | sed -E 's|redis://[^:]+:([0-9]+).*|\1|')

# If no port in URL the sed above returns the full URL (no match), default to 6379
if [ "${REDIS_PORT}" = "${REDIS_URL}" ]; then
    REDIS_PORT="6379"
fi

echo "[entrypoint] Waiting for Redis at ${REDIS_HOST}:${REDIS_PORT} (max ${REDIS_WAIT_SECS}s)"

elapsed=0
until nc -z "${REDIS_HOST}" "${REDIS_PORT}" 2>/dev/null; do
    if [ "${elapsed}" -ge "${REDIS_WAIT_SECS}" ]; then
        echo "[entrypoint] ERROR: Redis not reachable after ${REDIS_WAIT_SECS}s. Exiting."
        exit 1
    fi
    echo "[entrypoint] Redis not ready yet — retrying in 2s (${elapsed}s elapsed)"
    sleep 2
    elapsed=$((elapsed + 2))
done

echo "[entrypoint] Redis is reachable."

# ── Step 3: Exec the command ─────────────────────────────────────────

echo "[entrypoint] Executing: $*"
exec "$@"