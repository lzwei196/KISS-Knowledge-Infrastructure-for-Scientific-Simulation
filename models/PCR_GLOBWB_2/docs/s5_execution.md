# Stage 5/6: Model Execution (Spin-up and Transient Run)

## Purpose

Execute PCR-GLOBWB 2 including optional spin-up for state variable initialization and the main transient simulation. The model is run via `deterministic_runner.py` which handles the PCRaster DynamicFramework loop.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Configuration .ini | INI text | Complete model configuration |
| Clone map | PCRaster .map | Local spatial extent file |
| Forcing data | NetCDF | Precipitation, temperature, reference ET |
| Parameter data | NetCDF | Soil, topography, groundwater, land cover, routing |
| Initial conditions | NetCDF | State variables (optional — use spin-up if unavailable) |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| NetCDF time series | outputDir/netcdf/ | Discharge, runoff, ET, storage, etc. |
| End states | outputDir/states/ | PCRaster maps for restart |
| Log files | outputDir/log/ | Execution logs |
| Script backup | outputDir/scripts/ | Copy of model scripts |

## Procedure

### Step 1: Spin-up (optional but recommended)

Set in `[globalOptions]`:
```ini
maxSpinUpsInYears = 20        # Number of spin-up cycles
minConvForSoilSto = 0.0       # Convergence threshold for soil storage
minConvForGwatSto = 0.0       # Convergence threshold for GW storage
minConvForChanSto = 0.0       # Convergence threshold for channel storage
minConvForTotlSto = 0.0       # Convergence threshold for total storage
```

- Spin-up repeats the simulation period cyclically
- Each cycle uses the end state of the previous cycle as initial condition
- Convergence is checked by comparing beginning and end states
- Set convergence thresholds > 0 to enable automatic convergence detection
- Typical spin-up: 5-30 years for regional, 50+ years for global

### Step 2: Transient Run

```bash
cd model/
python deterministic_runner.py /path/to/setup.ini
```

The model executes:
1. Parse configuration
2. Create output directories (netcdf/, states/, log/, maps/, tmp/)
3. Run spin-up cycles (if maxSpinUpsInYears > 0)
4. Run transient simulation from startTime to endTime
5. Write outputs at each timestep (daily) and at configured intervals

### Step 3: Monitor Execution

- Check `outputDir/log/*.log` for progress and errors
- Monitor `outputDir/netcdf/` for growing output files
- Memory usage: ~2-4 GB for Rhine-Meuse at 5 arcmin, ~50-100 GB for global

### Parallel Execution (Global Runs)

For global 5 arcmin runs, split into subdomains:
```bash
# Each clone has its own .ini file
for clone_id in 01 02 03 ... 53; do
    python deterministic_runner.py setup_clone_${clone_id}.ini &
done
wait
# Merge results
python merge_netcdf.py
```

## Verification

- [ ] Log file shows "Transient simulation run started"
- [ ] No ERROR messages in log
- [ ] NetCDF output files created in outputDir/netcdf/
- [ ] State files created in outputDir/states/
- [ ] Discharge values > 0 at river outlets
- [ ] Water balance closure (check debug output)

## Traps

| Trap ID | Symptom | Root Cause | Fix |
|---------|---------|-----------|-----|
| dt_010 | Crash on startup | Clone map on OPeNDAP | Move to local path |
| dt_012 | "Only daily timestep" error | Non-daily timestep in .ini | Set timeStep=1.0 |
| dt_013 | Non-converging spin-up | Too few cycles or wrong thresholds | Increase maxSpinUpsInYears |
| dt_014 | Very slow execution | All data via OPeNDAP | Download inputs locally |
| dt_015 | Memory error | Global run on single machine | Split into clones |

## Example

```bash
# Activate environment
conda activate pcrglobwb_python3

# Run Rhine-Meuse at 5 arcmin (2000-2010)
cd /path/to/PCR-GLOBWB_model/model/
python deterministic_runner.py ../config/setup_05min.ini

# With debug mode
python deterministic_runner.py ../config/setup_05min.ini debug

# With custom output directory
python deterministic_runner.py ../config/setup_05min.ini normal --output_dir /scratch/custom_output/
```

### Runtime Expectations

| Domain | Resolution | Period | Approximate Runtime |
|--------|-----------|--------|-------------------|
| Rhine-Meuse | 5 arcmin | 10 years | 1-4 hours (OPeNDAP) / 10-30 min (local) |
| Global | 30 arcmin | 10 years | 2-8 hours |
| Global | 5 arcmin | 10 years | Days-weeks (parallel recommended) |
| Africa (30sec) | 30 arcsec | 10 years | Weeks (HPC required) |
