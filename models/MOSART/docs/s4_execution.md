# Stage 4: Model Execution

## Purpose

Run the mosartwmpy simulation using the BMI (Basic Model Interface). This stage initializes the model with the configuration file, advances through all timesteps, and writes output/restart files.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| `config.yaml` | Stage 3 | Simulation configuration |
| Grid file | Stage 2 | Domain grid NetCDF |
| Runoff forcing | Stage 1 | Runoff NetCDF |
| Demand file | External | Water demand (if WM enabled) |
| Reservoir files | External | Reservoir parameters (if WM enabled) |

## Outputs

| Output | Format | Location | Description |
|--------|--------|----------|-------------|
| Output NetCDF | `{name}_{year}_{month}.nc` | `output/{name}/` | Daily-averaged gridded results |
| Restart files | `{name}_restart_{date}.nc` | `output/{name}/restart_files/` | Full state snapshot |
| Log file | `mosartwmpy.log` | `output/{name}/` | Simulation log |
| Config copy | `config.yaml` | `output/{name}/` | Configuration archive |

## Procedure

### Method 1: Python script (recommended for automation)

```python
from mosartwmpy import Model

model = Model()
model.initialize('config.yaml')
model.update_until(model.get_end_time())
model.finalize()
```

### Method 2: Step-by-step execution

```python
from mosartwmpy import Model

model = Model()
model.initialize('config.yaml')

# Run one timestep at a time for fine control
while model.get_current_time() < model.get_end_time():
    # Optionally modify state before each step
    model.update()

    # Access current state
    discharge = model.get_value_ptr(
        'outgoing_water_volume_transport_along_river_channel')
    print(f"Max discharge: {discharge[~np.isnan(discharge)].max():.1f} m3/s")

model.finalize()
```

### Method 3: Using the KI execution wrapper

```bash
python ki/tools/run_mosartwmpy.py --config config.yaml
python ki/tools/run_mosartwmpy.py --config config.yaml --dry-run  # preflight only
```

### Method 4: Coupled with external model

```python
from mosartwmpy import Model
import numpy as np

model = Model()
model.initialize('config.yaml')

# Set runoff from external model (BMI input)
# Note: BMI input expects mm/s, internally converted to m3/s
runoff = np.zeros(model.get_grid_size())
runoff[100] = 0.001  # 1 mm/s at cell 100

model.set_value('surface_runoff_flux', runoff)
model.update()
```

## Timestep Structure

```
For each timestep (10800s default):
  _prepare()                    # Reset accumulators, handle floods, unit conversion
  for subcycle in range(3):     # 3 subcycles (3600s each)
    hillslope_routing()         # Overland flow on each cell
    for iteration in range(5):  # 5 routing iterations (720s each)
      subnetwork_irrigation()   # Extract from tributaries for demand
      subnetwork_routing()      # Route through tributaries
      upstream_accumulation()   # Pass flow downstream
      main_channel_routing()    # Kinematic wave in main channel
      main_channel_irrigation() # Extract from main channel for demand
      regulation()              # Apply reservoir release rules
    extraction_regulated_flow() # Allocate supply from reservoirs
  _finalize()                   # Average, compute storage, convert units back
```

## Verification

- [ ] Output directory created with NetCDF files
- [ ] No `ERROR` messages in `mosartwmpy.log`
- [ ] Output variables have physically reasonable values:
  - Discharge: 0 to ~1e5 m³/s for CONUS rivers
  - Storage: 0 to ~1e12 m³ for large basins
  - Supply: 0 to ~1e3 m³/s per cell
- [ ] Restart file written at simulation end
- [ ] Runtime reasonable (~5-30 min for 1 month CONUS at 1/8°)

## Traps

### TRAP 1: numba JIT compilation slow on first run
**Symptom**: Model appears hung for 30-60 seconds at start.
**Diagnosis**: numba compiles JIT functions on first call; cached for subsequent runs.
**Prevention**: This is normal. Set `cache=True` (already done in source). The `.nbi` cache files speed up subsequent runs.

### TRAP 2: Memory error on large grids
**Symptom**: `MemoryError` during initialization or first timestep.
**Diagnosis**: Full CONUS grid at 1/8° is ~100k cells with many state arrays.
**Prevention**: Use `grid.subdomain` to limit to basins of interest. Each cell uses ~200 float64 values (~1.6 KB), so 100k cells ≈ 160 MB per state array.

### TRAP 3: RunoffFile time bounds mismatch
**Symptom**: `ValueError: Current simulation date not within time bounds`.
**Diagnosis**: Simulation period extends beyond runoff file coverage.
**Prevention**: Ensure runoff files cover `start_date` through `end_date`. For multi-file input, ensure all {Y}/{M}/{D} combinations exist.

### TRAP 4: All output values are zero
**Symptom**: NetCDF output has all-zero variables.
**Diagnosis**: Usually runoff input is zero (wrong file) or grid mask excludes all cells.
**Prevention**: Check `mosart_mask > 0` count in grid file. Verify runoff file has non-zero values at grid locations.

### TRAP 5: numpy 2.0 incompatibility
**Symptom**: `AttributeError` or `TypeError` during numba compilation.
**Diagnosis**: mosartwmpy requires numpy<2.0 due to numba API changes.
**Prevention**: Pin numpy: `pip install "numpy>=1.20,<2.0"`.

## Example

```python
# Complete execution with timing
import time
from mosartwmpy import Model

t0 = time.time()
model = Model()
model.initialize('config.yaml')
print(f"Init: {time.time()-t0:.1f}s")

t1 = time.time()
model.update_until(model.get_end_time())
print(f"Run: {time.time()-t1:.1f}s")

model.finalize()
print(f"Total: {time.time()-t0:.1f}s")
```
