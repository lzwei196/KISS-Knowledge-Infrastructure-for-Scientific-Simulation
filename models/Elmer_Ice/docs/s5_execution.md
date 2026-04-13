# S5: Execution

## Purpose

Run ElmerSolver to execute the ice dynamics simulation defined in the SIF file.
This stage handles preflight validation, serial and parallel execution, and
output verification.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| SIF file | Stage s4 | Simulation configuration |
| Mesh directory | Stage s2 | FEM mesh files |
| Forcing files | Stage s3 | Boundary condition data |
| Geometry files | Stage s1 | Initial conditions |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `results*.vtu` | VTU XML | Simulation results per output interval |
| `results*.result` | Elmer native | Restart/continuation files |
| stdout/stderr | Text | Solver log with convergence info |

## Procedure

### Serial Execution

```bash
# Direct execution
cd run_directory
ElmerSolver simulation.sif

# Using wrapper script with preflight checks
python run_elmerice.py --sif simulation.sif --run_dir ./run \
    --solver_binary ElmerSolver --np 1 --timeout 3600
```

### Parallel Execution (MPI)

```bash
# Step 1: Partition mesh (MUST do this first — dt_011!)
ElmerGrid 2 2 rectangle -partdual -metis 4

# Step 2: Run with MPI
mpirun -np 4 ElmerSolver simulation.sif

# Or using wrapper
python run_elmerice.py --sif simulation.sif --run_dir ./run \
    --solver_binary ElmerSolver --np 4 --timeout 7200
```

### Monitoring Progress

ElmerSolver prints convergence information to stdout:
```
Time: 1 / 100
  ComputeChange: NS (ITER=1) (NRM,RELC): ( 1.234e+02  1.000e+00)
  ComputeChange: NS (ITER=2) (NRM,RELC): ( 1.234e+02  5.678e-03)
  ComputeChange: NS (ITER=3) (NRM,RELC): ( 1.234e+02  1.234e-07) :: Converged
```

- `NRM`: Solution norm
- `RELC`: Relative change (should decrease toward tolerance)
- `Converged`: Nonlinear system converged

## Verification

After execution:
1. Check return code = 0
2. Verify VTU files exist: `ls results*.vtu`
3. Check for "Model Run Complete" or "Converged" in stdout
4. Look for NaN warnings in stderr
5. Open first/last VTU in ParaView to verify sensible results

## Traps

| Trap | ID | Symptom | Fix |
|------|----|---------|-----|
| No mesh partitioning | dt_011 | MPI crash at startup | `ElmerGrid 2 2 mesh -partdual -metis N` |
| MUMPS out of memory | dt_017 | Crash with memory error | Switch to iterative solver |
| NaN propagation | dt_013 | NaN in output | Set Critical Shear Rate > 0 |
| Empty VTU | dt_015 | No output files | Check Output Intervals |
| Wrong mesh path | — | "Mesh not found" error | Check SIF Header mesh DB path |
| Timeout | — | Process killed | Increase --timeout or reduce mesh/timesteps |

## Runtime Estimates

| Problem Size | Solver | Serial | 4-core MPI |
|-------------|--------|--------|------------|
| 1K nodes, SSA, 100 steps | Direct | 30 s | 15 s |
| 10K nodes, SSA, 100 steps | Direct | 5 min | 2 min |
| 100K nodes, SSA, 100 steps | Iterative | 30 min | 10 min |
| 100K nodes, Stokes, 100 steps | Iterative | 4 hr | 1 hr |
| 1M nodes, Stokes, 100 steps | Iterative | 2 days | 12 hr |

## Example

```bash
# Full workflow: mesh → partition → run → check
ElmerGrid 1 2 rectangle
ElmerGrid 2 2 rectangle -partdual -metis 4
cd run && mpirun -np 4 ElmerSolver simulation.sif
ls results*.vtu | wc -l  # Should show 10 files (100 steps / 10 interval)

# Using wrapper for preflight checks
python run_elmerice.py --sif simulation.sif --run_dir ./run \
    --np 4 --timeout 7200
```
