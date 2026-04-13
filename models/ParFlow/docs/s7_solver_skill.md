# S7: Solver Configuration — Skill Document

## Purpose

Configure the ParFlow solver (Richards equation, Newton-Krylov, preconditioner) and generate the run script.

## Key Solver Parameters

| Parameter | Default | Range | Effect |
|-----------|---------|-------|--------|
| TimeStep.Value | 1.0 hr | 0.01-24 hr | Larger = faster but may not converge |
| Nonlinear.MaxIter | 300 | 100-5000 | Max Newton iterations per timestep |
| Nonlinear.ResidualTol | 1e-6 | 1e-8 - 1e-4 | Convergence criterion |
| Linear.Preconditioner | PFMG | PFMG/MGSemi | PFMG for most cases, MGSemi for extreme K contrasts |
| OverlandKinematic | 1 | 0/1 | Kinematic wave (faster, less accurate for flat) |
| OverlandFlowDiffusive | 0 | 0/1 | Diffusive wave (more accurate, slower) |
| TerrainFollowingGrid | True | True/False | Follow topography (essential for sloped terrain) |

## Procedure

1. **Run** `generate_parflow_script.py` with domain JSON, run name, and dates.
2. **Review** generated script: check MPI topology, timestep, CLM settings.
3. **Verify** P*Q*R matches planned number of MPI processes.
4. **Verify** NX%P==0, NY%Q==0, NZ%R==0 (dt_pf_023).

## Overland Flow Choice

- **Kinematic** (default): Good for moderate-to-steep terrain. Faster. May produce unrealistic ponding in flat areas.
- **Diffusive**: Better for flat terrain and flood applications. Slower. More stable for backwater effects.

## Common Pitfalls

- **Timestep too large** (dt_pf_020): Sharp wetting fronts need small dt (0.1-0.5 hr).
- **Bad initial condition** (dt_pf_021): >100 iterations per step = poor IC.
- **PFMG crash** (dt_pf_022): K contrast > 1e6 needs MGSemi or capped K.
- **MPI mismatch** (dt_pf_023): nprocs MUST equal P*Q*R exactly.
