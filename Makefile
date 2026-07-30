# Makefile — Solver-MCP MCP Connector
#
# All commands run from the project root.
# Prerequisites: Docker, Docker Compose, Python 3.11+
#
# Usage examples
# ──────────────────────────────────────────────────────────────────────
#   make up            Start the full Prototype stack
#   make down          Stop and remove containers
#   make logs          Tail logs from all services
#   make test          Run the full test suite
#   make lint          Run linter and type checker
#   make smoke         Verify LLM provider config is working
#
# Run `make help` to see all available targets.

.DEFAULT_GOAL := help
SHELL         := /bin/bash

# ── Project config ────────────────────────────────────────────────────
PROJECT       := Solver-MCP
COMPOSE_FILE  := docker-compose.yml
PYTHON        := python3
PIP           := pip3

# Colours for help output
BOLD  := \033[1m
RESET := \033[0m
CYAN  := \033[36m

# ════════════════════════════════════════════════════════════════════════
# Help
# ════════════════════════════════════════════════════════════════════════

.PHONY: help
help: ## Show this help message
	@echo ""
	@echo "$(BOLD)Solver-MCP MCP Connector — available targets$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ════════════════════════════════════════════════════════════════════════
# Environment
# ════════════════════════════════════════════════════════════════════════

.PHONY: env
env: ## Copy .env.example to .env if .env does not exist
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example — fill in your values before running."; \
	else \
		echo ".env already exists — skipping."; \
	fi

# ════════════════════════════════════════════════════════════════════════
# Docker — build
# ════════════════════════════════════════════════════════════════════════

.PHONY: build
build: ## Build all Docker images
	docker compose -f $(COMPOSE_FILE) build

.PHONY: build-mcp
build-mcp: ## Build only the Solver-MCP-mcp image
	docker compose -f $(COMPOSE_FILE) build Solver-MCP-mcp

.PHONY: build-worker
build-worker: ## Build only the Solver-MCP-worker image
	docker compose -f $(COMPOSE_FILE) build Solver-MCP-worker

.PHONY: build-openfoam
build-openfoam: ## Build only the openfoam-svc image
	docker compose -f $(COMPOSE_FILE) build openfoam-svc

.PHONY: build-lammps
build-lammps: ## Build only the lammps-svc image
	docker compose -f $(COMPOSE_FILE) build lammps-svc

.PHONY: build-freecad
build-freecad: ## Build only the freecad-svc image
	docker compose -f $(COMPOSE_FILE) build freecad-svc

.PHONY: build-no-cache
build-no-cache: ## Rebuild all images from scratch (no layer cache)
	docker compose -f $(COMPOSE_FILE) build --no-cache

# ════════════════════════════════════════════════════════════════════════
# Docker — stack lifecycle
# ════════════════════════════════════════════════════════════════════════

.PHONY: up
up: ## Start the full Prototype stack (detached)
	docker compose -f $(COMPOSE_FILE) up -d
	@echo ""
	@echo "Stack is up. MCP server: http://localhost:$${PORT:-8000}"
	@echo "Run 'make logs' to follow output."

.PHONY: up-build
up-build: ## Build images then start the full stack
	docker compose -f $(COMPOSE_FILE) up -d --build

.PHONY: seed-openfoam-mesh
seed-openfoam-mesh: ## Force a re-seed of the OpenFOAM polyMesh on /work (normally automatic on `up`)
	# Seeding now happens automatically: openfoam-svc's startup script provisions
	# /work/mesh on every boot when the mesh is missing. This target only forces a
	# re-seed by wiping the mesh and restarting the service, reusing that same path
	# (one source of truth — see shell-scripts/seed-openfoam-work.sh).
	docker compose -f $(COMPOSE_FILE) exec -T openfoam-svc rm -rf /work/mesh
	docker compose -f $(COMPOSE_FILE) restart openfoam-svc
	@echo ""
	@echo "openfoam-svc restarted; it re-provisions /work/mesh/constant/polyMesh on startup."
	@echo "Check progress with: make logs-openfoam"

.PHONY: down
down: ## Stop and remove containers (keeps volumes)
	docker compose -f $(COMPOSE_FILE) down

.PHONY: down-clean
down-clean: ## Stop containers and remove volumes and orphan containers
	docker compose -f $(COMPOSE_FILE) down --volumes --remove-orphans

.PHONY: restart
restart: ## Restart all services
	docker compose -f $(COMPOSE_FILE) restart

.PHONY: restart-mcp
restart-mcp: ## Restart only the MCP server container
	docker compose -f $(COMPOSE_FILE) restart Solver-MCP-mcp

.PHONY: restart-worker
restart-worker: ## Restart only the Celery worker container
	docker compose -f $(COMPOSE_FILE) restart Solver-MCP-worker

# ════════════════════════════════════════════════════════════════════════
# Docker — logs and status
# ════════════════════════════════════════════════════════════════════════

.PHONY: logs
logs: ## Tail logs from all running services
	docker compose -f $(COMPOSE_FILE) logs -f

.PHONY: logs-mcp
logs-mcp: ## Tail logs from the MCP server only
	docker compose -f $(COMPOSE_FILE) logs -f Solver-MCP-server

.PHONY: logs-worker
logs-worker: ## Tail logs from the Celery worker only
	docker compose -f $(COMPOSE_FILE) logs -f Solver-MCP-worker

.PHONY: logs-redis
logs-redis: ## Tail logs from Redis only
	docker compose -f $(COMPOSE_FILE) logs -f redis-svc

.PHONY: logs-openfoam
logs-openfoam: ## Tail logs from the OpenFOAM solver only
	docker compose -f $(COMPOSE_FILE) logs -f openfoam-svc

.PHONY: logs-lammps
logs-lammps: ## Tail logs from the LAMMPS solver only
	docker compose -f $(COMPOSE_FILE) logs -f lammps-svc

.PHONY: logs-freecad
logs-freecad: ## Tail logs from the FreeCAD solver only
	docker compose -f $(COMPOSE_FILE) logs -f freecad-svc

.PHONY: ps
ps: ## Show running container status
	docker compose -f $(COMPOSE_FILE) ps

.PHONY: artifacts
artifacts: ## List all artifact files stored in the artifacts volume
	@echo "Artifact volume contents:"
	@docker compose exec Solver-MCP-worker find /artifacts -type f | sort
	@echo ""
	@echo "Artifacts are grouped by solver: /artifacts/<solver>/<job_id>/..."
	@echo "To inspect a specific job artifact (use any path from the list above):"
	@echo "  docker compose exec Solver-MCP-worker cat /artifacts/<solver>/<job_id>/<file>"
	@echo "    LAMMPS   key files: lammps/<job_id>/in.lammps, lammps/<job_id>/log.lammps"
	@echo "    OpenFOAM key files: openfoam/<job_id>/system/controlDict, openfoam/<job_id>/<lastTime>/U"
	@echo "  docker volume inspect solver-mcp_artifacts"

.PHONY: volumes
volumes: ## Inspect the work and artifacts Docker volume mounts
	@echo "Work volume:"
	@docker volume inspect solver-mcp_work
	@echo ""
	@echo "Artifacts volume:"
	@docker volume inspect solver-mcp_artifacts

# ════════════════════════════════════════════════════════════════════════
# Docker — shell access
# ════════════════════════════════════════════════════════════════════════

.PHONY: shell-mcp
shell-mcp: ## Open a shell inside the running MCP server container
	docker compose -f $(COMPOSE_FILE) exec Solver-MCP-mcp /bin/bash

.PHONY: shell-worker
shell-worker: ## Open a shell inside the running worker container
	docker compose -f $(COMPOSE_FILE) exec Solver-MCP-worker /bin/bash

.PHONY: shell-redis
shell-redis: ## Open the Redis CLI inside the running Redis container
	docker compose -f $(COMPOSE_FILE) exec redis-svc redis-cli

# ════════════════════════════════════════════════════════════════════════
# Testing
# ════════════════════════════════════════════════════════════════════════

.PHONY: test
test: ## Run the full test suite (unit + integration)
	$(PYTHON) -m pytest tests/ -v

.PHONY: test-unit
test-unit: ## Run unit tests only (no containers required)
	$(PYTHON) -m pytest tests/unit/ -v

.PHONY: test-integration
test-integration: ## Run integration tests (requires Docker Compose stack to be up)
	$(PYTHON) -m pytest tests/integration/ -v

.PHONY: test-regression
test-regression: ## Run regression tests (requires Docker Compose stack to be up)
	$(PYTHON) -m pytest tests/regression/ -v

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	$(PYTHON) -m pytest tests/unit/ --cov=. --cov-report=term-missing --cov-report=html

# ════════════════════════════════════════════════════════════════════════
# Code quality
# ════════════════════════════════════════════════════════════════════════

.PHONY: lint
lint: ## Run ruff linter and mypy type checker
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy . --ignore-missing-imports

.PHONY: format
format: ## Auto-format code with ruff
	$(PYTHON) -m ruff format .

.PHONY: format-check
format-check: ## Check formatting without making changes
	$(PYTHON) -m ruff format --check .

# ════════════════════════════════════════════════════════════════════════
# Development
# ════════════════════════════════════════════════════════════════════════

.PHONY: install
install: ## Install Python dependencies from pyproject.toml
	$(PIP) install -e ".[dev]"

.PHONY: smoke
smoke: ## Verify LLM provider config is working (no containers needed)
	$(PYTHON) -m agent.agent

.PHONY: chat
chat: ## Interactive prompt: type a request, watch the full sim flow (needs the stack up + MCP_TRANSPORT=http)
	$(PYTHON) -m agent.chat

.PHONY: health
health: ## Check the health endpoint of the running MCP server
	curl -s http://localhost:$${PORT:-8000}/health | python3 -m json.tool

.PHONY: ready
ready: ## Check the readiness endpoint (verifies Redis connection)
	curl -s http://localhost:$${PORT:-8000}/health/ready | python3 -m json.tool

.PHONY: tools
tools: ## List MCP tools registered on the running server
	docker compose exec Solver-MCP-mcp python -c "import asyncio; from mcp_server.server import mcp; print(chr(10).join(sorted(t.name for t in asyncio.run(mcp.list_tools()))))"

.PHONY: ui
ui: ## Open the Solver-MCP web UI at http://localhost:8000
	@python3 -m webbrowser http://localhost:8000 2>/dev/null || \
	 echo "Open http://localhost:8000 in your browser"

# ════════════════════════════════════════════════════════════════════════
# Cleanup
# ════════════════════════════════════════════════════════════════════════

.PHONY: clean
clean: ## Remove Python cache files and test artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name ".coverage" -delete
	@echo "Clean complete."

.PHONY: clean-docker
clean-docker: ## Remove stopped containers and dangling images for this project
	docker compose -f $(COMPOSE_FILE) down --remove-orphans
	docker image prune -f --filter "label=project=$(PROJECT)"
	@echo "Docker clean complete."

# ════════════════════════════════════════════════════════════════════════
# CI/CD
# ════════════════════════════════════════════════════════════════════════

.PHONY: ci-check
ci-check: ## Run the same checks GitHub Actions runs before you push
	@echo "Running unit tests..."
	$(PYTHON) -m pytest tests/unit/ -v --tb=short
	@echo ""
	@echo "Running linter..."
	$(PYTHON) -m ruff check .
	@echo ""
	@echo "Checking formatting..."
	$(PYTHON) -m ruff format --check .
	@echo ""
	@echo "All CI checks passed. Safe to push."

.PHONY: image-tag
image-tag: ## Print the image tag that CI would use for the current commit
	@git rev-parse --short HEAD