# CLAUDE.md — Solver-MCP MCP Connector

## Project identity

This is the Solver-MCP MCP Connector project, built for AM Simulation (AMS) as part of the
B Global Talent (BGT) 4th Edition 2026 programme challenge. The Software Requirements and
Technical Design Specification (SRS/TDS v1.0.0) is the authoritative reference for all
architecture and development decisions.

AMS has an existing web-based Solver-MCP platform called Solver-MCP. It is built on
GPT-4o and LangChain. Engineers submit natural language prompts and the agent handles
geometry, meshing, model setup, solver execution, and result display. CalculiX is already
connected to Solver-MCP via MCP and is confirmed done. This project extends Solver-MCP by
adding three new MCP connectors: OpenFOAM, LAMMPS, and FreeCAD.

---

## Session and development workflow

This section governs how every development session runs. These rules apply without
exception. They exist to keep the developer in control of every decision and every line of
code that enters the project.

### Core principle

Nothing is written to the codebase without explicit developer approval. The agent proposes.
The developer reviews. The developer approves or rejects. Only then does the agent proceed.
This applies to plans, file structures, code, configuration, tests, and Dockerfiles equally.

### Session startup protocol

At the start of every session, before any work begins, the agent must:

1. State the current phase from the implementation plan (Phase 1, 2, 3, or 4).
2. State the last completed step within that phase, based on what the developer confirms.
3. State the single next step to be worked on in this session.
4. Ask the developer to confirm this is correct before proceeding.

The agent must not assume where the project left off. The developer confirms the starting
point at the beginning of every session. If the developer does not confirm, the agent asks
again before doing anything.

Example session opening:

"We are in Phase 1. Based on what you have told me, the last completed step was
setting up Docker Compose and verifying all containers start cleanly. The next
step is implementing the OpenFOAMInput Pydantic schema. Shall I proceed with
that, or is there something else you want to address first?"

### Build planning protocol

Every module, file, or meaningful unit of work follows this four-step sequence before any
code is written:

**Step 1 — Plan presentation**
The agent presents a written plan for the next unit of work. The plan states:

- What will be built (file name, module name, function signatures at a high level)
- Why each decision was made (referencing the SRS or architecture rules)
- What the inputs and outputs are
- What tests will be written alongside it
- Any assumption being made that is not confirmed in the SRS

The plan is presented in plain text, not as code. No implementation begins until the plan
is approved.

**Step 2 — Developer review**
The developer reads the plan and either:

- Approves it as written
- Requests changes to the plan
- Rejects it and provides direction

The agent must not interpret silence as approval. If the developer does not explicitly
approve, the agent waits.

**Step 3 — Implementation**
Only after explicit approval does the agent write code. The agent writes one logical unit
at a time: one file, one class, or one clearly bounded function group. It does not write the
entire phase in one pass.

**Step 4 — Review before surfacing**
After writing the code, the agent presents it for review before considering it done. The
agent summarises what was written, highlights any decision that deviated from the plan,
and asks for approval before moving to the next step.

If the developer requests changes at this stage, the agent revises and re-presents. It does
not proceed to the next step until the current unit is explicitly approved.

### Sequential development rule

Development is strictly sequential. The phases are:

Phase 1 > Phase 2 > Phase 3 > Phase 4

Within each phase, steps are completed in the order listed in the implementation plan.
The agent must not work on Phase 2 items while Phase 1 is incomplete. The agent must not
skip a step because it seems minor. If a step is already done, the agent confirms this with
the developer and moves to the next step in sequence.

The agent must not work on multiple steps in parallel in a single session unless the
developer explicitly instructs this.

### Checkpoint at phase boundaries

When a phase is complete, the agent does not automatically begin the next phase. It stops,
reports the completed phase to the developer, and lists what was built. The developer
decides when to begin the next phase and confirms the starting point.

### Mid-session pausing

If the developer says stop, pause, or that is enough for now at any point, the agent:

1. Stops immediately after finishing the current sentence or the current file, whichever
   comes first.
2. Reports the exact step that was completed last.
3. Reports what the next step would be if the session were to continue.
4. Does not start any new work.

This ensures the next session can resume from a known, confirmed state.

### Handling uncertainty during implementation

If the agent encounters an ambiguity, a gap in the SRS, or a decision point not covered
by this CLAUDE.md, it must stop and surface this to the developer before proceeding. The
agent must not resolve ambiguity by making a silent assumption. It must state:

- What the ambiguity is
- What the two or more possible approaches are
- Which approach it recommends and why
- Then wait for the developer's decision

---

## What you are building

You are implementing an MCP server that exposes OpenFOAM, LAMMPS, and FreeCAD as
structured, callable tools to the Solver-MCP AI agent. The agent layer (GPT-4o + LangChain)
is AMS's property and is not modified by this project. Your work lives entirely in Layers 2, 3,
and 4 of the architecture defined in the SRS.

**Layer 2** — MCP Server (primary deliverable): FastMCP server, tool router, Pydantic schema
validation, SolverInterface abstract base class.

**Layer 3** — Execution Layer: Celery worker, Redis broker and artifact cache, SHA-256
simulation caching, artifact store (local volume in Prototype, S3 in Production).

**Layer 4** — Solver Microservices: openfoam-svc, lammps-svc, freecad-svc. Each runs as an
isolated Docker container with no network access and a non-root user.

---

## Delivery tracks

There are two tracks. They share the same codebase. The difference is infrastructure only.

**Prototype (Track 1)**

- Deployment: Docker Compose on a single local machine
- LLM: OpenAI API key (GPT-4o), set in .env
- OpenFOAM: simpleFoam only, single worker
- LAMMPS: CLI subprocess, NVT ensemble, basic potentials
- FreeCAD: stubbed connector (returns structured NOT_IMPLEMENTED)
- Authentication: static API key in environment variable
- Storage: local Docker volume
- Scaling: one worker per solver

**Production (Track 2)**

- Deployment: Kubernetes with HPA on Celery queue depth
- LLM: AMS-managed GPT-4o endpoint
- OpenFOAM: all flow regimes (simpleFoam, pimpleFoam, interFoam), parallel workers
- LAMMPS: Python library interface, full ensemble and potential support
- FreeCAD: full headless Python API, Gmsh and Netgen mesh generation
- Authentication: JWT / OAuth2
- Storage: S3-compatible object store
- Scaling: HPA, minimum 2 worker replicas

Code quality and architecture are identical in both tracks.
The Prototype is a real working system. Its constraints are infrastructure, not code.

---

## Implementation phases

Follow these phases in order. Do not skip ahead. Each step requires developer approval
before the next step begins. See the session and development workflow section above.

**Phase 1 — MCP server and OpenFOAM connector**

Step 1.1 Stand up the full Docker Compose stack. Verify all containers start, health checks
pass, and Redis is reachable from the worker and MCP server.

Step 1.2 Implement OpenFOAMInput Pydantic schema. Write unit tests for valid and invalid
inputs before writing any connector code.

Step 1.3 Build the FastMCP server with tool registration for run_cfd_simulation and
get_job_status. Return a mocked PENDING response for all valid inputs. Verify
tool discovery from a test MCP client.

Step 1.4 Implement case_builder.py: writes the full OpenFOAM case directory from the
JSON payload. Covers controlDict, fvSchemes, fvSolution, and boundary condition
files for a simpleFoam steady turbulent flow case.

Step 1.5 Implement OpenFOAMConnector.run(): mounts the work directory into
openfoam-svc, invokes simpleFoam, captures exit code and logs.

Step 1.6 Implement output_parser.py: reads the final time directory field files and
returns a structured dict with pressure and velocity field summaries.

Step 1.7 Wire the Celery worker: picks up job, calls the connector, writes results to the
local artifact volume, updates job status in Redis.

Step 1.8 Add a regression test using a known pipe flow case with expected output ranges.
This test must pass before Phase 1 is considered complete.

**Phase 2 — LAMMPS connector**

Step 2.1 Implement LAMMPSInput schema: element types, interatomic potential, ensemble,
timestep, number of steps, output frequency. Unit tests first.

Step 2.2 Implement script_builder.py: generates a valid LAMMPS input script from the
validated schema.

Step 2.3 Implement LAMMPSConnector.run(): invokes lmp inside lammps-svc as a
subprocess, captures stdout and exit code.

Step 2.4 Implement output_parser.py: reads the log file and extracts thermodynamic
trajectory data (temperature, pressure, energy per timestep).

Step 2.5 Register run_md_simulation in the MCP server. Update the tool router.

Step 2.6 Add a regression test using a Lennard-Jones argon case with known equilibrium
properties. This test must pass before Phase 2 is considered complete.

**Phase 3 — FreeCAD stub, caching, observability, hardening**

Step 3.1 Implement cache.py: SHA-256 normalisation of inputs, Redis lookup before job
submission, result storage after completion.
Note: Layer 1 saves the solver run and collapses the agent's status-polling loop (submit
returns COMPLETED immediately, so fewer get_job_status round-trips). Layer 2 (interpretation
cache, key `interp:{hash}`) additionally caches the final prose under the same hash and skips
the interpretation LLM call on identical repeats. LLM call #1 (tool selection) always runs —
something must translate the prompt into a structured tool call. See the "Two-layer
simulation cache" architecture rule and docs/phase-3.1.

Step 3.2 Add LangSmith tracing and structured JSON logging with a correlation ID on
every request across all layers.

Step 3.3 Implement all error handling paths with corresponding tests: - validation failure (Pydantic) - solver non-zero exit (OpenFOAM and LAMMPS) - output parse failure - worker crash mid-job - cache store unavailable (fall-through behaviour)

Step 3.4 Add the FreeCAD stub connector. It must register the tool in MCP discovery and
return a structured NOT_IMPLEMENTED response with a clear message.

Step 3.5 Run an end-to-end test confirming that a second identical MCP call returns a
cached result without invoking the solver. Phase 3 is not complete without this.

**Phase 4 — Production (requires AMS infrastructure input)**

Step 4.1 Replace static API key with JWT / OAuth2 token validation at the MCP server.

Step 4.2 Migrate artifact store from local Docker volume to S3-compatible object store.

Step 4.3 Implement the full FreeCAD connector: headless Python API, geometry import
(STEP or FCStd), FEM Workbench configuration, Gmsh or Netgen mesh generation,
backend solver invocation, structured result return.

Step 4.4 Write Kubernetes manifests for all services. Configure HPA for worker
deployments based on Celery queue depth.

Step 4.5 Add Prometheus metrics endpoint and Grafana dashboards for job latency, queue
depth, cache hit rate, and solver error rate.

Step 4.6 Enable TLS on all inter-service communication.

Step 4.7 Run load tests and tune worker pool sizes and resource limits.

---

## Architecture rules

These rules are non-negotiable and apply to every commit.

**SolverInterface contract**
Every solver connector must implement the SolverInterface abstract base class. The five
required methods are: validate_inputs, build_input_files, run, and parse_outputs, plus the
solver_name property. Adding a new solver means creating one new file that implements this
contract. No changes to the MCP server, tool router, or execution layer are permitted when
adding a solver.

**Layer boundaries**
Layer 1 (AMS Solver-MCP platform) is not touched. Layer 2 does not invoke solvers directly.
Layer 3 does not parse MCP protocol. Layer 4 contains no business logic. Each layer
communicates only with adjacent layers through defined interfaces.

**Solver isolation**
Solver containers run as non-root users with no network access. No solver binary or input
file executes outside its container. Path traversal from any user-supplied input must be
caught at the Pydantic validation layer before any file is written.

**Two-layer simulation cache**

Layer 1 — Solver cache (key: `cache:{sha256hex}`):
Before any solver is invoked, compute a SHA-256 hash of the normalised simulation inputs
(sort keys, normalise float precision, serialise to JSON). Check Redis for a completed job
record with that hash. If found, return the cached numeric result without running the solver
or the agent's polling loop.

Layer 2 — Interpretation cache (key: `interp:{sha256hex}`):
When the agent produces a final prose interpretation of a simulation result, store it in
Redis under the same SHA-256 key with an `interp:` prefix. On a subsequent identical request
that hits Layer 1, check for a cached interpretation before the agent runs the final LLM
call; if found, return it directly and the interpretation call is skipped. (Wired in the
chat SSE path `mcp_server/app.py :: GET /api/chat`; the key is derived by validating the raw
tool args through the same model the router uses, so both layers share one key.)

Never skip the Layer 1 check. If Redis is unavailable, fall through to the solver and log a
warning. Never let a cache outage block a request — both layers degrade to a fresh run /
fresh interpretation, never an error.

LLM call #1 (tool selection) always runs — something must translate natural language into a
structured tool call.

**Error responses**
Every MCP response is structured JSON. Never surface a raw Python stack trace to the
calling agent. Every error response includes: stage (validation, build, solver, parse), code,
and message. Solver non-zero exits must classify the error type from stderr before returning.

**Secrets**
No secrets are hardcoded anywhere. All credentials, API keys, and connection strings are
read from environment variables. The .env file is never committed.

**Tests before code**
For each schema and connector, unit tests are written in the same step as the code, not
after. A step is not complete if the code exists but the tests do not.

---

## Solver communication patterns

**OpenFOAM**

- Input: case directory written to the shared /work volume before solver invocation
- Required subdirectories: system/ (controlDict, fvSchemes, fvSolution), constant/
  (polyMesh, physical properties), 0/ (initial and boundary conditions per field)
- Invocation: subprocess call to simpleFoam (Prototype) from the case root directory
- Output: field files written to timestamped directories; parsed by output_parser
- No API, no socket: all communication is file-based and CLI-driven

**LAMMPS**

- Input: plain-text input script written to the shared /work volume (Prototype)
- Invocation: subprocess call to lmp -in input.lammps
- Output: log file (thermodynamic scalars per timestep) and dump files (per-atom data)
- In Production: use the lammps Python library instead of file-based subprocess to avoid
  file intermediaries and allow direct extraction of results into Python variables
- Compatible with ASE (Atomic Simulation Environment) for higher-level workflow control

**FreeCAD**

- Input: STEP or FCStd geometry file passed via the shared /work volume
- Control: Python API calls drive the FEM Workbench headlessly (no display required from
  version 0.20 onwards)
- Mesh generation: Gmsh or Netgen via the FEM Workbench
- Output: displacement, stress fields, or mesh data returned via Python API
- Prototype: stubbed — tool registers in MCP discovery, returns NOT_IMPLEMENTED
- Production: full headless workflow via freecad-svc container

---

## Project layout

```
Solver-MCP/
│
│   # ── Config and environment ─────────────────────────────────
├── config/
│   ├── settings.py        # Pydantic Settings model — single source of all config
│   └── __init__.py        # Exports: get_settings() cached singleton
│
│   # ── Layer 1: Agent and orchestration ──────────────────────────
├── agent/
│   ├── agent.py           # LLM builder (build_llm) and agent builder (build_agent)
│   ├── prompts.py         # System prompt and any prompt templates
│   └── __init__.py
│
│   # ── Layer 2: MCP server + HTTP API ─────────────────────────
├── mcp_server/
│   ├── app.py             # FastAPI app — mounts MCP and exposes HTTP routes
│   ├── server.py          # FastMCP server — tool registration, MCP protocol
│   ├── router.py          # Routes MCP tool calls to solver connectors
│   ├── routes/
│   │   ├── jobs.py        # GET /jobs/{job_id}  — job status and result retrieval
│   │   ├── health.py      # GET /health         — liveness and readiness probes
│   │   └── __init__.py
│   ├── schemas/
│   │   ├── openfoam.py    # OpenFOAMInput Pydantic model
│   │   ├── lammps.py      # LAMMPSInput Pydantic model
│   │   └── freecad.py     # FreecadInput Pydantic model
│   └── __init__.py
│
│   # ── Layer 2: Solver connectors ──────────────────────────────
├── connectors/
│   ├── base.py            # SolverInterface ABC
│   ├── openfoam/
│   │   ├── connector.py   # OpenFOAMConnector(SolverInterface)
│   │   ├── case_builder.py
│   │   ├── output_parser.py
│   │   └── __init__.py
│   ├── lammps/
│   │   ├── connector.py   # LAMMPSConnector(SolverInterface)
│   │   ├── script_builder.py
│   │   ├── output_parser.py
│   │   └── __init__.py
│   ├── freecad/
│   │   ├── connector.py   # FreecadConnector(SolverInterface) — stub in Prototype
│   │   ├── workflow.py    # Headless Python API workflow (Production only)
│   │   └── __init__.py
│   └── __init__.py
│
│   # ── Layer 3: Execution ──────────────────────────────────────
├── execution/
│   ├── worker.py          # Celery worker
│   ├── cache.py           # SHA-256 normalisation + Redis cache logic
│   ├── artifact_store.py  # Local FS adapter (Prototype) / S3 adapter (Production)
│   └── __init__.py
│
│   # ── Layer 4: Solver container definitions ───────────────────
├── docker/
│   ├── openfoam/
│   │   └── Dockerfile
│   ├── lammps/
│   │   └── Dockerfile
│   ├── freecad/
│   │   └── Dockerfile
│   ├── mcp_server/
│   │   └── Dockerfile     # Uses entrypoint.sh + run-fastapi-server.sh
│   └── worker/
│       └── Dockerfile
│
│   # ── Shell scripts ────────────────────────────────────────────
├── shell-scripts/
│   ├── entrypoint.sh          # Docker ENTRYPOINT — sets permissions, waits for Redis, execs CMD
│   └── run-fastapi-server.sh  # Starts Gunicorn with 3 Uvicorn workers
│
│   # ── Tests ───────────────────────────────────────────────────
├── tests/
│   ├── unit/              # Fast tests, mock connectors, no containers
│   │   ├── test_schemas.py
│   │   ├── test_cache.py
│   │   └── test_connectors.py
│   ├── integration/       # Requires Docker Compose to be running
│   │   ├── test_openfoam_connector.py
│   │   └── test_lammps_connector.py
│   └── regression/        # Reference simulations with known correct outputs
│       ├── openfoam/      # Reference case files + expected output ranges
│       └── lammps/        # Reference input scripts + expected thermo values
│
│   # ── CI/CD ────────────────────────────────────────────────────
├── .github/
│   └── workflows/
│       └── build-deploy.yml   # Build image, push to GHCR, update K8s manifests repo
│
│   # ── Project root ────────────────────────────────────────────
├── docker-compose.yml     # Full Prototype stack
├── Makefile               # Docker, test, lint, and dev targets
├── .env                   # Local environment values — never committed
├── .env.example           # All env var names documented, no values — committed
├── requirements.txt       # Dependencies
├── docs         # document every phase of development here and an md file
└── README.md
```

K8s manifests and ArgoCD configuration live in a **separate repository**
(e.g. `Solver-MCP-k8s`). See the CI/CD and GitOps section below.

**Layer and directory ownership at a glance**

config/ Central config — all env vars loaded and validated here via Pydantic
Settings. Every other module imports from config, never from os.environ
directly.
agent/ Layer 1 — LLM builder and agent orchestration. No other directory may
import an LLM provider package directly.
mcp_server/ Layer 2 — Two responsibilities kept in separate files:
app.py FastAPI application. Mounts FastMCP and HTTP routes.
server.py FastMCP server. MCP protocol and tool registration only.
routes/ HTTP endpoints (job status, health). Consumed by app.py.
connectors/ Layer 2 — Solver interface implementations, one subdirectory per solver.
execution/ Layer 3 — Async job lifecycle, caching, artifact storage.
docker/ Layer 4 — Container definitions. One subdirectory per service.
shell-scripts/ Shell scripts used inside containers. All scripts live here.
entrypoint.sh is the Docker ENTRYPOINT for the MCP container.
run-fastapi-server.sh starts Gunicorn inside that container.
.github/ GitHub Actions workflows. build-deploy.yml is the only workflow.
Makefile Developer interface for all Docker and project commands.

---

## Config and environment loading

All environment variables are loaded and validated in one place: `config/settings.py`.
No module outside `config/` calls `os.getenv()` directly. Every module that needs a
setting imports from `config`:

```python
from config import get_settings
settings = get_settings()
```

`get_settings()` returns a cached singleton. The settings object is built using Pydantic
Settings, which reads from the environment (and the `.env` file via python-dotenv) and
validates types, required fields, and value constraints at startup. If a required variable
is missing or has the wrong type, the application fails immediately with a clear error
before any solver or LLM is initialised.

The `.env` file is never committed. The `.env.example` file is committed and contains
every variable name with an empty value and a comment explaining what it is for. When
setting up the project, copy `.env.example` to `.env` and fill in the values.

**What lives in settings.py**

LLM settings LLM_PROVIDER, model name, API key (per provider)
MCP settings MCP_TRANSPORT, MCP_SERVER_URL, MCP_API_KEY
Redis settings REDIS_URL (default: redis://redis-svc:6379/0)
Celery settings CELERY_BROKER_URL, CELERY_RESULT_BACKEND
Artifact store ARTIFACT_STORE_TYPE (local or s3), LOCAL_ARTIFACT_PATH,
S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
Auth settings API_KEY (Prototype static key), JWT_SECRET (Production)
Work volume WORK_DIR (default: /work)
Logging LOG_LEVEL (default: INFO), LOG_FORMAT (json or text)

---

## HTTP API routes

The HTTP layer is built with **FastAPI**. FastMCP mounts onto the FastAPI app so both
the MCP protocol and the REST endpoints are served by a single process on a single port.

**Why FastAPI**
FastMCP has native support for mounting onto a FastAPI app via `mcp.get_asgi_app()`.
FastAPI uses Pydantic v2 natively, which is already the project's validation library.
Its async model aligns with Celery async job dispatch and the async MCP transport.

**File responsibilities**

`mcp_server/app.py` — creates the FastAPI application, registers middleware (CORS,
authentication, request ID injection for correlation logging), includes the route routers,
and mounts the FastMCP ASGI app at `/mcp`. This is the entry point that Uvicorn starts.

`mcp_server/server.py` — creates the FastMCP instance and registers the solver tools.
It has no knowledge of HTTP routing. It is imported by `app.py` and mounted onto it.

`mcp_server/routes/health.py` — liveness and readiness probes used by Docker Compose
health checks and Kubernetes probes.

`mcp_server/routes/jobs.py` — job status and result retrieval endpoints. The MCP agent
submits a simulation and gets back a job ID. It then polls this endpoint to check whether
the job has completed and retrieve the result artifact reference.

**Endpoints**

```
GET  /health           Liveness probe. Returns 200 if the process is running.
GET  /health/ready     Readiness probe. Returns 200 only if Redis is reachable.

GET  /jobs/{job_id}    Returns the current status and result for a simulation job.
                       Response shape:
                         {
                           "job_id": "...",
                           "status": "PENDING | RUNNING | COMPLETED | FAILED",
                           "result_ref": "...",   # present when COMPLETED
                           "error": {             # present when FAILED
                             "stage": "...",
                             "code": "...",
                             "message": "..."
                           }
                         }

POST /mcp              MCP JSON-RPC endpoint (HTTP/SSE transport, Production).
                       Mounted automatically by FastMCP. Not called directly.
```

**Starting the server**

In the Prototype, Uvicorn starts the FastAPI app inside the `Solver-MCP-mcp` container:

```
uvicorn mcp_server.app:app --host 0.0.0.0 --port 8000
```

The MCP client in `agent/agent.py` connects via stdio in the Prototype (launches the
server as a subprocess) or via HTTP/SSE in Production (connects to port 8000).

---

## CI/CD and GitOps

Production deployment uses a GitOps model with two separate Git repositories and ArgoCD
as the deployment controller. This separation is intentional: source code changes and
deployment state changes are distinct concerns with distinct owners, reviewers, and audit
trails.

### Two-repository model

**`Solver-MCP` (this repo) — source of truth for application code**
Contains Python source, Dockerfiles, tests, shell scripts, and the GitHub Actions
workflow. The only deployment artefact this repo produces is a Docker image, pushed to
GitHub Container Registry (GHCR). It has no knowledge of which cluster it runs on or
how many replicas are running.

**`Solver-MCP-k8s` (separate repo) — source of truth for cluster state**
Contains Kubernetes manifests for every service: Deployments, Services, ConfigMaps,
HPAs, Ingress, and the ArgoCD Application manifest. This repo is the single source of
truth for what is running in the cluster. No kubectl apply is ever run manually against
production. If it is not in this repo, it is not in the cluster.

### Pipeline flow

```
Developer pushes to main (Solver-MCP)
           │
           ▼
┌─────────────────────────────┐
│  GitHub Actions              │
│                              │
│  1. Run unit tests           │
│  2. Run linter               │
│  3. Build Docker image       │
│  4. Push to GHCR             │
│     ghcr.io/org/Solver-MCP-   │
│     mcp:<git-sha>            │
│                              │
│  5. Checkout Solver-MCP-k8s   │
│  6. Update image tag in      │
│     deployments/Solver-MCP-   │
│     mcp/deployment.yaml      │
│  7. Commit and push          │
└─────────────────────────────┘
           │
           │  git push to Solver-MCP-k8s
           ▼
┌─────────────────────────────┐
│  ArgoCD                      │
│  (watching Solver-MCP-k8s)    │
│                              │
│  Detects manifest change     │
│  Syncs cluster to new state  │
│  Rolls out new pod           │
│  Health checks pass          │
│  Old pod terminates          │
└─────────────────────────────┘
           │
           ▼
  New version running in cluster
```

### GitHub Actions workflow (.github/workflows/build-deploy.yml)

The workflow has three jobs that run in sequence:

**Job 1 — test**
Runs on every push and every pull request. Installs dependencies, runs unit tests with
pytest, and checks linting and formatting with ruff. This job does not require Docker.
It must pass before the next job runs.

**Job 2 — build-push**
Runs only on push to main (not on PRs). Builds the `Solver-MCP-mcp` Docker image using
the `docker/mcp_server/Dockerfile` and pushes it to GHCR with two tags: the short git
SHA (7 characters) as the immutable version tag, and `latest` as a floating tag. Uses
GitHub Actions layer cache to keep build times fast. The image tag is passed to Job 3
as a workflow output.

**Job 3 — update-manifests**
Checks out the `Solver-MCP-k8s` manifests repo using a Personal Access Token stored in
repository secrets. Updates the image field in
`deployments/Solver-MCP-mcp/deployment.yaml` to the new tag. Commits with a message
that includes the source commit SHA and workflow run URL for traceability. Pushes the
commit. Only commits if the tag actually changed (idempotent).

### Required GitHub repository secrets

Set these in the source repo (Solver-MCP) under Settings > Secrets > Actions:

FEM_AGENT_K8S_REPO The manifests repo in owner/repo format.
Example: your-org/Solver-MCP-k8s

FEM_AGENT_K8S_TOKEN A GitHub Personal Access Token with contents:write
permission on the manifests repo. Use a fine-grained
token scoped to Solver-MCP-k8s only.

`GITHUB_TOKEN` is provided automatically by GitHub Actions and is used to push the
Docker image to GHCR. No additional secret is needed for that.

### Solver-MCP-k8s repository layout

```
Solver-MCP-k8s/
├── deployments/
│   ├── Solver-MCP-mcp/
│   │   ├── deployment.yaml    # Image tag updated here by CI
│   │   ├── service.yaml
│   │   ├── hpa.yaml
│   │   └── configmap.yaml
│   ├── Solver-MCP-worker/
│   │   ├── deployment.yaml
│   │   ├── hpa.yaml
│   │   └── configmap.yaml
│   ├── openfoam-svc/
│   │   └── deployment.yaml
│   ├── lammps-svc/
│   │   └── deployment.yaml
│   ├── freecad-svc/
│   │   └── deployment.yaml
│   └── redis-svc/
│       ├── deployment.yaml
│       └── service.yaml
├── infrastructure/
│   ├── namespace.yaml         # Solver-MCP namespace definition
│   ├── ingress.yaml           # Ingress with TLS
│   └── secrets/               # Sealed secrets or external secrets refs
└── argocd/
    └── argocd-app.yaml        # ArgoCD Application manifest (applied once manually)
```

### ArgoCD Application manifest (argocd-app.yaml)

The `argocd-app.yaml` file lives in the `Solver-MCP-k8s` repo under `argocd/`. It is
applied once manually when setting up the cluster:

```
kubectl apply -f argocd/argocd-app.yaml -n argocd
```

After that single apply, ArgoCD takes over. It watches the `deployments/Solver-MCP-mcp/`
path in the manifests repo. Every time CI pushes a new image tag there, ArgoCD detects
the diff within 3 minutes (or immediately via webhook) and rolls out the new version.

Key settings in the ArgoCD Application:

automated.prune: true Resources removed from manifests are deleted from cluster.
automated.selfHeal: true Manual cluster changes are reverted to match manifests.
ignoreDifferences HPA-managed replica counts are excluded from diff checks
so ArgoCD does not fight the HPA over replica count.

### Makefile targets for CI/CD

make ci-check Run the same checks GitHub Actions runs (tests + lint + format)
before pushing. Catch failures locally before CI does.

---

## Shell scripts

All shell scripts used inside Docker containers live in `shell-scripts/` at the project
root. Keeping them in one directory makes it easy to audit what runs inside containers,
and the entrypoint ensures they all have execute permissions regardless of how they were
copied in.

**`shell-scripts/entrypoint.sh`**
The Docker ENTRYPOINT for the `Solver-MCP-mcp` container. It does three things in order:

1. Runs `chmod +x shell-scripts/*.sh` to ensure every script in the directory is
   executable. This protects against the execute bit being stripped by a Docker COPY
   on certain host operating systems or umask settings.
2. Waits for Redis to be reachable before proceeding. It parses `REDIS_URL` to extract
   the host and port, then polls with `nc` every 2 seconds up to `REDIS_WAIT_SECS`
   (default 30). If Redis is not up in time it exits with a clear error message.
3. Executes the command passed as arguments (`exec "$@"`), which the Dockerfile CMD
   sets to `shell-scripts/run-fastapi-server.sh`.

**`shell-scripts/run-fastapi-server.sh`**
Starts the FastAPI application using Gunicorn with Uvicorn workers. The configuration is:

- **Workers: 3** — fixed. Three async Uvicorn worker processes per container.
  Each worker handles many concurrent requests internally via asyncio. Three workers
  gives concurrency without excessive memory use on a single machine. In Production,
  scale by adding pods rather than increasing workers per pod.
- **Worker class: `uvicorn.workers.UvicornWorker`** — tells Gunicorn to spin up async
  Uvicorn workers rather than synchronous workers. Required for FastAPI and FastMCP.
- **Timeout: 120s** — simulation job submissions are async (they return a job ID
  immediately) so this timeout only needs to cover the MCP call roundtrip and Redis
  write, which should be well under a second. 120s is a safe ceiling.
- **Graceful timeout: 30s** — on SIGTERM, Gunicorn gives workers 30 seconds to finish
  in-flight requests before forcefully killing them.

The `docker/mcp_server/Dockerfile` references these scripts:

```dockerfile
COPY shell-scripts/ shell-scripts/
ENTRYPOINT ["shell-scripts/entrypoint.sh"]
CMD ["shell-scripts/run-fastapi-server.sh"]
```

---

## Makefile

The `Makefile` at the project root is the single interface for all Docker, test, lint,
and development commands. It removes the need to remember long `docker compose` invocations.

Run `make help` to see every available target with its description.

**Key targets**

make env Copy .env.example to .env (safe — skips if .env already exists)
make build Build all Docker images
make up Start the full Prototype stack in detached mode
make up-build Build images and start the stack in one command
make down Stop containers, keep volumes
make down-clean Stop containers, remove volumes and orphans
make logs Tail logs from all services
make logs-mcp Tail logs from the MCP server only
make ps Show container status
make shell-mcp Open a bash shell inside the running MCP container
make shell-redis Open the Redis CLI inside the running Redis container
make test Run the full test suite (unit + integration)
make test-unit Run unit tests only — no containers needed
make test-integration Run integration tests — requires stack to be up
make test-cov Run unit tests with HTML coverage report
make lint Run ruff linter and mypy type checker
make format Auto-format code with ruff
make smoke Verify LLM provider config works (runs agent/agent.py smoke test)
make health Hit /health on the running MCP server
make ready Hit /health/ready to check Redis connectivity
make tools List MCP tools registered on the running server
make clean Remove Python cache files and test artifacts
make clean-docker Remove stopped containers and dangling project images

---

## Services (Docker Compose)

| Service           | Image                              | Notes                                    |
| ----------------- | ---------------------------------- | ---------------------------------------- |
| Solver-MCP-mcp    | Solver-MCP/mcp-server:latest       | FastMCP server, port 8000                |
| Solver-MCP-worker | Solver-MCP/worker:latest           | Celery worker, mounts /work              |
| openfoam-svc      | openfoam/openfoam10:latest         | Non-root, no network, mounts /work       |
| lammps-svc        | lammps/lammps:stable               | Non-root, no network, mounts /work       |
| freecad-svc       | Solver-MCP/freecad-headless:latest | Non-root, headless, mounts /work         |
| redis-svc         | redis:7-alpine                     | Broker + cache, port 6379, internal only |
| artifact-store    | Docker volume                      | Local FS in Prototype, S3 in Production  |

Startup order: redis-svc first, then solver containers, then worker, then mcp server.
Health checks required on redis-svc and Solver-MCP-mcp before dependent services start.

---

## Technology stack

- **FastMCP** — MCP server framework (official Python SDK)
- **LangChain + LangSmith** — confirmed in AMS's platform; LangSmith for trace visibility
- **GPT-4o** — confirmed AMS language model; developer API key in Prototype
- **Pydantic v2** — runtime schema validation for all connector input and output models
- **Celery + Redis** — async job execution; Redis is both broker and simulation artifact cache
- **Docker + Compose** — solver isolation and full local stack management in Prototype
- **Kubernetes** — Production orchestration; HPA on Celery queue depth
- **pytest + pytest-asyncio** — all test layers; solvers mocked in unit, real in integration

---

## Open questions (do not assume answers)

These are unresolved. Do not hardcode assumptions about them. When an implementation
decision depends on one of these, stop and surface it to the developer before proceeding.

1. **Solver priority** — the BGT brief names Code_Aster and LAMMPS; the challenge video
   shows OpenFOAM, LAMMPS, FreeCAD. The submission primary target is unconfirmed.
2. **CalculiX connector** — the existing connector's internal structure is unknown. The
   SolverInterface ABC in this project is designed to be compatible but this has not been
   verified with AMS.
3. **Deployment environment** — whether the MCP server runs on the same host as
   Solver-MCP or as a separate service is unconfirmed. The Docker socket access pattern
   for the worker invoking solver containers depends on this.
4. **GPT-4o continuity** — whether AMS will continue using GPT-4o or switch models is
   unknown. Tool schema descriptions are written for GPT-4o's function-calling format.
5. **FreeCAD headless version** — assumes FreeCAD 0.21 which supports headless mode.
   If an older version is required, an Xvfb virtual framebuffer is needed in freecad-svc.
6. **OpenFOAM mesh handling** — whether the connector receives a pre-meshed polyMesh
   or must generate a mesh from a STEP or STL surface file (using blockMesh or
   snappyHexMesh) is unconfirmed.

---

## Testing requirements

- Unit tests must never invoke a real solver. Use mock connectors.
- Integration tests run against containerised solvers in Docker Compose.
- Every connector must have at least one regression test with a known reference simulation
  and expected output ranges. A regression test failure blocks the phase from being marked
  complete.
- All error handling paths (validation failure, solver error, parse failure, cache miss,
  cache unavailable) must have corresponding tests.
- Test the caching layer explicitly: first call runs the solver, second identical call returns
  the cached result without invoking the solver.
- Tests are written in the same step as the code they cover, not in a separate step later.

---

## Notes on the architecture

The architecture described in this CLAUDE.md may need to adapt based on AMS's existing
infrastructure. This document and the SRS/TDS v1.0.0 serve as the basis for presentation
and technical discussion with AMS. Decisions made during that discussion take precedence
over defaults defined here.

---

## LLM configuration — provider-agnostic setup

The Solver-MCP MCP connector is LLM-agnostic. No LLM is hardcoded anywhere in the
codebase. The LLM is selected entirely through environment variables at runtime. This
means the same codebase works whether the developer is using a personal Claude
subscription, an OpenAI API key, a local Ollama model, or an AMS-managed endpoint.

### agent.py

The file agent/agent.py is the single place where LLM construction happens.
It exports two public functions:

build_llm() Returns a LangChain BaseChatModel for the configured provider.
build_agent() Returns a LangChain AgentExecutor wired to the MCP server and LLM.

No other file in the project imports an LLM directly. All LLM usage goes through
build_llm() or build_agent(). If a new provider is needed, only agent/agent.py changes.

### Supported providers

openai GPT-4o or any OpenAI chat model. Requires OPENAI_API_KEY.
anthropic Any Claude model via the Anthropic API. Requires ANTHROPIC_API_KEY.
Default model: claude-sonnet-4-5. Override with ANTHROPIC_MODEL.
azure Azure-hosted OpenAI deployment. Requires AZURE_OPENAI_API_KEY,
AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT.
ollama Any model running locally via Ollama. No API key required.
Default model: llama3. Override with OLLAMA_MODEL.

### Environment variables

All variables go in a .env file at the project root. The .env file is never committed.
A .env.example file is committed with all variable names and no values.

Required for every setup:

LLM_PROVIDER= # one of: openai, anthropic, azure, ollama
MCP_TRANSPORT= # stdio (Prototype) or http (Production)

Provider-specific (set only the block that matches LLM_PROVIDER):

# OpenAI

OPENAI_API_KEY=
OPENAI_MODEL= # optional, default: gpt-4o

# Anthropic / Claude

ANTHROPIC_API_KEY=
ANTHROPIC_MODEL= # optional, default: claude-sonnet-4-5

# Azure OpenAI

AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_DEPLOYMENT=
AZURE_OPENAI_API_VERSION= # optional, default: 2024-02-01

# Ollama (local, no key needed)

OLLAMA_MODEL= # optional, default: llama3
OLLAMA_BASE_URL= # optional, default: http://localhost:11434

# MCP server (Production / HTTP transport only)

MCP_SERVER_URL= # e.g. http://localhost:8000
MCP_API_KEY= # static key for Prototype; JWT token for Production

### Developer setup example (Claude subscription)

The developer working on this project uses a Claude subscription. The local .env file
for development will look like this:

LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-5
MCP_TRANSPORT=stdio

This is a valid Prototype configuration. The Solver-MCP runs on GPT-4o in production
(confirmed from the AMS challenge video). When demonstrating to AMS, the .env switches
to:

LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
MCP_TRANSPORT=stdio

No code changes. Only the .env changes.

### AMS production configuration

When AMS provides a managed endpoint, the .env for production will use:

LLM_PROVIDER=openai # or azure, depending on AMS's setup
OPENAI_API_KEY= # AMS-managed key
MCP_TRANSPORT=http
MCP_SERVER_URL=https://Solver-MCP-mcp.ams-internal.example.com
MCP_API_KEY= # JWT token for production auth

### Smoke testing the LLM config

Before starting any development session, verify the LLM configuration is working:

python -m agent.agent

This sends a single short message to the configured LLM and prints the response.
It does not start the MCP server. It is a quick check that the API key is valid and
the provider is reachable. If it fails, it prints the exact error and exits.

### Adding a new provider

To add a provider not listed above:

1. Write a _build_<provider> function in agent.py that returns a BaseChatModel.
2. Add the provider name and function to \_PROVIDER_MAP in agent.py.
3. Add any required environment variable names to \_REQUIRED_ENV in agent.py.
4. Add the new variables to .env.example with empty values and a comment.
5. Present the change to the developer for approval before committing.

No other file needs to change.

The agent/ directory also contains prompts.py for the system prompt and any prompt
templates. Keeping prompts separate from the builder makes them easy to review,
version, and adjust without touching LLM wiring.

### LLM-agnostic rule for the codebase

No file outside agent.py may import from langchain_openai, langchain_anthropic,
langchain_ollama, or any other provider-specific LangChain package directly. If a
module needs an LLM, it receives a BaseChatModel as a constructor argument. The
concrete type is resolved only in agent.py or in tests using a mock.
