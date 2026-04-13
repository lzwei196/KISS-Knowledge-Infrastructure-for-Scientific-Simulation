# S8: Execution — Skill Document

## Purpose

Run ParFlow, monitor convergence via kinsol.log, and validate output files.

## Execution Methods

| Method | Command | When |
|--------|---------|------|
| Python pftools | `python run_<name>.py` | Default (most convenient) |
| Direct MPI | `mpirun -np N parflow <name>` | Production runs |
| TCL | `tclsh <name>.tcl` | Legacy scripts |

## Memory Estimation

```
Memory (GB) ~ NX * NY * NZ * 200 bytes / 1e9
```
- 100x100x15 = 30 MB (trivial)
- 500x500x20 = 1 GB (workstation)
- 1000x1000x20 = 4 GB (server)

## kinsol.log Interpretation

| Pattern | Meaning | Action |
|---------|---------|--------|
| nni < 10 | Good convergence | None needed |
| nni 10-50 | Acceptable | Monitor |
| nni 50-100 | Marginal | Consider reducing dt |
| nni > 100 | Poor convergence | Reduce dt or improve IC |
| nni = MaxIter | Solver failed | MUST reduce dt |

## Procedure

1. **Run** `run_parflow.py` with run directory and name.
2. **Monitor** runtime (check expected runtime table in SKILL.md).
3. **Check** exit code: 0 = success, non-zero = error.
4. **Check** output: pressure and saturation PFB files should exist.
5. **Check** kinsol.log: mean iterations < 50 is acceptable.

## Common Pitfalls

- **Distributed PFB** (dt_pf_040): MPI runs produce one file per rank. Must combine.
- **Timeout**: Large domains can run for hours/days. Do NOT kill prematurely.
- **SIGABRT**: Some gfortran versions emit SIGABRT after clean completion (check output files, not just exit code).
