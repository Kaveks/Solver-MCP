# Solver-MCP MCP Connector

**Natural-language Solver-MCP, executed on real solvers.** An engineer types
_"simulate turbulent water flow through this pipe at 2 m/s"_ and an AI agent turns it into a
validated, sandboxed run on a production CFD/MD solver — returning structured numbers, not a
chat guess. This service is the bridge between the agent and three simulation engines:
**OpenFOAM** (fluid dynamics), **LAMMPS** (molecular dynamics), and **FreeCAD** (structural
FEM, currently a registered stub).

The hard problem it solves: simulation software is powerful but unforgiving — it wants exact
input files, directory layouts, and parameter names, and fails cryptically when anything is
off. Pointing an LLM straight at a solver is fragile and unsafe. This connector inserts a
**validated, auditable, sandboxed boundary** in between: every request is type-checked, every
path is sanitised, every solver runs isolated, and every result _and_ error returns as
structured data — never a raw crash dump.

> Reference architecture: **[`docs/project_structure.png`](docs/project_structure.png)** —
> the request flows top-down (Engineer → Agent → MCP server → Execution → Connectors →
> Solver containers → Results) and the result flows back up to the agent.

![Architecture](docs/project_structure.png)

---

## Why this stack

The architecture is four independent layers joined by narrow contracts. Each technology was
chosen to enforce a specific boundary, and each is **visible in a specific directory**.

### Model Context Protocol (MCP) — the agent ↔ tools contract

An LLM should not be hard-wired with "if the user says X, call function Y." MCP is an open
standard where the server _publishes_ typed tools and the agent _discovers_ them at runtime:
each tool has a name, a description, and a JSON Schema for its arguments. The agent calls a
tool by name with a JSON object; the server validates and acts. This turns brittle prompt
glue into a discoverable, enforced contract — and the contract the agent sees is generated
directly from the same Pydantic model the server validates against, so they can never drift.

_Evident in:_ `mcp_server/server.py` (the four `@mcp.tool` definitions), schemas in
`mcp_server/schemas/`, the agent's MCP client in `agent/agent.py`.

### FastAPI — one async process, two protocols

FastMCP mounts onto a FastAPI app, so a single process serves both the MCP protocol (at
`/mcp`) and a REST surface (health probes, job status, the chat SSE stream, the web UI).
FastAPI is Pydantic-native (the project's validation library) and async-first, which matches
both the streaming MCP transport and async job dispatch. Validation happens at the HTTP
boundary, so a malformed request is a structured `422`, never a deferred worker crash.

_Evident in:_ `mcp_server/app.py` (app, middleware, routes, MCP mount), `mcp_server/routes/`.

### Distributed system — async execution with Celery + Redis

A solver run takes seconds to minutes; an HTTP request must not block on it. Submitting a job
enqueues it on **Celery** (a distributed task queue) and returns a `job_id` immediately; a
worker runs it out of band; the client polls for the result. **Redis** is the shared
backbone — message broker, job store, and result cache in one. This decoupling is what makes
the API responsive under load and what allows workers to scale independently of the API.

_Evident in:_ `execution/worker.py` (Celery task), `execution/job_store.py`,
`execution/cache.py`, `redis-svc` in `docker-compose.yml`.

### Microservice architecture — isolated solver services

Each solver runs as its **own container**: non-root, **no network access**, sharing only a
`/work` volume. Solvers are large third-party binaries; isolating each one means a crashing
or compromised solver cannot touch the host, the network, or another solver. The application
holds no solver logic inside these containers — they are pure execution targets.

_Evident in:_ `docker/openfoam/`, `docker/lammps/`, `docker/freecad/` (one Dockerfile each),
`network_mode: "none"` + the shared `work` volume in `docker-compose.yml`.

### The seam that ties it together

**Layer 2 builds the solver command; Layer 3 executes it**, through a pluggable runner
(`execution/runner.py`, selected by `RUNNER_BACKEND`). That single abstraction is why the
_same_ connector code runs a solver as a local container in development and as an orchestrated
cluster job in production — with no code change. The same pattern applies to storage
(`ARTIFACT_STORE_TYPE`) and the LLM (`LLM_PROVIDER`): swap implementations behind a stable
interface, never rewrite.

---

## The four layers

| Layer                       | Directory                    | Responsibility                                         | Boundary it enforces                                                                            |
| --------------------------- | ---------------------------- | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| 1 — Agent                   | `agent/`                     | LLM (via LangChain) turns language into MCP tool calls | The AI can only call declared, schema-checked tools — never the solver, FS, or network directly |
| 2 — MCP server + connectors | `mcp_server/`, `connectors/` | Publish tools, validate, route, expose HTTP/UI         | Every request is type-checked and every path sanitised _before_ anything runs                   |
| 3 — Execution               | `execution/`                 | Async job lifecycle, caching, artifacts                | The fast web request is decoupled from the slow solver run                                      |
| 4 — Solver containers       | `docker/`                    | Run the solver binary, isolated                        | A solver cannot affect anything outside its sandbox                                             |

Each layer talks only to its neighbours. A new solver is one new module implementing
`SolverInterface` plus two one-line registrations — the server, worker, cache, and isolation
model are all solver-agnostic (see _Extending_ below).

---

## Caching — and why it matters in an agent call

An agentic simulation call is expensive on two axes: **solver compute** (the dominant cloud
cost — minutes to hours on a cluster) and **LLM tokens** (the agent runs several times per
request). Repeated work — parameter sweeps, design iterations, re-runs of the same case — is
common in engineering, so the system caches at **two layers, both keyed on the same SHA-256**
of the normalised `(solver, inputs)` pair.

| Request                        | LLM calls                         | Solver runs |
| ------------------------------ | --------------------------------- | ----------- |
| First submission               | 3–5 (select → poll×n → interpret) | 1           |
| Identical repeat — Layer 1     | 2 (select + interpret)            | **0**       |
| Identical repeat — Layer 1 + 2 | **1** (select only)               | **0**       |

- **Layer 1 — solver cache** (`cache:{hash}`): checked before dispatch. On a hit it returns
  the completed numeric result without running the solver, and `submit` returns `COMPLETED`
  immediately so the agent's polling loop collapses (each skipped poll is one fewer LLM
  round-trip).
- **Layer 2 — interpretation cache** (`interp:{hash}`): the agent's final prose answer is
  stored under the same key. On a repeat the cached interpretation is streamed back and the
  **final LLM call is skipped entirely** (the agent's event stream is stopped before the model
  step begins — nothing is aborted mid-flight).

What is **never** skipped: the first LLM call (tool selection) — something must always turn
language into a structured call. And caching never compromises correctness: if Redis is
unavailable, both layers fall through to a fresh run / fresh interpretation and log a warning.

_Evident in:_ `execution/cache.py` (both keyspaces), the cache check in `mcp_server/router.py`
(Layer 1), the serve/store logic in `mcp_server/app.py :: GET /api/chat` (Layer 2). Full
detail: [`docs/phase-3.1-caching-and-observability.md`](docs/phase-3.1-caching-and-observability.md)
and [`docs/phase-3.1b-interpretation-cache-and-history.md`](docs/phase-3.1b-interpretation-cache-and-history.md).

---

## The three solvers

- **OpenFOAM** — computational fluid dynamics. Drives `simpleFoam` (steady, turbulent,
  incompressible flow), returns summarised pressure and velocity fields. The schema is
  _de-technicalised_: a prompt states only inlet velocity and viscosity — mesh location,
  turbulence inlets (`k`, `ε`/`ω`), and run controls are defaulted or derived. **Fully
  supported.**
- **LAMMPS** — molecular dynamics. Runs an NVT Lennard-Jones fluid and returns the
  thermodynamic trajectory (temperature, pressure, energy) and equilibrium averages. **Fully
  supported.**
- **FreeCAD** — structural FEM. **Registered stub**: the tool is published and its input
  validated, but execution returns a structured `NOT_IMPLEMENTED`. Full headless workflow is
  on the roadmap.

The MCP server publishes four tools: `run_cfd_simulation`, `run_md_simulation`,
`run_fem_simulation`, and `get_job_status`.

---

## How a request flows

A simulation is asynchronous: **submit → poll → retrieve**.

1. **Submit.** The agent calls a `run_*` tool with a parameter object. The server validates
   it; the execution layer hashes the normalised inputs and checks the cache. Cache hit →
   completed result immediately. Miss → a job is created, enqueued, and `{ "job_id": "...",
"status": "PENDING" }` returned.
2. **Run.** A Celery worker sets the job `RUNNING`, writes solver input files to `/work`,
   invokes the solver in its container, parses output, stores artifacts, caches the result,
   and sets `COMPLETED` — or `FAILED` with a structured `{ stage, code, message }`.
3. **Retrieve.** The client polls `get_job_status` (or `GET /jobs/{job_id}`) until terminal;
   a completed response carries a `result_ref` and a `result` summary.

A CFD submission — note how little the caller must specify:

```jsonc
// run_cfd_simulation  (mesh, turbulence inlets, and controls are defaulted/derived)
{
  "case_name": "pipe_baseline",
  "fluid": { "kinematic_viscosity": 1e-5 },
  "boundary_conditions": { "inlet_velocity": [1.0, 0.0, 0.0] }, // m/s
}
// → { "job_id": "a1b2…", "status": "PENDING" }
// later → { "status": "COMPLETED", "result_ref": "…",
//   "result": { "pressure": { "mean": 0.08 },
//               "velocity": { "magnitude": { "mean": 1.00 } } } }
```

The agent path adds two more conveniences: the chat SSE endpoint streams tool calls and the
answer live, and the **web UI** (`/`) renders an inline result card and a per-device job
history. That history is **sourced from the backend** (Redis), scoped to the device — so a
cleared backend shows an empty history rather than stale client cache. See
[`docs/phase-3.1b-interpretation-cache-and-history.md`](docs/phase-3.1b-interpretation-cache-and-history.md).

---

## Quick start

Requires **Docker Engine** + **Docker Compose v2** (the only hard runtime dependency).
Python 3.12 is needed only to run the tests locally; an LLM API key is needed only to drive
the agent.

```bash
make env          # copy .env.example → .env (does not overwrite)
# edit .env: set LLM_PROVIDER and the matching API key (see Configuration)
make up-build     # build images + start the stack (server, worker, redis, 3 solvers)
make health       # GET /health  → 200 {"status":"ok"}
make ready        # GET /health/ready → 200 only when Redis is reachable
make tools        # list the four MCP tools
make chat         # interactive natural-language chat against the running stack
make down         # stop the stack
```

Open the web UI at **http://localhost:8000** (`make ui`). `make help` lists every target.

---

## Configuration

All configuration is environment variables, loaded and validated once at startup in
`config/settings.py` — a missing or malformed value fails fast with a clear message; no other
module reads the environment directly. Every variable is documented in `.env.example`.

- **LLM is provider-agnostic** (`LLM_PROVIDER`): OpenAI, Anthropic, Azure OpenAI, or local
  Ollama. Switching providers is a `.env` change, never code.
- **`MCP_TRANSPORT`** — `stdio` (launch the server as a subprocess) or `http` (connect to the
  running stack). Note this governs only the agent↔MCP-tools channel, not the Web UI: the
  Prototype default is `stdio`, and the Web UI keeps using it — the browser talks HTTP to
  `/api/chat`, but inside the container the agent still spawns the MCP server over `stdio`.
  Use `http` only when the agent runs **outside** the stack (host-driven `make chat`, or
  Production). To drive the agent against the Compose stack from the host, use:

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
MCP_TRANSPORT=http
MCP_SERVER_URL=http://localhost:8000
MCP_API_KEY=local-dev-key      # placeholder; the Prototype does not enforce auth
GUNICORN_WORKERS=1             # streamable-HTTP MCP sessions are per worker
```

`make smoke` verifies just the LLM credential (no stack needed).

---

## Testing

```bash
make test-unit          # fast, no containers (mocked solvers, fakeredis) — run constantly
make test-integration   # real execution inside solver containers
make test-regression    # real OpenFOAM + LAMMPS runs; asserts physics within expected ranges
make test               # all three levels
```

Regression includes a cache-correctness gate: an identical request submitted twice runs the
solver only once. Unit tests cover schemas, connectors, both cache layers, the job lifecycle,
error paths, per-device history scoping, and tool discovery.

---

## Deployment plan and scaling to production

The same codebase targets two tracks. **The difference is infrastructure, selected by
environment variables — not application code**, because the execution backend, storage, and
auth are already abstractions with interchangeable implementations.

### Prototype (today — `make up-build`)

Single machine, Docker Compose. The worker runs each solver by exec-ing into its long-running
container; artifacts go to a local Docker volume; auth is a static API key; one worker per
solver. A real, working system whose limits are operational (one host), not architectural.

### Production (the scale-out path)

Kubernetes, driven by GitOps:

- **Execution at scale.** `RUNNER_BACKEND` switches the runner from local container-exec to
  submitting each solver run as a **Kubernetes Job** (a one-off, isolated unit of work). The
  connector code is unchanged.
- **Elastic workers.** A **Horizontal Pod Autoscaler** scales worker replicas on **Celery
  queue depth** — load (not a fixed pool) drives capacity, with a minimum of 2 replicas.
- **Durable storage.** `ARTIFACT_STORE_TYPE` switches the artifact store from the local
  volume to an **S3-compatible object store**; Redis remains broker + cache (with persistence
  enabled in production).
- **Identity.** The single auth boundary at the server swaps the static key for **JWT/OAuth2**.
- **Delivery.** CI builds and pushes the image to GHCR; a separate manifests repo
  (`Solver-MCP-k8s`) is the source of truth for cluster state, reconciled by **ArgoCD** —
  source changes and deployment state stay distinct, audited concerns.
- **Observability & security.** Prometheus metrics + Grafana dashboards (job latency, queue
  depth, cache-hit rate, solver error rate) and TLS on inter-service traffic.

Because each of these is an implementation swap behind a stable interface, moving from
prototype to production is configuration and infrastructure work — not a rewrite. Full
detail: [`docs/phase-4.1-auth-and-storage.md`](docs/phase-4.1-auth-and-storage.md),
[`docs/phase-4.3-k8s-observability-hardening.md`](docs/phase-4.3-k8s-observability-hardening.md).

---

## Extending — adding a solver

A new solver is a self-contained addition: one module plus two one-line registrations.

1. Create `connectors/<solver>/` with a class implementing `SolverInterface`
   (`connectors/base.py`): `solver_name`, `validate_inputs`, `build_input_files`, `run`,
   `parse_outputs`. Add its input schema under `mcp_server/schemas/`.
2. Register it in `connectors/registry.py` (one entry: name → class).
3. Add one `@mcp.tool` in `mcp_server/server.py`, typed with the new schema.

Unchanged: routing, the worker, both cache layers, the job store, the artifact store, the
runner, and the isolation model — they operate on the `SolverInterface` contract, not on any
specific solver.

---

## Project layout

The directory a file lives in tells you its layer and what it may depend on. (See
[`docs/project_structure.png`](docs/project_structure.png) for the visual.)

```
config/          Validated settings — the single source of all configuration.
agent/           Layer 1. LLM-agnostic agent builder + system prompt + chat REPL.
mcp_server/      Layer 2. FastAPI app, FastMCP server, router, HTTP routes, web UI, schemas.
connectors/      Layer 2. SolverInterface + one subpackage per solver (+ registry).
execution/       Layer 3. Celery worker, two-layer cache, job store, artifact store, runner.
observability/   Cross-cutting. Structured JSON logging with a correlation ID; tracing.
docker/          Layer 4. One Dockerfile per service (server, worker, each solver).
shell-scripts/   Container entrypoint and the Gunicorn launch script.
tests/           unit/ (mocked) · integration/ (containers) · regression/ (real physics).
docs/            Per-phase development records + architecture diagram.
docker-compose.yml · Makefile · requirements.txt · .env.example
```

Development history is recorded phase-by-phase under `docs/` (start at
[`docs/00-roadmap.md`](docs/00-roadmap.md)).

---

## Project context

Built for AM Simulation as part of the BGT 4th Edition 2026 programme. It extends an existing
GPT-4o + LangChain platform (Solver-MCP) with MCP connectors for OpenFOAM, LAMMPS, and FreeCAD;
a CalculiX connector already exists upstream. The agent layer is the platform's property and
is not modified here — this project owns Layers 2–4.
