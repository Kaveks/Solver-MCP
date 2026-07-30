# Bonus Demo Prompts - Caching & Error Handling

Two prompts that show the cross-cutting Phase 3 features rather than a new physics case.

---

## Prompt 1 - Cache hit (identical resubmission)

Run **Prompt 1 from `lammps-prompts.md`** (`argon_equilibration`) once and let it complete.
Then, in the same `make chat` session, paste the line below.

```
Run that exact same argon_equilibration simulation again with all the same parameters.
Submit it, poll until it finishes, and report the equilibrium results.
```

What to point out: the inputs normalise to the same SHA-256 cache key, so
`router.submit_job` finds the stored record and returns `COMPLETED` immediately - **no
Celery task, no solver run, no parse.** The `result_ref` points at the original run's
artifacts. This is the caching requirement from the architecture rules (and it also cuts
repeat LLM/tool cost).

> Tip: to make the cache hit unmistakable, watch the worker logs in another terminal
> (`make logs-worker`). On the cached call, nothing new appears.

---

## Prompt 2 - Structured error path (missing mesh)

Demonstrates that failures come back as clean `{stage, code, message}` JSON, never a raw
stack trace. Uses a mesh path that does not exist on `/work`.

```
Run a steady turbulent CFD simulation with simpleFoam. Case name: pipe_broken. Use the
mesh at meshes/does_not_exist/polyMesh. Kinematic viscosity 1e-5 with the kEpsilon
turbulence model. Inlet velocity 1.0 0.0 0.0, inlet k 0.00375, inlet turbulence
dissipation 0.005, outlet pressure 0. Run 500 iterations writing every 100. Submit it,
poll until it finishes, and report the result.
```

Expected: the job ends `FAILED` at the **build** stage with a message like
`polyMesh not found at /work/meshes/does_not_exist/polyMesh`. The agent reports the stage
and message plainly and does not speculate - exactly the contract in the system prompt.
