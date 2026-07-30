# =============================================================================
# docker/worker/Dockerfile — Solver-MCP-worker image (Layer 3)
#
# Celery worker. Shares the same codebase as the MCP image but runs the Celery
# process instead of the web server. Mounts the /work and /artifacts volumes at
# runtime (see docker-compose.yml). Non-root user; waits for Redis on startup.
# =============================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# netcat-openbsd: entrypoint.sh waits for Redis before starting Celery.
RUN apt-get update \
    && apt-get install -y --no-install-recommends netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Non-root user; create the volume mount points and hand ownership to it.
RUN useradd --create-home --uid 1000 appuser \
    && chmod +x shell-scripts/*.sh \
    && mkdir -p /work /artifacts \
    && chown -R appuser:appuser /app /work /artifacts
USER appuser

# entrypoint waits for Redis, then execs the Celery worker.
# concurrency=1 matches the Prototype "one worker per solver" constraint.
ENTRYPOINT ["shell-scripts/entrypoint.sh"]
CMD ["celery", "-A", "execution.worker:celery_app", "worker", "--loglevel=INFO", "--concurrency=1"]
