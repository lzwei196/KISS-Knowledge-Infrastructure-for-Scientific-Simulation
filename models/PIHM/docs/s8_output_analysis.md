# S8: Output Analysis Skill

## Purpose

Parse MM-PIHM binary output files, extract key hydrologic variables, compute
performance metrics, and generate diagnostic visualizations. This stage
transforms raw binary `.dat` files into interpretable time series and maps.

## Prerequisites

- Completed PIHM simulation (S7) with output files
- Python 3 with numpy, pandas, matplotlib (or PIHM-utils package)
- Observed data for validation (if computing metrics)

## Inputs

| Input | Description |
|-------|-------------|
| Binary output files | `output/<run>/*.dat` |
| Project name | Used to construct file names |
| Mesh file | `input/<project>/<project>.mesh` (for spatial mapping) |
| Observed data | Optional, for metric computation |

## Outputs

| Output | Description |
|--------|-------------|
| CSV time series | Extracted variables with timestamps |
| Performance metrics | NSE, KGE, PBIAS, RMSE |
| Hydrographs | Simulated vs observed streamflow |
| Spatial maps | GW depth, ET, soil moisture across watershed |

## Procedure

### Step 1: Parse Binary Output

PIHM writes binary files with format:
```
[int32 Unix_timestamp] [float64 elem_1] [float64 elem_2] ... [float64 elem_N]
```

Use `output_parser.py`:

```bash
python ki/tools/output_parser.py \
    --input output/test_run/ \
    --project ShaleHills \
    --variables gw,surf,rivflx1 \
    --output results.csv
```

To list available variables:
```bash
python ki/tools/output_parser.py \
    --input output/test_run/ \
    --project ShaleHills \
    --list-variables
```

### Step 2: Extract Streamflow

Streamflow at the outlet is typically the downstream flux (RIVFLX1) of the
last river segment. For Shale Hills, river segment 20 is the outlet.

```python
import pandas as pd
import numpy as np

# Read parsed CSV
df = pd.read_csv("results.csv", parse_dates=["time"])

# Outlet streamflow (last river segment, downstream flux)
# Convert from m³/s to mm/day for comparison
# Q_mm = Q_m3s * 86400 / (area_m2) * 1000
watershed_area_m2 = 80000  # 8 ha for Shale Hills
df["Q_mm_day"] = df["rivflx1_riv20_m3/s"].abs() * 86400 / watershed_area_m2 * 1000
```

### Step 3: Compute Performance Metrics

Standard hydrologic metrics:

```python
def nash_sutcliffe(obs, sim):
    """Nash-Sutcliffe Efficiency (NSE). Perfect = 1.0."""
    return 1.0 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

def kge(obs, sim):
    """Kling-Gupta Efficiency (KGE). Perfect = 1.0."""
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return 1.0 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

def pbias(obs, sim):
    """Percent Bias (PBIAS). Perfect = 0%. Positive = overestimation."""
    return 100.0 * np.sum(sim - obs) / np.sum(obs)

def rmse(obs, sim):
    """Root Mean Square Error."""
    return np.sqrt(np.mean((obs - sim)**2))
```

Metric interpretation:
| Metric | Poor | Satisfactory | Good | Very Good |
|--------|------|-------------|------|-----------|
| NSE | <0.5 | 0.5–0.65 | 0.65–0.80 | >0.80 |
| KGE | <0.5 | 0.5–0.65 | 0.65–0.80 | >0.80 |
| PBIAS | >±25% | ±15–25% | ±10–15% | <±10% |

### Step 4: Generate Diagnostic Plots

#### Hydrograph (simulated vs observed)

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(df["time"], df["Q_mm_day"], color="#2563EB", label="Simulated", linewidth=1)
# If observed data available:
# ax.plot(obs_df["time"], obs_df["Q_mm_day"], color="black", label="Observed", linewidth=1)

ax.set_xlabel("Date")
ax.set_ylabel("Streamflow (mm/day)")
ax.set_title("Shale Hills Streamflow")
ax.legend()

# Add metrics box if available
# textstr = f"NSE = {nse:.2f}\nKGE = {kge_val:.2f}\nPBIAS = {pbias_val:.1f}%"
# ax.text(0.98, 0.95, textstr, transform=ax.transAxes, fontsize=10,
#         verticalalignment='top', horizontalalignment='right',
#         bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

fig.savefig("hydrograph.png", dpi=150, bbox_inches="tight")
```

#### Groundwater Depth Time Series

```python
# Spatially averaged GW depth
gw_cols = [c for c in df.columns if c.startswith("gw_elem")]
df["gw_mean"] = df[gw_cols].mean(axis=1)

fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(df["time"], df["gw_mean"], color="#2563EB")
ax.set_ylabel("Mean GW Head (m)")
ax.set_title("Watershed-Average Groundwater")
ax.invert_yaxis()  # GW depth increases downward
fig.savefig("gw_depth.png", dpi=150, bbox_inches="tight")
```

#### Water Balance Check

```python
# Annual water balance: P = ET + Q + dS
# Sum up all element areas and fluxes
# P_total = sum(PRCP * area * dt)
# ET_total = sum((EC + ETT + EDIR) * area * dt)
# Q_outlet = sum(RIVFLX1_outlet * dt)
# dS = final_storage - initial_storage
```

### Step 5: Spatial Output (Optional)

For mapping, use the mesh connectivity from `.mesh` file to create
triangular plots showing spatial distribution of GW, ET, soil moisture.

## Verification

1. **Streamflow magnitude**: Matches expected range for catchment (mm/day)
2. **Water balance closure**: P ≈ ET + Q + ΔS (within 5%)
3. **Seasonal patterns**: GW rises in wet season, drops in dry
4. **Recession behavior**: Baseflow recession follows power/exponential
5. **ET seasonality**: Peak in summer, low in winter (temperate)

## Traps

| Trap | Triplet | Severity |
|------|---------|----------|
| Binary endianness mismatch | dt_019 | Degraded — garbage values |
| Wrong element for outlet | — | Silent — wrong streamflow |
| Missing area conversion for mm/day | — | Degraded — wrong magnitudes |

## Example

Full analysis pipeline for Shale Hills:

```bash
# 1. Parse output
python ki/tools/output_parser.py \
    --input output/production/ \
    --project ShaleHills \
    --variables gw,surf,rivflx1,ett,edir,ec,snow \
    --output shale_hills_results.csv

# 2. Analyze in Python
python -c "
import pandas as pd
df = pd.read_csv('shale_hills_results.csv', parse_dates=['time'])
print(f'Records: {len(df)}')
print(f'Period: {df.time.min()} to {df.time.max()}')
gw_cols = [c for c in df.columns if 'gw_' in c]
print(f'Mean GW: {df[gw_cols].mean().mean():.3f} m')
"
```

### PIHM-utils Alternative

The official `PIHM-utils` Python package provides convenient functions:

```bash
pip install PIHM-utils
```

```python
import pihmutils as pu
data = pu.read_output("output/production/ShaleHills.gw.dat", 535)
```
