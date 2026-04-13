# S7: Output Analysis

## Purpose

Parse, validate, and analyze ADCIRC simulation output files. Extract time series at specific locations, compute maximum inundation maps, compare with observations, and generate publication-quality figures. This stage transforms raw ADCIRC binary/ASCII output into actionable scientific results.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Elevation output | S6 | `fort.63` / `.nc` | Water surface elevation time series |
| Velocity output | S6 | `fort.64` / `.nc` | Depth-averaged velocity time series |
| Max elevation | S6 | `maxele.63` / `.nc` | Peak water level at each node |
| Station data | S6 | `fort.61` / `.nc` | Elevation at recording stations |
| Observations | NOAA CO-OPS, USGS | CSV | Observed water levels, high-water marks |
| Grid file | S1 | `fort.14` | Node coordinates for spatial reference |

## Outputs

| Output | File | Format | Description |
|--------|------|--------|-------------|
| Time series CSV | `results.csv` | CSV | Extracted data at specified locations |
| Summary statistics | `results_summary.json` | JSON | Min, max, mean, percentiles |
| Inundation map | `maxele_map.png` | PNG | Spatial plot of maximum water levels |
| Station comparison | `station_comparison.png` | PNG | Observed vs simulated time series |
| Metrics | `metrics.json` | JSON | R², RMSE, bias, peak error |

## Procedure

### 1. Extract Time Series at Stations

```bash
# Extract elevation at specific lat/lon locations
python ki/tools/parse_adcirc_output.py \
    --work_dir ./run \
    --format ascii \
    --output_csv stations.csv \
    --variables elevation \
    --stations "29.95,-90.07;30.03,-89.93;29.37,-89.42"
```

The tool finds the nearest mesh node to each specified coordinate and extracts the full time series.

### 2. Parse Maximum Elevation

```bash
# Extract maxele for all nodes
python ki/tools/parse_adcirc_output.py \
    --work_dir ./run \
    --format ascii \
    --output_csv maxele.csv \
    --variables maxele
```

### 3. Compute Validation Metrics

For storm surge validation, standard metrics include:

| Metric | Formula | Target |
|--------|---------|--------|
| RMSE | √(Σ(sim-obs)²/n) | < 0.3 m for tides, < 0.5 m for surge |
| Bias | Σ(sim-obs)/n | < ±0.1 m |
| Peak error | max(sim) - max(obs) | < ±0.3 m |
| R² | 1 - SS_res/SS_tot | > 0.9 for tides, > 0.8 for surge |
| Timing error | t_peak(sim) - t_peak(obs) | < 1 hour |

```python
import numpy as np

def compute_metrics(observed, simulated):
    """Compute standard validation metrics."""
    obs = np.array(observed)
    sim = np.array(simulated)
    mask = ~np.isnan(obs) & ~np.isnan(sim)
    obs, sim = obs[mask], sim[mask]

    rmse = np.sqrt(np.mean((sim - obs) ** 2))
    bias = np.mean(sim - obs)
    r2 = 1 - np.sum((sim - obs)**2) / np.sum((obs - np.mean(obs))**2)
    peak_error = np.max(sim) - np.max(obs)

    return {
        "rmse_m": round(rmse, 4),
        "bias_m": round(bias, 4),
        "r2": round(r2, 4),
        "peak_error_m": round(peak_error, 4),
        "n_points": len(obs),
    }
```

### 4. Generate Figures

```python
import matplotlib.pyplot as plt
import numpy as np

# Station comparison plot
fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(obs_time, obs_elev, 'k-', label='Observed', linewidth=1.5)
ax.plot(sim_time, sim_elev, color='#2563EB', label='Simulated', linewidth=1.2)
ax.set_xlabel('Time')
ax.set_ylabel('Water Level (m)')
ax.legend()
ax.set_title('ADCIRC vs Observed: Station 8761724')

# Metrics annotation
metrics_text = f"RMSE = {rmse:.3f} m\nBias = {bias:.3f} m\nR² = {r2:.3f}"
ax.text(0.98, 0.95, metrics_text, transform=ax.transAxes,
        verticalalignment='top', horizontalalignment='right',
        bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

plt.tight_layout()
plt.savefig('station_comparison.png', dpi=150)
```

### 5. Inundation Mapping

```python
# Plot maxele on the mesh
from matplotlib.tri import Triangulation

# Read mesh coordinates and maxele
# ...
tri = Triangulation(lon, lat, elements)
fig, ax = plt.subplots(figsize=(10, 8))
tc = ax.tripcolor(tri, maxele, cmap='YlOrRd', vmin=0, vmax=5)
plt.colorbar(tc, label='Maximum Elevation (m)')
ax.set_xlabel('Longitude')
ax.set_ylabel('Latitude')
ax.set_title('Maximum Storm Surge (m above geoid)')
plt.savefig('maxele_map.png', dpi=150)
```

## Verification

```bash
# Check output file sizes (should be > 0)
ls -lh fort.63 fort.64 maxele.63

# Check for reasonable elevation values
python3 -c "
import json
with open('results_summary.json') as f:
    s = json.load(f)
for stat in s.get('statistics', []):
    print(f\"{stat['variable']}: min={stat['min']}, max={stat['max']}\")
    if 'warning' in stat:
        print(f'  WARNING: {stat[\"warning\"]}')
"

# Compare number of output timesteps with expected
python3 -c "
rnday = 30; dtdp = 2.0; nspoolge = 360
expected_snaps = int(rnday * 86400 / dtdp / nspoolge)
print(f'Expected output snapshots: {expected_snaps}')
"
```

## Traps

| Trap | ID | Symptom |
|------|----|---------|
| Dry node sentinel (-99999) not filtered | — | Statistics polluted by sentinel values |
| Time reference confusion (days vs seconds) | dt_015 | X-axis of plots is wrong |
| Station too far from nearest node | — | Extracted values not representative |
| Output format mismatch (ASCII vs netCDF) | — | Parser fails to read file |
| Large output files fill disk | — | Partial/corrupt output |

## Example

```bash
# Complete output analysis pipeline
cd /path/to/run_dir

# 1. Parse to CSV
python ki/tools/parse_adcirc_output.py \
    --work_dir . --format ascii \
    --output_csv results.csv \
    --variables elevation,velocity,maxele \
    --stations "29.95,-90.07;30.03,-89.93"

# 2. Review summary
cat results_summary.json | python3 -m json.tool

# 3. Quick plot
python3 -c "
import pandas as pd
import matplotlib.pyplot as plt
df = pd.read_csv('results.csv')
fig, ax = plt.subplots()
ax.plot(df['time_s']/3600, df.iloc[:,4], color='#2563EB')
ax.set_xlabel('Time (hours)')
ax.set_ylabel('Elevation (m)')
plt.savefig('quick_timeseries.png', dpi=150)
print('Saved quick_timeseries.png')
"
```
