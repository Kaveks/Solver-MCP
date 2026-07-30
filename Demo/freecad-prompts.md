# FreeCAD Demo Prompt - `run_fem_simulation`

Structural finite-element analysis (displacement / stress under load). **In the Prototype the
FreeCAD connector is a stub.** The tool is registered and discoverable, and its input is
validated against the real schema — but execution returns a structured `NOT_IMPLEMENTED`
response instead of running a solver. The full headless FreeCAD workflow (geometry import,
FEM Workbench, Gmsh/Netgen meshing, solve, result return) lands in the Production track
(Phase 4, `docs/phase-4.2`).

This prompt exists to demo three things that **are** real in the Prototype:

1. **Tool discovery** — `run_fem_simulation` shows up in MCP tool discovery alongside CFD/MD.
2. **Schema validation** — the input is validated by `FreecadInput` (path-traversal guarded on
   `case_name` and `geometry_ref`), so a malformed request is rejected before anything runs.
3. **Graceful not-implemented** — the agent reports the capability is not yet available rather
   than inventing a result (system prompt, step 5).

The prompt only states what the schema needs. Fields a prompt typically sets:
`case_name`, `geometry_ref` (a STEP or FCStd file on `/work`); `analysis_type` defaults to
`static` (the only Prototype option).

---

## Prompt 1 - Static structural analysis (the FEM stub demo)

```
Run a structural FEM analysis with FreeCAD. Case name: bracket_static. Use the geometry file
bracket.step. Static analysis. Submit it and report the displacement and stress results.
```

Expected: the agent selects `run_fem_simulation`, the input validates, and the tool returns a
structured NOT_IMPLEMENTED response (no solver runs, no job is dispatched):

```json
{
  "status": "NOT_IMPLEMENTED",
  "solver": "freecad",
  "error": {
    "stage": "solver",
    "code": "NOT_IMPLEMENTED",
    "message": "The FreeCAD connector is a stub in the Prototype. Structural FEM (geometry import, meshing, solve) is implemented in the Production track (Phase 4)."
  }
}
```

The agent then tells you plainly that structural FEM is not yet available in the Prototype and
is on the Production roadmap — it does not fabricate displacement or stress numbers.

---

## Note on the UI

If the FreeCAD solver is selected in the web UI sidebar, the agent is bound to this one tool
(deterministic routing). The result card renders the static "FEM — Not Implemented" panel
rather than metrics/charts, consistent with the stub response above.
