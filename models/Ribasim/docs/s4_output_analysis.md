# Stage 4: Output Analysis and Validation

## Purpose

Parse Ribasim NetCDF outputs, compute water balance metrics, generate time
series plots, and optionally compare against observed data for model
calibration and validation.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| Basin results | NetCDF | `results/basin.nc` | Yes |
| Flow results | NetCDF | `results/flow.nc` | Optional |
| Basin state | NetCDF | `results/basin_state.nc` | Optional |
| Observed data | CSV | Field measurements | Optional |

## Outputs

| Output | Format | Path |
|--------|--------|------|
| Basin time series | CSV | User-specified |
| Flow time series | CSV | User-specified |
| Summary statistics | JSON | User-specified |
| Validation metrics | JSON (in summary) | User-specified |
| Plots | PNG/PDF | User-specified |

## Procedure

### Step 1: Read basin results

```python
import xarray as xr
import pandas as pd

ds = xr.open_dataset("results/basin.nc")

# Available variables (typical):
# - level: Water level (m)
# - storage: Water volume (m³)
# - precipitation: Precipitation flux (m³/s, basin-integrated)
# - evaporation: Evaporation flux (m³/s, basin-integrated)
# - drainage: Drainage flux (m³/s)
# - infiltration: Infiltration flux (m³/s)
# - inflow_rate: Total inflow (m³/s)
# - outflow_rate: Total outflow (m³/s)
# - storage_rate: dS/dt (m³/s)
# - balance_error: Water balance error (m³/s)
# - relative_error: Relative balance error (dimensionless)

# Extract time series for a specific basin
basin_1 = ds.sel(node_id=1)
level_ts = basin_1["level"].to_pandas()
```

### Step 2: Read flow results

```python
flow_ds = xr.open_dataset("results/flow.nc")

# flow_rate: Flow rate on each link (m³/s)
# Indexed by (time, link_id) or (time, from_node_id, to_node_id)

# Get flow on a specific link
link_flow = flow_ds["flow_rate"].sel(link_id=1).to_pandas()
```

### Step 3: Compute water balance

For each basin, verify:
```
dS/dt = P + D + Q_in - E - I - Q_out
```

Where:
- S = storage (m³)
- P = precipitation (m³/s, basin-integrated)
- D = drainage (m³/s)
- Q_in = total inflow (m³/s)
- E = evaporation (m³/s, basin-integrated)
- I = infiltration (m³/s)
- Q_out = total outflow (m³/s)

```python
# Check balance closure
balance_error = ds["balance_error"].sel(node_id=1)
relative_error = ds["relative_error"].sel(node_id=1)

print(f"Max absolute error: {abs(balance_error).max().values:.6f} m³/s")
print(f"Max relative error: {abs(relative_error).max().values:.6f}")
```

Acceptable thresholds:
- Absolute error: < solver abstol (default 1e-5 m³/s)
- Relative error: < solver reltol (default 1e-5)

### Step 4: Compare with observations

```python
import numpy as np

# Load observed levels
obs = pd.read_csv("observed_levels.csv", parse_dates=["time"])

# Extract simulated levels for the same basin
sim_level = ds["level"].sel(node_id=obs_node_id).to_pandas()

# Align time series
merged = pd.merge_asof(
    obs.sort_values("time"),
    sim_level.reset_index().rename(columns={"index": "time", 0: "sim_level"}),
    on="time",
    tolerance=pd.Timedelta("1D"),
)

# Compute metrics
obs_arr = merged["obs_level"].values
sim_arr = merged["sim_level"].values

# NSE
obs_mean = np.nanmean(obs_arr)
nse = 1 - np.nansum((obs_arr - sim_arr)**2) / np.nansum((obs_arr - obs_mean)**2)

# KGE
r = np.corrcoef(obs_arr, sim_arr)[0, 1]
alpha = np.std(sim_arr) / np.std(obs_arr)
beta = np.mean(sim_arr) / np.mean(obs_arr)
kge = 1 - np.sqrt((r-1)**2 + (alpha-1)**2 + (beta-1)**2)

# PBIAS
pbias = 100 * np.sum(sim_arr - obs_arr) / np.sum(obs_arr)

print(f"NSE: {nse:.3f}")
print(f"KGE: {kge:.3f}")
print(f"PBIAS: {pbias:.1f}%")
```

### Step 5: Generate plots

```python
import matplotlib.pyplot as plt

fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

# Level
ax = axes[0]
level.plot(ax=ax, color="#2563EB", label="Simulated")
if obs is not None:
    ax.scatter(obs["time"], obs["level"], c="black", s=5, label="Observed")
ax.set_ylabel("Level (m)")
ax.legend()

# Inflow/outflow
ax = axes[1]
ds["inflow_rate"].sel(node_id=1).plot(ax=ax, color="blue", label="Inflow")
ds["outflow_rate"].sel(node_id=1).plot(ax=ax, color="red", label="Outflow")
ax.set_ylabel("Flow (m³/s)")
ax.legend()

# Water balance error
ax = axes[2]
ds["relative_error"].sel(node_id=1).plot(ax=ax, color="orange")
ax.set_ylabel("Relative Error")
ax.axhline(0.01, color="red", linestyle="--", label="1% threshold")
ax.legend()

plt.tight_layout()
plt.savefig("model_results.png", dpi=150)
```

## Verification

1. Basin levels stay within profile range
2. Water balance error < tolerance for all basins
3. Flow rates are non-negative where expected (pumps, outlets)
4. Time series has the expected number of points
5. No NaN values in critical variables (level, storage)
6. If observed data available: NSE > 0 (better than mean)

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Output units | **SILENT** | Precipitation/evaporation in basin.nc are **basin-integrated** (m³/s), not per-area (m/s). Don't compare directly with input forcing. |
| saveat misinterpretation | **SILENT** | Output timestamps mark the **start** of the averaging period, not the end. |
| Missing variables | Warning | Not all variables are present in all outputs. Check `ds.data_vars` before accessing. |
| Large files | Performance | For long simulations or many nodes, NetCDF files can be >1 GB. Use `sel()` to subset before loading. |
| Time zone | **SILENT** | Ribasim uses UTC. If observations are in local time, shift before comparing. |

## Example

```bash
# Quick output check
python -c "
import xarray as xr
ds = xr.open_dataset('results/basin.nc')
print('=== Basin Output Summary ===')
print(f'Time range: {ds.time.values[0]} to {ds.time.values[-1]}')
print(f'Timesteps: {ds.dims[\"time\"]}')
for var in ds.data_vars:
    print(f'{var}: min={ds[var].min().values:.4g}, max={ds[var].max().values:.4g}')
ds.close()
"
```
