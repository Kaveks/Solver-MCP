# OpenFOAM Demo Prompts - `run_cfd_simulation`

Steady, turbulent, incompressible flow with `simpleFoam` over the seeded duct mesh. All
three prompts reuse the same `polyMesh` (the connector does not generate a mesh - open
question Q6), which `openfoam-svc` provisions automatically on startup.

The prompts only state the physics that matters - inlet velocity and viscosity. Everything
else has a sensible default or is derived:

- **Mesh** defaults to the seeded `mesh/constant/polyMesh` - no need to name it.
- **Inlet turbulence** (`k`, `epsilon`/`omega`) is derived from the inlet velocity using the
  standard intensity (5%) + length-scale estimate, so a prompt never states them. (You can
  still give explicit values to override the estimate.)
- **Turbulence model** defaults to `kEpsilon`; **outlet pressure** to 0; **iterations** to
  1000 (stops early on convergence); **write interval** to 100.

Schema fields a prompt typically sets: `case_name`, `fluid.kinematic_viscosity`,
`boundary_conditions.inlet_velocity`.

---

## Mesh provisioning (automatic)

No manual staging is needed. On every `make up`, `openfoam-svc` runs `blockMesh` into
`/work/mesh` (the reference 0.1 x 0.1 m duct) only if the mesh is missing, so the default
`mesh/constant/polyMesh` is always present. `make seed-openfoam-mesh` only **forces** a
re-seed.

Verify (optional): `docker exec Solver-MCP-openfoam ls /work/mesh/constant/polyMesh` should
list `boundary faces neighbour owner points`.

---

## Prompt 1 - Baseline pipe flow (the flagship CFD demo)

```
Run a steady turbulent CFD simulation with simpleFoam. Case name: pipe_baseline. Inlet
velocity 1.0 m/s along x. Fluid kinematic viscosity 1e-5. Submit it, poll the job status
until it finishes, and report the pressure and velocity field summaries.
```

Expected: converges well within the default iteration budget; mean velocity magnitude ≈ 1.0
m/s with the mean vector aligned to the x-axis. (Derived inlet k ≈ 0.00375, epsilon ≈ 0.005

- the same values the earlier hand-tuned prompt used.)

---

## Prompt 2 - Faster inlet (shows the field summary scaling)

```
Run a steady turbulent pipe flow with simpleFoam. Case name: pipe_fast. Inlet velocity 2.0
m/s along x. Kinematic viscosity 1e-5. Submit it, poll until it finishes, and report the
pressure and velocity field summaries.
```

Expected: mean velocity magnitude ≈ 2.0 m/s; larger pressure variation than Prompt 1.

---

## Prompt 3 - More viscous fluid (shows viscosity sensitivity)

```
Run a steady turbulent CFD case with simpleFoam. Case name: pipe_viscous. Inlet velocity
1.0 m/s along x. Kinematic viscosity 5e-5. Submit it, poll until it finishes, and report the
pressure and velocity field summaries.
```

Expected: still ≈ 1.0 m/s mean velocity; the higher viscosity gives a smoother,
faster-converging field.
