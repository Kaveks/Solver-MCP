# =============================================================================
# docker/mcp_server/Dockerfile — Solver-MCP-mcp image (Layer 2)
#
# FastMCP server + FastAPI HTTP API. Runs Gunicorn with Uvicorn workers via the
# shell scripts in shell-scripts/. Non-root user; waits for Redis on startup.
# =============================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /usr/src/Solver-MCP

# netcat-openbsd: used by entrypoint.sh to wait for Redis (nc -z).
RUN apt-get update \
    && apt-get install -y --no-install-recommends netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first so the layer caches across code-only changes.
# Web UI deps (jinja2, aiofiles, python-multipart) are pinned in requirements.txt
# and installed here; the templates/ and static/ assets ship via the COPY . . below.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Non-root user; ensure shell scripts are executable and the app is owned by it.
RUN useradd --create-home --uid 1000 appuser \
    && chmod +x shell-scripts/*.sh \
    && chown -R appuser:appuser /usr/src/Solver-MCP
USER appuser

EXPOSE 8000

# entrypoint waits for Redis, then execs the CMD (the Gunicorn launcher).
ENTRYPOINT ["shell-scripts/entrypoint.sh"]
CMD ["shell-scripts/run-fastapi-server.sh"]
