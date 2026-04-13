# Stage 4: Model Execution

## Purpose

Run the LPJmL binary with proper environment setup, managing the two-step simulation protocol (spinup + transient). Monitor for errors, balance violations, and performance issues.

## Inputs

| Input | Description |
|-------|-------------|
| `bin/lpjml` | Compiled LPJmL binary |
| `lpjml_config.cjson` | Configuration file |
| Climate CLM files | Prepared forcing data |
| Soil/land-use files | Prepared static inputs |
| CO2 text file | Annual atmospheric CO2 (ppm) |

## Outputs

| Output | Description |
|--------|-------------|
| Restart file (`*.lpj`) | Binary state for continuing simulation |
| Output files (`output/*.bin`) | Raw binary time series |
| Globalflux CSV | Global carbon/water budget summary |

## Procedure

### Step 1: Spinup (natural vegetation)

```bash
# Set environment
export LPJROOT=$(pwd)
export LPJINPATH=/path/to/input/data

# Create directories
mkdir -p output restart

# Run spinup (~4000 years, no land use)
./bin/lpjml lpjml_config.cjson
```

Expected behavior:
- Runs for ~4000 years cycling 30-year climate
- Soil carbon reaches equilibrium
- Vegetation composition stabilizes
- Runtime: minutes (single grid cell) to hours (global)
- Creates restart file at year 1700

### Step 2: Transient run (with land use)

```bash
# Run transient from restart
./bin/lpjml -DFROM_RESTART lpjml_config.cjson
```

Expected behavior:
- Reads restart file from spinup
- Additional 420-year spinup with nitrogen cycling
- Simulation from 1901-2019 with historical land use
- Outputs written from outputyear (1901)

### Parallel execution (MPI)

```bash
# Build with MPI
./configure.sh
make

# Run on 32 cores
mpirun -np 32 ./bin/lpjml -DFROM_RESTART lpjml_config.cjson

# Or use SLURM
bin/lpjsubmit 32 -DFROM_RESTART lpjml_config.cjson
```

## Verification

### During run
- Monitor stdout for year-by-year progress messages
- Check for ERROR messages (format: `ERRORxxx: message`)
- Monitor memory usage (global run needs ~2 GB per process)

### After run
- Check output files exist and have expected sizes
- Inspect `output/globalflux.csv` for global carbon balance
- Verify restart file was created
- Run `bin/lpjprint restart/restart_file.lpj` to inspect restart contents

### Key diagnostics from globalflux.csv

| Column | Variable | Expected Range |
|--------|----------|----------------|
| NEE | Net Ecosystem Exchange | ±5 GtC/yr |
| NPP | Net Primary Production | 40-80 GtC/yr globally |
| Rh | Heterotrophic respiration | 40-80 GtC/yr globally |
| Fire | Fire emissions | 1-4 GtC/yr |
| Discharge | Global discharge | ~35,000-45,000 km3/yr |

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| ERROR001 | Configuration parse error | Run `lpjcheck` first |
| ERROR002 | Missing input file | Check paths with `lpjfiles` |
| ERROR004 | Carbon balance violation | Check input data quality; try CHECK_BALANCE flag |
| ERROR005 | Water balance violation | Check precipitation units; disable reservoir if needed |
| ERROR009 | Out of memory | Reduce grid size or use MPI |
| ERROR015 | Invalid CO2 year | Extend CO2 file or adjust firstyear |
| ERROR037 | Nitrogen balance | Check fertilizer/manure inputs |
| ERROR038 | Invalid climate data | Check for NaN/missing values in forcing |
| Slow spinup | Taking hours for single cell | Normal — 4000 years takes time |
| Core dump | Segfault during run | Compile with -DSAFE -DCHECK_BALANCE for diagnostics |

## Example

```bash
# Full workflow
cd /path/to/lpjml
export LPJROOT=$(pwd)
export LPJINPATH=/data/lpjml_inputs

# Step 1: Spinup
./bin/lpjml lpjml_config.cjson 2>&1 | tee spinup.log

# Check spinup completed
ls -la restart/restart_1700_nv_stdfire.lpj

# Step 2: Transient
./bin/lpjml -DFROM_RESTART lpjml_config.cjson 2>&1 | tee transient.log

# Check outputs
ls -la output/
head output/globalflux.csv
```

## Performance Notes

| Configuration | Typical Runtime |
|---------------|----------------|
| Single cell, spinup (4000yr) | 1-5 minutes |
| Global (67420 cells), spinup | 4-12 hours (32 cores) |
| Global, transient (119yr) | 1-3 hours (32 cores) |
| Regional (1000 cells), both | 10-30 minutes |
