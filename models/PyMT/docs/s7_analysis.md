# Stage 7: Post-Processing and Analysis

## Purpose

Analyze and visualize model output after simulation completes. Includes
computing domain-appropriate metrics, creating diagnostic plots, and
comparing simulation results to observations.

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| Model output | CSV/NetCDF/arrays | Yes | Simulation results from Stage 4-5 |
| Observations | CSV/NetCDF | No | Field/lab data for validation |
| Metrics to compute | list | No | NSE, KGE, RMSE, PBIAS, etc. |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| Metrics | dict | Computed performance metrics |
| Figures | .png files | Diagnostic and validation plots |
| Summary report | text/JSON | Tabulated results |

## Procedure

### Step 1: Load Output Data
```python
import numpy as np
import pandas as pd

# From CSV
df = pd.read_csv("output.csv")

# From NetCDF
import xarray as xr
ds = xr.open_dataset("output.nc")
```

### Step 2: Compute Hydrological Metrics
```python
def nash_sutcliffe(obs, sim):
    """Nash-Sutcliffe Efficiency (-inf to 1, 1 is perfect)."""
    return 1.0 - np.sum((obs - sim) ** 2) / np.sum((obs - np.mean(obs)) ** 2)

def kge(obs, sim):
    """Kling-Gupta Efficiency (-inf to 1, 1 is perfect)."""
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)

def rmse(obs, sim):
    """Root Mean Square Error."""
    return np.sqrt(np.mean((obs - sim) ** 2))

def pbias(obs, sim):
    """Percent Bias (positive = model overestimates)."""
    return 100.0 * np.sum(sim - obs) / np.sum(obs)
```

### Step 3: Time Series Plot
```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(times_obs, obs_values, color="black", linewidth=1.5, label="Observed")
ax.plot(times_sim, sim_values, color="#2563EB", linewidth=1.0, label="Simulated")

# Metrics box
nse = nash_sutcliffe(obs_values, sim_values)
textstr = f"NSE = {nse:.3f}"
ax.text(0.98, 0.95, textstr, transform=ax.transAxes,
        fontsize=10, verticalalignment="top", horizontalalignment="right",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

ax.set_xlabel("Time")
ax.set_ylabel("Variable [units]")
ax.legend()
plt.tight_layout()
plt.savefig("validation.png", dpi=150)
```

### Step 4: Spatial Map Plot
```python
fig, ax = plt.subplots(figsize=(10, 8))

# Reshape flat array to grid
grid_id = model.var_grid("variable_name")
shape = model.grid_shape(grid_id)
data_2d = values.reshape(shape)

im = ax.imshow(data_2d, origin="lower", cmap="viridis")
plt.colorbar(im, ax=ax, label="Variable [units]")
ax.set_title("Spatial Distribution")
plt.savefig("spatial_map.png", dpi=150)
```

### Step 5: Summary Statistics
```python
summary = {
    "n_timesteps": len(times),
    "time_range": [float(min(times)), float(max(times))],
    "variables": {},
}

for var in captured_vars:
    vals = np.array(data[var])
    summary["variables"][var] = {
        "mean": float(np.mean(vals)),
        "std": float(np.std(vals)),
        "min": float(np.min(vals)),
        "max": float(np.max(vals)),
    }

import json
print(json.dumps(summary, indent=2))
```

## Verification

```python
# Output file exists
import os
assert os.path.exists("validation.png"), "Figure not created"

# Metrics are in valid range
assert -10 < nse <= 1.0, f"NSE out of range: {nse}"
assert rmse_val >= 0, f"RMSE negative: {rmse_val}"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Time unit mismatch | Obs and sim on different time axes | Convert both to same units before comparison |
| Spatial mismatch | Comparing grid-mean to point obs | Extract nearest grid point or area-average |
| All-zero output | NSE = -inf, KGE = -inf | Model likely not initialized or forcing not set |
| NaN in output | Metrics return NaN | Check for NaN with `np.isnan()` before computing |
| Wrong variable units | Metrics look reasonable but values are wrong | Always check `model.var_units()` |

## Example

```python
import numpy as np
import matplotlib.pyplot as plt

# Simulated data
times = np.arange(0, 365)
sim = 5.0 + 3.0 * np.sin(2 * np.pi * times / 365) + np.random.normal(0, 0.5, 365)
obs = 5.0 + 3.0 * np.sin(2 * np.pi * times / 365) + np.random.normal(0, 0.3, 365)

# Metrics
nse = 1.0 - np.sum((obs - sim) ** 2) / np.sum((obs - np.mean(obs)) ** 2)
r = np.corrcoef(obs, sim)[0, 1]

# Plot
fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(times, obs, "k-", label="Observed", linewidth=1.5)
ax.plot(times, sim, color="#2563EB", label="Simulated", linewidth=1.0)
ax.text(0.98, 0.95, f"NSE={nse:.3f}\nr={r:.3f}",
        transform=ax.transAxes, va="top", ha="right",
        bbox=dict(facecolor="wheat", alpha=0.5))
ax.legend()
ax.set_xlabel("Day of Year")
ax.set_ylabel("Value")
plt.tight_layout()
plt.savefig("validation.png", dpi=150)
print(f"NSE: {nse:.3f}, r: {r:.3f}")
```
