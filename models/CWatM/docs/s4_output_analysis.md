# Stage 4: Output Analysis — Results Extraction and Validation

## Purpose

Extract, analyze, and validate CWatM simulation results. Compute hydrological performance metrics against observed data. Generate visualizations for model assessment.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| CWatM output files | Model run | NetCDF | Discharge, ET, storage, etc. |
| Observed discharge | GRDC / local agency | CSV / NetCDF | Measured streamflow |
| Observed ET | MODIS / GLEAM | NetCDF | Remote sensing ET |
| Observed TWS | GRACE | NetCDF | Gravitational water storage |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Time series CSV | CSV | Extracted gauge data |
| Performance metrics | JSON / text | NSE, KGE, PBIAS, R², RMSE |
| Hydrograph plots | PNG | Simulated vs observed |
| Spatial maps | PNG | Gridded variable visualization |
| Water balance summary | CSV | Component-wise balance |

## Procedure

### 1. Extract Time Series

```python
from parse_cwatm_output import extract_timeseries

dates, discharge, meta = extract_timeseries(
    "output/discharge_daily.nc", "discharge", gauge_index=0
)
```

### 2. Compute Performance Metrics

Standard hydrological metrics:

| Metric | Formula | Good Range | Interpretation |
|--------|---------|------------|----------------|
| NSE | 1 - Σ(sim-obs)²/Σ(obs-mean)² | > 0.5 | Model better than mean |
| KGE | 1 - √((r-1)²+(α-1)²+(β-1)²) | > 0.5 | Correlation + variability + bias |
| PBIAS | 100×Σ(sim-obs)/Σ(obs) | ±25% | Volume bias |
| R² | (correlation coefficient)² | > 0.6 | Linear relationship |
| RMSE | √(mean(sim-obs)²) | varies | Absolute error magnitude |

```python
from parse_cwatm_output import compute_hydrological_metrics

metrics = compute_hydrological_metrics(sim_discharge, obs_discharge)
print(f"NSE: {metrics['NSE']}, KGE: {metrics['KGE']}, PBIAS: {metrics['PBIAS']}%")
```

### 3. Generate Hydrograph

```python
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(obs_dates, obs_values, 'k-', linewidth=0.8, label='Observed')
ax.plot(sim_dates, sim_values, color='#2563EB', linewidth=0.8, label='Simulated')
ax.set_ylabel('Discharge (m³/s)')
ax.legend()
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

# Add metrics box
textstr = f'NSE={metrics["NSE"]:.3f}\nKGE={metrics["KGE"]:.3f}\nPBIAS={metrics["PBIAS"]:.1f}%'
ax.text(0.98, 0.95, textstr, transform=ax.transAxes, fontsize=9,
        verticalalignment='top', horizontalalignment='right',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

plt.savefig("hydrograph.png", dpi=150, bbox_inches='tight')
```

### 4. Water Balance Check

CWatM tracks total water storage (TWS):
```
TWS = storGroundwater + totalSto + lakeReservoirStorage/CellArea + channelStorage/CellArea
```

Water balance closure:
```
ΔS = P - ET - Q_out + Q_in
```

Where:
- ΔS = change in total water storage
- P = precipitation
- ET = total evapotranspiration
- Q_out = discharge at outlet
- Q_in = external inflows

### 5. Spatial Analysis

```python
import netCDF4 as nc
import numpy as np

# Read annual average discharge map
ds = nc.Dataset("output/discharge_annualavg.nc")
q_map = ds.variables["discharge"][-1, :, :]  # Last year
lats = ds.variables["lat"][:]
lons = ds.variables["lon"][:]

# Plot
import matplotlib.pyplot as plt
plt.pcolormesh(lons, lats, q_map, cmap='Blues')
plt.colorbar(label='Discharge (m³/s)')
plt.savefig("discharge_map.png", dpi=150)
```

## Verification

- NSE > 0 means model is better than climatological mean
- KGE > -0.41 means model is informative (Knoben et al. 2019)
- PBIAS within ±25% is acceptable for most applications
- Water balance should close within 1% over multi-year periods
- Seasonal cycle should be captured (peak timing within ±1 month)

## Traps

1. **Discharge units**: CWatM outputs discharge in m³/s. GRDC data is also in m³/s. Some local agencies use mm/day or ML/day — convert before comparison.

2. **SpinUp period in output**: Output before the SpinUp date may contain initialization artifacts. Always exclude SpinUp period from metric calculation.

3. **Gauge location mismatch**: CWatM maps gauges to the nearest grid cell. For coarse grids (30 arcmin ≈ 50 km), the mapped drainage area may differ significantly from the actual gauge catchment area. Check upstream area.

4. **Monthly vs daily metrics**: NSE on daily data is usually lower than on monthly averages. Compare metrics at the same temporal resolution.

5. **Negative discharge**: Can occur in small channels due to numerical errors in routing. Filter out near-zero negative values before computing metrics.

## Example

```bash
# Full analysis pipeline
python parse_cwatm_output.py \
    --output_dir output/ \
    --variable discharge \
    --gauge_index 0 \
    --csv_out discharge_sim.csv \
    --compute_metrics \
    --observed_csv grdc_observed.csv
```

Expected output:
```json
{
    "NSE": 0.72,
    "KGE": 0.78,
    "PBIAS": -8.5,
    "R2": 0.81,
    "RMSE": 145.3,
    "mean_sim": 1234.5,
    "mean_obs": 1350.2,
    "n_points": 3650
}
```
