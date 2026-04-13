# S5: Execution

## Purpose

Run the TELEMAC simulation, monitor progress, and diagnose common runtime
failures. This stage invokes the TELEMAC runner scripts that handle file
staging, compilation of user Fortran, and parallel decomposition.

## Inputs

| Input                | Format   | Description                                 |
|----------------------|----------|---------------------------------------------|
| Steering file        | .cas     | From Stage 4                                |
| All referenced files | various  | Geometry, boundary, forcing files           |
| TELEMAC installation | binary   | Compiled TELEMAC with systel.cfg configured |

## Outputs

| Output               | Format   | Description                                 |
|----------------------|----------|---------------------------------------------|
| Results file         | .slf     | SELAFIN with requested output variables     |
| Listing file         | .lis     | Text log with convergence, mass balance     |
| Temporary directory  | dir      | Working files (cleaned on success)          |

## Procedure

1. **Set environment**:
   ```bash
   export HOMETEL=/path/to/telemac
   export PATH=$HOMETEL/scripts/python3:$PATH
   # Verify systel.cfg exists
   ls $HOMETEL/build/systel.cfg
   ```

2. **Run sequentially**:
   ```bash
   cd /path/to/simulation
   telemac2d.py simulation.cas
   ```

3. **Run in parallel** (requires MPI + METIS):
   ```bash
   telemac2d.py simulation.cas --ncsize 8
   ```
   This automatically:
   - Decomposes the domain with METIS
   - Launches MPI processes
   - Recombines results with GRETEL

4. **Monitor progress**:
   - Watch the listing output for convergence warnings
   - Check mass balance at each listing period
   - Monitor Courant number (should stay < 1 for FE)

5. **Using the wrapper script**:
   ```bash
   python run_telemac.py --cas simulation.cas --module telemac2d \
       --hometel /path/to/telemac --nproc 4
   ```

## Verification

- [ ] "My work is done" message at end of log
- [ ] Results file exists and has expected size
- [ ] Mass balance error < 0.1% at final timestep
- [ ] No "NaN" or "Infinity" in listing output
- [ ] Solver converged at all timesteps

## Traps

- **dt_015**: "STOP 1" or "NaN" in output usually means CFL violation.
  Reduce TIME STEP or enable VARIABLE TIME-STEP.

- **dt_016**: Parallel run hangs silently. Check that --ncsize matches
  available MPI slots and METIS decomposition succeeded.

- **dt_017**: User Fortran compilation fails with "undefined reference".
  Ensure user Fortran is compiled with the same compiler used to build TELEMAC.

- **dt_014**: Negative depths appear in listing with warnings like
  "NEGATIVE DEPTH". Enable TIDAL FLATS = YES and/or set
  TREATMENT OF NEGATIVE DEPTHS = 2.

## Example

```bash
# Full execution workflow
export HOMETEL=/opt/telemac
export PATH=$HOMETEL/scripts/python3:$PATH

# Validate steering file first
python run_telemac.py --cas t2d_estuary.cas --module telemac2d \
    --hometel $HOMETEL --dry-run

# Run (4 cores)
telemac2d.py t2d_estuary.cas --ncsize 4

# Check completion
grep "MY WORK IS DONE" t2d_estuary.cas_*.lis

# Parse output
python parse_selafin.py r2d_estuary.slf --info
```
