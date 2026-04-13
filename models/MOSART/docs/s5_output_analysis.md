# Stage 5: Output Analysis and Validation

## Purpose

Parse, visualize, and validate mosartwmpy simulation output. Extract time series at specific locations, compute basin-scale statistics, and compare against observations or reference simulations using NMAE, NSE, KGE, and PBIAS metrics.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Output NetCDF files | Stage 4 | Gridded daily-averaged results |
| Observation data (optional) | USGS/GRDC | Streamflow gauge records |
| Validation dataset (optional) | `mosartwmpy.download` | Reference 1981-1982 results |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Time series CSV | CSV | Extracted discharge/storage at points or basins |
| Validation figure | PNG | Observed vs. simulated with metrics |
| Statistics summary | JSON | NSE, KGE, PBIAS, NMAE, correlation |

## Procedure

### Step 1: Load output files

```python
import xarray as xr

# Load all monthly output files
ds = xr.open_mfdataset('./output/tutorial/*.nc')
print(ds)
```

### Step 2: Extract discharge at a gauge location

```python
# Portland, OR area (Columbia River)
discharge = ds['RIVER_DISCHARGE_OVER_LAND_LIQ'].sel(
    lat=45.52, lon=-122.68, method='nearest')
df = discharge.to_dataframe()
```

### Step 3: Compare with observations

```python
import numpy as np
import pandas as pd

# Load observed streamflow (e.g., USGS)
obs = pd.read_csv('observed_discharge.csv', index_col='date', parse_dates=True)

# Merge on time
merged = pd.merge(
    df.reset_index()[['time', 'RIVER_DISCHARGE_OVER_LAND_LIQ']],
    obs.reset_index(),
    left_on='time', right_on='date',
)
sim = merged['RIVER_DISCHARGE_OVER_LAND_LIQ'].values
obs_vals = merged['discharge_m3s'].values
```

### Step 4: Compute validation metrics

```python
def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    return 1.0 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

def compute_kge(obs, sim):
    """Kling-Gupta Efficiency."""
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return 1.0 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

def compute_pbias(obs, sim):
    """Percent Bias."""
    return 100.0 * np.sum(sim - obs) / np.sum(obs)

def compute_nmae(obs, sim):
    """Normalized Mean Absolute Error (%)."""
    return 100.0 * np.sum(np.abs(sim - obs)) / np.sum(obs)

nse = compute_nse(obs_vals, sim)
kge = compute_kge(obs_vals, sim)
pbias = compute_pbias(obs_vals, sim)
```

### Step 5: Create validation figure

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(merged['time'], obs_vals, color='black', linewidth=1.5, label='Observed')
ax.plot(merged['time'], sim, color='#2563EB', linewidth=1.0, label='Simulated')
ax.set_xlabel('Date')
ax.set_ylabel('Discharge (m³/s)')
ax.set_title('MOSART-WM Discharge Validation')
ax.legend()

# Add metrics box
textstr = f'NSE = {nse:.3f}\nKGE = {kge:.3f}\nPBIAS = {pbias:.1f}%'
props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
ax.text(0.98, 0.98, textstr, transform=ax.transAxes,
        verticalalignment='top', horizontalalignment='right',
        bbox=props, fontsize=10)

fig.tight_layout()
fig.savefig('validation.png', dpi=150)
```

### Step 6: Built-in validation (reference comparison)

```bash
# Download validation data
python -m mosartwmpy.download   # Select option 3 (validation)

# Run simulation for 1981-1982
# Then compare with reference:
python -m mosartwmpy.validate
```

## Verification

- [ ] Time series extracted at correct location (check lat/lon in output)
- [ ] Units consistent: output discharge in m³/s, observations in m³/s
- [ ] NSE > 0.5 for well-calibrated simulation
- [ ] KGE > 0.5 for well-calibrated simulation
- [ ] |PBIAS| < 25% for reasonable water balance
- [ ] NMAE = 0% for validation against reference (unmodified code)
- [ ] Figures show reasonable hydrograph shape (peaks, baseflow)

## Traps

### TRAP 1: Comparing wrong variable
**Symptom**: Metrics are nonsensical (negative NSE, huge PBIAS).
**Diagnosis**: `RIVER_DISCHARGE_OVER_LAND_LIQ` (total basin outflow) vs `channel_outflow` (single cell outflow) — they mean different things.
**Prevention**: `RIVER_DISCHARGE_OVER_LAND_LIQ` = `runoff_land` = basin-derived flow. Use this for comparison with streamflow gauges.

### TRAP 2: Time alignment mismatch
**Symptom**: Scatter plot shows no correlation despite reasonable hydrographs.
**Diagnosis**: Observed data in local time, model output in UTC, or off-by-one day.
**Prevention**: Always normalize time indices before merging. Model outputs daily averages with time stamp at end of averaging period.

### TRAP 3: Spatial resolution mismatch with gauge
**Symptom**: Simulated discharge is a fraction of observed.
**Diagnosis**: Gauge is on a river that's sub-grid scale, or grid cell doesn't capture the full upstream area.
**Prevention**: Compare `areaTotal2` at the nearest grid cell with the gauge's documented drainage area.

### TRAP 4: Water management masking natural flow
**Symptom**: Simulated flow is highly regulated (flat), observed is natural.
**Diagnosis**: Model includes reservoir operations but gauge measures natural flow (or vice versa).
**Prevention**: Run with `water_management.enabled: false` for comparison with naturalized flow records.

### TRAP 5: Output averaging artifacts
**Symptom**: Peak flows appear dampened compared to observations.
**Diagnosis**: Output is daily-averaged (86400s resolution) while observations may be instantaneous.
**Prevention**: Expected behavior. For peak analysis, reduce `output_resolution` or access state directly during simulation.

## Example

```python
# Using KI output parser
from ki.tools.parse_mosart_output import parse_output

result = parse_output(
    input_dir='./output/tutorial/',
    output_path='./discharge_portland.csv',
    variable='RIVER_DISCHARGE_OVER_LAND_LIQ',
    mode='point',
    lat=45.52, lon=-122.68,
)
print(result['stats'])
```
