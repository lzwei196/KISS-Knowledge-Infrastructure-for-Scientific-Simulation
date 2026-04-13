# Stage 4: Model Execution

## Purpose

Run the COSIPY energy and mass balance model, managing the Dask distributed computing framework, and produce output/restart netCDF files.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Forcing netCDF | Stage 2 output | netCDF4 |
| Static file | Stage 1 output | netCDF4 (embedded in forcing or separate) |
| `config.toml` | Stage 0 | TOML |
| `constants.toml` | Stage 3 | TOML |
| Restart file (optional) | Previous run | netCDF4 |

## Outputs

| Output | Path | Format |
|--------|------|--------|
| Result netCDF | `data/output/<prefix>_<start>-<end>.nc` | netCDF4 |
| Restart file | `data/restart/restart_<timestamp>.nc` | netCDF4 |
| Stake statistics (optional) | `data/output/stake_statistics.csv` | CSV |
| Stake simulations (optional) | `data/output/stake_simulations.csv` | CSV |

## Procedure

### Running the model

```bash
# Default (uses config files in current directory)
python COSIPY.py

# Custom config paths
python COSIPY.py -c path/to/config.toml -x path/to/constants.toml

# With SLURM scheduler
python COSIPY.py -s path/to/slurm_config.toml

# Using entry point (after pip install)
cosipy-run
```

### Using KI execution wrapper

```bash
python ki/tools/run_cosipy.py \
    --config config.toml \
    --constants constants.toml \
    --source-dir /path/to/cosipy/source

# Preflight checks only (no execution)
python ki/tools/run_cosipy.py --preflight-only
```

### Execution flow

1. Load config.toml and constants.toml
2. Read input netCDF (forcing + static variables)
3. Initialize result and restart datasets
4. Start Dask cluster (LocalCluster or SLURMCluster)
5. For each grid cell where MASK=1:
   - Submit `cosipy_core()` to Dask worker
   - Process physical modules in sequence (per timestep):
     - Fresh snow density calculation
     - Snow/rain partitioning
     - Grid update (layer merging)
     - Albedo and roughness update
     - Surface energy balance (solve for surface temperature)
     - Mass fluxes (melt, sublimation, evaporation)
     - Percolation and refreezing
     - Heat equation
     - Densification
     - Mass balance computation
6. Collect results from all workers
7. Write output and restart netCDF files

### Parallelism

- Each grid cell is processed independently on a separate Dask worker
- No inter-cell communication (1D vertical model)
- Typical throughput: 10-100 grid-cell-years per second per core

### Runtime expectations

| Configuration | Grid size | Period | Runtime |
|---------------|-----------|--------|---------|
| Point model | 1x1 | 10 days | ~5-10 seconds |
| Point model | 1x1 | 1 year | ~30-60 seconds |
| Distributed | 7x13 (15 glacier cells) | 10 days | ~30 seconds |
| Distributed | 7x13 | 1 year | ~5-15 minutes |
| Large glacier | 50x50 | 1 year | ~1-4 hours |

## Verification

```bash
# Check output file exists and has data
python -c "
import xarray as xr, os, glob
output_dir = 'data/output/'
nc_files = glob.glob(os.path.join(output_dir, '*.nc'))
for f in nc_files:
    ds = xr.open_dataset(f)
    print(f'File: {f}')
    print(f'  Time steps: {ds.dims[\"time\"]}')
    print(f'  Variables: {len(ds.data_vars)}')
    if 'MB' in ds:
        import numpy as np
        print(f'  MB range: {float(ds.MB.min()):.4f} to {float(ds.MB.max()):.4f} m w.e.')
    ds.close()
"
```

## Traps

1. **Dask port conflict**: Default port 8786. If another process uses this port, COSIPY hangs at "Starting clients and submitting jobs". Change `local_port` in config.toml.

2. **NaN in input data**: COSIPY crashes with "ERROR! There are NaNs in the dataset" if any forcing variable has NaN in glacier cells. Fix the input data, don't try to catch the error.

3. **Memory exhaustion**: Each worker processes one grid cell for the entire time series. For very long simulations (10+ years), memory per worker can exceed available RAM. Reduce workers count or split the simulation period.

4. **Restart file path**: Restart files are stored in `<data_path>/restart/restart_<time_start>.nc`. The timestamp must exactly match `time_start` in config.toml. Mismatched timestamps cause "No restart file available" error.

5. **Output compression**: Set `compression_level` 1-3 in config.toml. Higher values (>3) dramatically increase write time with marginal size reduction.

6. **WRF_X_CSPY mode**: Interactive coupling with WRF. Should NOT be enabled for standalone simulations. It changes albedo method, forces full_field output, and modifies return values.

## Example

```bash
# Complete execution workflow
cd /path/to/cosipy/source

# 1. Preflight check
python ki/tools/run_cosipy.py --preflight-only

# 2. Run model
python COSIPY.py

# 3. Check output
ls data/output/*.nc
python ki/tools/parse_output.py -i data/output/Zhadang_ERA5_20090101-20090110.nc --mode summary
```
