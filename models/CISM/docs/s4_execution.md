# Stage 4: Model Execution

## Purpose

Build (if needed) and execute the CISM cism_driver binary with the
generated configuration file. Includes preflight checks, execution with
timeout, and post-run output validation.

## Inputs

| Input | Source | Required |
|-------|--------|----------|
| cism_driver binary | Build from source or pre-built | Yes |
| Config file (.config) | s3 output | Yes |
| Input NetCDF | s1 output | Yes |
| Forcing NetCDF | s2 output | No |

## Outputs

| Output | Format | Used by |
|--------|--------|---------|
| output.nc | NetCDF | s5 (parsing), s6 (visualization) |
| stdout/log | Text | Diagnostics |

## Procedure

1. **Build CISM** (if binary not available):
   ```bash
   cd CISM_SOURCE/
   mkdir -p builds/serial && cd builds/serial
   cmake \
     -D CISM_USE_TRILINOS:BOOL=OFF \
     -D CISM_MPI_MODE:BOOL=OFF \
     -D CISM_SERIAL_MODE:BOOL=ON \
     -D CISM_BUILD_CISM_DRIVER:BOOL=ON \
     -D CISM_NETCDF_DIR="/usr" \
     -D CISM_NETCDF_LIBS="netcdff" \
     -D CMAKE_Fortran_FLAGS="-g -O2 -ffree-line-length-none -fPIC -fno-range-check" \
     -D CMAKE_Fortran_COMPILER=gfortran \
     -D CMAKE_C_COMPILER=gcc \
     -D CISM_EXTRA_LIBS:STRING="-lblas" \
     ../..
   make -j$(nproc)
   ```
   Binary: `builds/serial/cism_driver/cism_driver`

2. **Preflight checks**:
   - Binary exists and is executable
   - Config file exists and has required sections
   - Input NetCDF exists and is readable
   - Parameter sanity (dt_002, dt_003, dt_007 checks)

3. **Execute**:
   ```bash
   # Serial
   ./cism_driver dome.config

   # MPI parallel
   mpirun -n 4 ./cism_driver dome.config
   ```

4. **Monitor**: Watch stdout for convergence info, error messages.
   Common patterns:
   - `Picard iteration converged` -- HO solver working
   - `WARNING: max velocity exceeds CFL` -- dt too large
   - `NaN detected` -- numerical instability

5. **Post-run validation**:
   - Output NetCDF exists
   - Time dimension is non-empty (dt_009)
   - Expected variables present
   - No NaN in final timestep

## Verification

- [ ] cism_driver exits with code 0
- [ ] Output NetCDF created with non-zero time dimension
- [ ] All requested output variables present
- [ ] No NaN values in output fields
- [ ] Runtime reasonable for domain size

## Traps

| ID | Trap | Prevention |
|----|------|-----------|
| dt_004 | Temperature instability (dt too large) | Reduce dt; check CFL |
| dt_005 | Crash: which_ho_sparse=4 without Trilinos | Use which_ho_sparse=3 |
| dt_010 | Nonlinear solver diverges | Use Picard (which_ho_nonlinear=0) |
| dt_017 | Crash: sigma levels not monotonic | Check sigma ordering 0->1 |
| dt_018 | Crash: input time slice out of range | Check [CF input] time value |
| dt_019 | Crash: restart file missing fields | Ensure all vars in input.nc |

## Example

```bash
# Quick serial run with wrapper
python tools/run_cism.py --binary ./cism_driver --config dome.config

# Build and run
python tools/run_cism.py --build --source_dir ../../source/repo \
    --config dome.config

# MPI run
python tools/run_cism.py --binary ./cism_driver --config dome.config \
    --mpi --nproc 4 --timeout 7200
```
