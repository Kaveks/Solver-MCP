# LAMMPS Demo Prompts - `run_md_simulation`

Molecular dynamics of a Lennard-Jones fluid. These need no pre-staging - LAMMPS builds
its own input script from the schema. All values stay in the stable liquid regime so each
run equilibrates cleanly near its NVT temperature setpoint.

Schema fields exercised: `case_name`, `units`, `lattice` (style, reduced_density,
replicate), `potential` (type, epsilon, sigma, cutoff), `ensemble` (type, temperature),
`timestep`, `n_steps`, `output_frequency`.

---

## Prompt 1 - Argon equilibration (the flagship demo)

Best first prompt: a full 2000-step NVT run that equilibrates right at T\*=1.5.

```
Run a Lennard-Jones argon molecular dynamics simulation. Case name: argon_equilibration.
Use lj units, an fcc lattice at reduced density 0.8442 replicated 10 by 10 by 10, a
Lennard-Jones potential with epsilon 1.0, sigma 1.0, cutoff 2.5, an NVT ensemble at
temperature 1.5, timestep 0.005, 2000 steps, output every 100 steps. Submit it, poll the
job status until it finishes, and report the equilibrium temperature, pressure, and
energies.
```

Expected: equilibrium temperature settles close to 1.5; negative potential energy
(attractive, dense LJ system).

---

## Prompt 2 - Warmer fluid (shows temperature control)

Same system, higher setpoint - good for showing the thermostat tracks a different target.

```
Run an NVT Lennard-Jones molecular dynamics simulation. Case name: argon_hot. Use lj
units, an fcc lattice at reduced density 0.8442 replicated 8 by 8 by 8, a Lennard-Jones
potential with epsilon 1.0, sigma 1.0, cutoff 2.5, an NVT ensemble at temperature 2.0,
timestep 0.005, 3000 steps, output every 100 steps. Submit it, poll until it finishes,
and report the equilibrium temperature, pressure, and total and potential energies.
```

Expected: equilibrium temperature near 2.0; higher pressure than Prompt 1.

---

## Prompt 3 - Quick short run (fast turnaround)

A small, short run for a snappy live demo when time is tight.

```
Run a quick Lennard-Jones molecular dynamics test. Case name: argon_quick. Use lj units,
an fcc lattice at reduced density 0.8442 replicated 6 by 6 by 6, a Lennard-Jones potential
with epsilon 1.0, sigma 1.0, cutoff 2.5, an NVT ensemble at temperature 1.2, timestep
0.005, 500 steps, output every 50 steps. Submit it, poll until it finishes, and report the
equilibrium temperature and energies.
```

Expected: completes quickly; temperature trends toward 1.2 over the short run.

## Prompt 4 - Takes Minutes to simulate

```
I'd like to simulate argon atoms in an FCC lattice using the Lennard-Jones potential. Use the standard reduced density of 0.8442 and a simulation box of 10 by 10 by 10 unit cells. Run an NVT simulation at a reduced temperature of 1.0 with a timestep of 0.005 for 50,000 steps, printing thermodynamic data every 100 steps. Name this simulation argon_equilibration.
```
