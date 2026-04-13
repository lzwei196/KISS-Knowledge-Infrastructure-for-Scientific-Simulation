# Stage 5: Model Execution

## Purpose

Run the RAPID binary to compute river discharge (Qout) and optionally stored
volume (V) from the lateral inflow (Vlat) using Muskingum routing through the
river network.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| rapid binary | Build (src/make rapid) | Compiled RAPID executable |
| rapid_namelist | Stage 4 | Complete configuration file |
| All files referenced in namelist | Stages 1–3 | Connectivity, parameters, Vlat |

## Outputs

| Output | Format | Units | Description |
|--------|--------|-------|-------------|
| Qout.nc | NetCDF4 | m³/s | Discharge at each reach per output time step |
| V.nc (optional) | NetCDF4 | m³ | Stored volume per reach |
| Qfinal.nc (optional) | NetCDF4 | m³/s | Final flow state for restart |

## Procedure

1. **Preflight checks**:
   - RAPID binary exists and is executable
   - Namelist file exists
   - All input files referenced in namelist exist
   - PETSc environment variables are set (PETSC_DIR, PETSC_ARCH)
   - NetCDF libraries are accessible

2. **Execute**:
   ```bash
   # Single process
   ./rapid --namelist /path/to/rapid_namelist

   # Parallel (4 processes)
   mpiexec -n 4 ./rapid --namelist /path/to/rapid_namelist
   ```

3. **Monitor execution**:
   - RAPID prints progress to stdout
   - Typical runtime: seconds to minutes for small basins, minutes to hours for continental
   - Memory: ~1 GB per 100,000 reaches per process

4. **Post-execution checks**:
   - Return code 0 = success
   - Qout.nc exists and is non-empty
   - Qout dimensions match expected (n_time × n_riv)

## RAPID Operational Modes

| IS_opt_run | Mode | Description |
|------------|------|-------------|
| 1 | Simulation | Standard routing (most common) |
| 2 | Optimization | Calibrate k, x using TAO against observed discharge |
| 3 | Data assimilation (forecast) | Kalman filter forecast phase |
| 4 | Data assimilation (analysis) | Kalman filter analysis phase |

## Verification

```bash
# Check output exists and has data
ncdump -h Qout.nc

python3 -c "
import netCDF4 as nc
d = nc.Dataset('Qout.nc')
q = d['Qout'][:]
print(f'Shape: {q.shape}')
print(f'Range: {q.min():.4f} to {q.max():.2f} m³/s')
print(f'Mean: {q.mean():.4f} m³/s')
print(f'NaN count: {(q != q).sum()}')
d.close()
"

# Quick sanity: peak discharge should be plausible for the basin size
# Rule of thumb: peak Q ≈ 0.1–10 × basin_area_km2 (m³/s)
```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| KSP diverged (dt_008) | FATAL | Muskingum instability — k too small for dtR or x > 0.5 |
| Segfault | FATAL | Usually mismatched IS_riv_tot/IS_max_up or corrupted connectivity |
| Namelist error | FATAL | Wrong syntax or missing required variables |
| Out of memory | FATAL | Too many reaches for available RAM — reduce np or use more nodes |
| Silent wrong results | SILENT | Model runs successfully but routing is wrong due to input errors |
| MPI not found | FATAL | PETSc requires MPI even for single-process runs |

## Example

```bash
# Set environment
export PETSC_DIR=/home/installz/petsc-3.13.6
export PETSC_ARCH=linux-gcc-c
export PATH=$PATH:$PETSC_DIR/$PETSC_ARCH/bin

# Run simulation
cd /path/to/run_dir
mpiexec -n 1 /path/to/src/rapid --namelist ./rapid_namelist

# Check results
ncdump -v Qout Qout.nc | tail -20
```

## Runtime Estimates

| Basin Size | Reaches | Time Steps | Processes | Runtime |
|-----------|---------|------------|-----------|---------|
| Small (San Guad) | 5,175 | 240 (30 days) | 1 | ~10 s |
| Medium (France) | 24,264 | 2,920 (1 year) | 4 | ~5 min |
| Continental (NHDPlus) | 2,600,000 | 2,920 | 64 | ~2 hours |
