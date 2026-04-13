# Skill: Model Execution

## Purpose

Run the openAMUNDSEN model, including initialization (grid loading, meteo reading,
state variable setup) and timestep iteration. Understand runtime behavior, memory
requirements, and common failure modes.

## Inputs

| Input | Format | Source |
|-------|--------|--------|
| Configuration file | YAML (.yml) | s3_configuration |
| DEM grid | Arc/Info ASCII (.asc) | s1_grid_setup |
| Meteo data | CSV or NetCDF | s2_meteo_forcing |

## Outputs

| Output | Format | Location |
|--------|--------|----------|
| Point time series | NetCDF or CSV | results_dir/ |
| Gridded fields | NetCDF, GeoTIFF, or ASCII | results_dir/ |
| Log output | Console (stderr) | stdout/stderr |

## Procedure

### Step 1: Preflight Check

Run the wrapper with dry-run mode first:
```bash
python run_openamundsen.py --config config.yml --dry-run
```

This validates:
- Config file parses correctly
- DEM file exists with correct naming
- Meteo directory contains data
- CRS, timestep, and lapse rates are reasonable

### Step 2: Run via CLI

```bash
openamundsen config.yml
```

Or via Python:
```python
import openamundsen as oa
config = oa.read_config("config.yml")
model = oa.OpenAmundsen(config)
model.initialize()
model.run()
```

### Step 3: Monitor Progress

openAMUNDSEN logs progress to stderr at INFO level. Key milestones:
- "Reading grid data..." — Loading DEM/ROI
- "Reading meteorological data..." — Loading station data
- "Processing timestep..." — Main loop started
- Monthly summary lines (SWE, precip totals)

### Step 4: Run with Logging

```bash
python run_openamundsen.py --config config.yml --log-file run.log
```

### Step 5: Verify Completion

Check that:
1. No Python exceptions in output
2. Results directory contains output files
3. Output time range matches config start/end dates

## Runtime Behavior

### Processing Steps Per Timestep

The model executes these steps for each timestep in order:

1. **Meteo interpolation**: Spatial interpolation of station data to grid (IDW + lapse rates)
2. **Precipitation correction**: Wind undercatch, snow redistribution
3. **Precipitation phase**: Determine rain/snow fraction per grid cell
4. **Radiation**: Clear-sky shortwave, terrain shadows, longwave
5. **Surface properties**: Update albedo, roughness length
6. **Snow model**: Mass/energy balance, layer updates
7. **Canopy** (if enabled): Interception, sublimation, unloading
8. **Evapotranspiration** (if enabled): FAO Penman-Monteith
9. **Output writing**: Append to NetCDF/CSV at specified frequency

### Memory Requirements

| Grid Size | ~Memory |
|-----------|---------|
| 100×100 (10,000 cells) | ~200 MB |
| 500×500 (250,000 cells) | ~2 GB |
| 1000×1000 (1,000,000 cells) | ~8 GB |

Memory scales with: grid_cells × num_snow_layers × num_state_variables.

### Performance

- Numba JIT compilation causes ~30s warmup on first run
- Subsequent timesteps are fast (~0.1–1s per step for 10k cells)
- Set `numba_threads: auto` for multi-core acceleration
- A full water year at hourly resolution ≈ 8,760 timesteps

## Verification

1. Check output files exist in results_dir
2. Open point output NetCDF — verify time dimension spans full period
3. Plot SWE time series — should show accumulation/ablation pattern
4. Check for NaN patches in gridded output (indicates failed interpolation)

## Traps

| Trap | Symptom | Fix | Diagnostic |
|------|---------|-----|------------|
| No stations within grid | Fatal error at init | Check station coords and CRS | dt_017 |
| Canopy enabled, no land cover | Warning, defaults used | Add land cover grid or disable | dt_018 |
| Snow model mismatch after calibration | Degraded accuracy | Re-calibrate for chosen model | dt_016 |
| All temps NaN (unit error) | Interpolation returns NaN everywhere | Fix input units (dt_001) | dt_001 |
| Huge memory with fine grid | OOM kill or swap thrashing | Reduce resolution or domain size | — |
| Numba compilation error | ImportError or JIT failure | Update numba: pip install -U numba | — |

## Example

Complete execution workflow:

```bash
# 1. Preflight check
python run_openamundsen.py --config config.yml --dry-run

# 2. Run model
openamundsen config.yml 2>&1 | tee run.log

# 3. Check results
ls -la output/
python parse_output.py --results-dir ./output --format csv
```

Python API for iterative runs:

```python
import openamundsen as oa

config = oa.read_config("config.yml")
model = oa.OpenAmundsen(config)
model.initialize()

# Run single timesteps for custom processing
for i in range(len(model.dates)):
    model.run_single()
    # Access state: model.state.snow.swe, model.state.meteo.temp, etc.
    if model.state.snow.swe.max() > 1000:
        print(f"Peak SWE > 1000 kg/m² at {model.date}")
```
