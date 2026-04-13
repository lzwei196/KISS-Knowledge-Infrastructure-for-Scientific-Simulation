# S6: Execution

## Purpose

Run the PFLOTRAN simulator on the assembled input deck. Handles MPI parallel
execution, timeout management, output verification, and error diagnosis.

## Inputs

| Input | Format | Source |
|---|---|---|
| Input deck | `.in` file | s5_input_deck_assembly |
| Data files | CSV / text | s3_forcing_boundary |
| Mesh file | `.h5` / `.uge` (unstructured only) | s1_grid_generation |
| PFLOTRAN binary | Executable | Installation |

## Outputs

| Output | Format | Description |
|---|---|---|
| HDF5 output | `.h5` | Spatial fields at specified times |
| Observation files | `-obs-*.tec` | Time series at observation points |
| Mass balance | `-mas.dat` | Cumulative in/out/storage |
| Screen output | `.out` (redirected) | Solver iterations, convergence info |
| Run summary | `_run_summary.json` | Timing, success/failure, diagnostics |

## Procedure

### Step 1: Pre-flight Checks

Before execution, verify:

1. **Binary exists and is executable**: `which pflotran` or check explicit path
2. **Input file exists**: Check `.in` file is readable
3. **Referenced files exist**: Parse input for `FILE` references
4. **MPI is available**: If nproc > 1, check `mpirun` exists
5. **Disk space**: Estimate output size (ncells × ntimes × nvars × 8 bytes)

### Step 2: Execute

**Single process:**
```bash
pflotran -pflotranin simulation.in
```

**Parallel (4 processes):**
```bash
mpirun -n 4 pflotran -pflotranin simulation.in
```

**With output redirect:**
```bash
mpirun -n 4 pflotran -pflotranin simulation.in > simulation.out 2>&1
```

### Step 3: Monitor

Key lines to watch in stdout:

```
 == FLOW RICHARDS ========================================
 0 2r: 1.23E+04 2x: 0.00E+00 ir: 0.00E+00 dt: 1.00E-03 |  0.00E+00  0.00E+00
 1 2r: 8.92E+02 2x: 3.14E+01 ir: 3.14E+01 dt: 1.00E-03 |  0.00E+00  0.00E+00
```

- `2r`: L2 norm of residual (should decrease)
- `2x`: L2 norm of update
- `dt`: current time step size
- "Time step cut" means convergence failure → reduces dt

### Step 4: Check Completion

Success indicator:
```
 == FLOW RICHARDS ========================================
   Simulation Complete
   Timing:  ... seconds
```

Failure indicators:
- `PETSC ERROR`
- `Newton solver DIVERGED`
- `SNES_DIVERGED_FNORM_NAN`
- Process killed (OOM)

### Step 5: Validate Output

1. HDF5 file exists and is non-empty
2. Observation files contain expected number of records
3. Mass balance error < 1%
4. No NaN in output fields
5. Pressure/saturation in physical range

## Verification

| Check | Pass Criteria | Action on Fail |
|---|---|---|
| Return code | 0 | Check stderr for error type |
| "Simulation Complete" | Present in stdout | Incomplete simulation |
| HDF5 size | > 0 bytes | Check OUTPUT block |
| Mass balance error | < 1% | Refine grid or reduce dt |
| Time step cuts | < 10% of total steps | Adjust initial/max dt |
| Wall time | < expected | (just informational) |

## Traps

| Symptom | Cause | Fix |
|---|---|---|
| Immediate PETSC ERROR | Version mismatch | Rebuild PFLOTRAN against current PETSc |
| Stalls at t=0 | Bad initial condition | Use HYDROSTATIC with reasonable datum |
| "SNES_DIVERGED_FNORM_NAN" | NaN in residual (bad params) | Check vG alpha units, permeability range |
| Repeated time step cuts | Strong nonlinearity | Reduce max timestep; check BCs |
| HDF5 file empty | No VARIABLES in OUTPUT | Explicitly list variables |
| Runs forever | FINAL_TIME in wrong units | Use `FINAL_TIME 10.d0 y` with unit keyword |

## Example

```bash
# Run Bengbu Basin simulation (4 cores, 2hr timeout)
python run_pflotran.py \
    --input-file bengbu_richards.in \
    --nproc 4 \
    --timeout 7200

# Check output
h5ls bengbu_richards.h5
head -20 bengbu_richards-obs-0.tec
```

### Typical Runtime Estimates

| Grid Size | Mode | Processes | Estimated Time |
|---|---|---|---|
| 10,000 cells | Richards steady | 1 | < 1 min |
| 100,000 cells | Richards 10yr | 4 | 5-30 min |
| 1,000,000 cells | Richards 10yr | 16 | 1-4 hr |
| 100,000 cells | Reactive transport | 8 | 1-8 hr |
