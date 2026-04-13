# Stage 5: Model Execution

## Purpose

Run the fully configured TopoFlow model via the EMELI framework, monitor for
errors, and capture output.  This stage covers three execution methods: Python
API, CLI, and NextGen integration.

## Inputs

| File                    | Required | Description                              |
|-------------------------|----------|------------------------------------------|
| `*_providers.txt`       | Yes      | Maps component types to implementations  |
| `*_topoflow.cfg`        | Yes      | Driver configuration (stop time, dt)     |
| `*_meteorology.cfg`     | Yes      | Meteorology component parameters         |
| `*_channels_*.cfg`      | Yes      | Channel routing parameters               |
| `*_infil_*.cfg`         | Yes      | Infiltration parameters                  |
| `*_snow_*.cfg`          | Yes      | Snow process parameters                  |
| `*_evap_*.cfg`          | Yes      | Evapotranspiration parameters            |
| `*_satzone_*.cfg`       | Yes      | Saturated zone parameters                |
| `*_outlets.txt`         | Yes      | Outlet pixel coordinates                 |
| DEM, D8, slope RTG files| Yes      | Domain grids                             |
| Met forcing files       | Yes      | Precipitation, temperature, etc.         |

## Outputs

| File                    | Format   | Description                              |
|-------------------------|----------|------------------------------------------|
| `*_0D-Q.txt`            | Text     | Outlet discharge time series (m³/s)      |
| `*_0D-d.txt`            | Text     | Outlet depth time series (m)             |
| `*_2D-Q.nc`             | NetCDF   | Spatiotemporal discharge grids           |
| `*_report.txt`          | Text     | Summary: peak Q, volumes, timing         |
| Console output          | Text     | Progress, warnings, final status         |

## Procedure

### Method 1: Python API (recommended)

```python
from topoflow.framework import emeli

f = emeli.framework()
f.run_model(
    driver_comp_name='topoflow_driver',
    cfg_prefix='June_20_67',
    cfg_directory='/path/to/Treynor_Iowa_30m/__No_Infil_June_20_67_Rain/',
)
```

### Method 2: CLI

```bash
python -m topoflow \
  --cfg_prefix=June_20_67 \
  --cfg_directory=/path/to/cfg/ \
  --driver_comp_name=topoflow_driver
```

### Method 3: Execution wrapper

```bash
python ki/tools/run_topoflow.py \
  --cfg_prefix June_20_67 \
  --cfg_directory /path/to/cfg/ \
  --driver_comp_name topoflow_driver \
  --timeout 3600
```

### Method 4: NextGen integration

```python
from topoflow import main2
main2.run_model(cat_id_str='cat-209', SILENT=False)
```

### Pre-run checklist

Before running, verify:

1. **All .cfg files exist** for every component listed in the provider file
2. **Provider component names are exact** (case-sensitive)
3. **All referenced data files exist** (DEM, slope, D8, met forcing)
4. **RTG grid dimensions match** the .rti header
5. **Outlet pixel is within grid bounds**
6. **Timesteps are reasonable** (channels dt ≈ 2–6 sec for 30m grids)
7. **Stop time is sufficient** for the event (check T_stop_model in driver .cfg)

### Monitoring during run

TopoFlow prints progress to the console:

```
Time [min] =   10.00,  Q_out =   0.0213 [m3/s]
Time [min] =   20.00,  Q_out =   0.5871 [m3/s]
...
Finished.  (03/25/2026  10:30:45)
```

Key indicators:
- **Q_out increasing** during rainfall: model is receiving forcing correctly
- **Q_out returning to zero** after rain stops: recession is working
- **"Finished." message**: run completed normally
- **"ERROR"** or traceback: failure requiring diagnosis

### Stopping criteria

Configured in `*_topoflow.cfg`:

| Method              | Parameter        | Description                       |
|---------------------|------------------|-----------------------------------|
| `Until_model_time`  | T_stop_model     | Stop at specified time [minutes]  |
| `Q_peak_fraction`   | Qp_fraction      | Stop when Q drops to fraction of peak |
| `Until_n_steps`     | n_steps          | Stop after N timesteps            |

### Typical run times

| Grid Size     | Duration      | Approx. Wall Time  | Notes                |
|---------------|---------------|---------------------|----------------------|
| 29×44 (30m)   | 250 min sim   | ~30 seconds         | Treynor test case    |
| 200×200 (30m) | 1 day sim     | ~5–15 minutes       | Small basin          |
| 500×500 (90m) | 1 year sim    | ~1–4 hours          | Medium basin         |

## Verification

1. **Exit status:** Run completed with "Finished." message
2. **Output files created:** At minimum, `*_0D-Q.txt` should exist
3. **Non-zero discharge:** Peak Q should be > 0 if there was precipitation
4. **Mass balance:** Total outflow volume ≈ total inflow − infiltration − ET
5. **No NaN/Inf values:** Check output files for corrupted data

```python
import numpy as np
q = np.loadtxt('June_20_67_0D-Q.txt')
assert np.all(np.isfinite(q)), "NaN or Inf in discharge output"
assert q.max() > 0, "Zero discharge — check forcing and infiltration"
```

## Traps

| Trap                              | Symptom                              | Fix                                |
|-----------------------------------|--------------------------------------|------------------------------------|
| Provider file has wrong comp name | EMELI crash: "component not found"   | Match exact name from SKILL §8     |
| Missing .cfg for a component      | EMELI crash at initialization        | Ensure all provider-listed cfgs exist |
| T_stop_model too short            | Run ends before peak flow            | Extend stop time                   |
| cfunits not installed             | Framework crash on unit conversion   | pip install cfunits                |
| Wrong cfg_directory path          | Files not found, crash               | Use absolute path                  |
| dt too large for grid spacing     | Oscillations or negative depth       | Reduce channel dt (CFL check)     |

## Example

Running the Treynor no-infiltration test:

```bash
cd topoflow/examples/Treynor_Iowa_30m/__No_Infil_June_20_67_Rain/
python -m topoflow \
  --cfg_prefix=June_20_67 \
  --cfg_directory=. \
  --driver_comp_name=topoflow_driver
```

Expected: Peak Q ≈ 3–5 m³/s at ~60–80 minutes into the simulation.
Run time: < 1 minute on modern hardware.
