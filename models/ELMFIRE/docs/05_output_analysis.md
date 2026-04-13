# Stage 5: Output Analysis and Validation

## Purpose

Parse ELMFIRE outputs into analysis-ready formats, compute fire behavior metrics, compare against observed fire perimeters or published benchmark values, and generate validation figures.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Output rasters | Stage 4 | time_of_arrival, spread_rate, flin, flame_length GeoTIFFs |
| fire_size_stats CSV | Stage 4 | Cumulative area/perimeter time series |
| Observed fire perimeter | NIFC, GeoMAC | Shapefile (optional, for validation) |
| Literature values | Published papers | Benchmark metrics (optional) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `results.csv` | CSV | Fire progression time series |
| `results_metrics.json` | JSON | Aggregate fire behavior metrics |
| `validation_figure.png` | PNG | Observed vs. simulated comparison |

## Procedure

### Step 1: Parse fire size statistics

```bash
python parse_elmfire_output.py \
    --outputs_dir ./outputs \
    --out results.csv
```

This produces:
- `results.csv`: Time series with columns for time, area, perimeter
- `results_metrics.json`: Summary metrics

### Step 2: Interpret output units

ELMFIRE uses US fire behavior units. Always convert for international comparisons:

| Output variable | ELMFIRE units | Metric conversion |
|----------------|---------------|-------------------|
| Rate of spread | ft/min | ×0.00508 → m/s; ×0.01829 → km/hr |
| Flame length | feet | ×0.3048 → meters |
| Fireline intensity | kW/m | (already SI) |
| Fire area | acres | ×0.4047 → hectares |
| Perimeter | feet | ×0.3048 → meters |
| Time of arrival | seconds | ÷3600 → hours |

### Step 3: Fire behavior classification

Using NWCG fire behavior thresholds:

| Flame length | Fireline intensity | Fire behavior | Suppression difficulty |
|---|---|---|---|
| < 4 ft (1.2 m) | < 350 kW/m | Low | Hand crews effective |
| 4–8 ft (1.2–2.4 m) | 350–1700 kW/m | Moderate | Equipment needed |
| 8–11 ft (2.4–3.4 m) | 1700–3500 kW/m | High | Serious difficulty |
| > 11 ft (3.4 m) | > 3500 kW/m | Extreme | Crowning, spotting |

### Step 4: Compare with observed data (if available)

```python
import numpy as np
from osgeo import gdal, ogr

# Load simulated time of arrival
ds = gdal.Open('outputs/time_of_arrival.tif')
toa = ds.GetRasterBand(1).ReadAsArray()
gt = ds.GetGeoTransform()

# Load observed perimeter
obs = ogr.Open('observed_perimeter.shp')
layer = obs.GetLayer()

# Rasterize observed perimeter
# Compare burned/unburned pixel agreement
simulated_burned = toa > 0  # or toa != nodata
observed_burned = ...  # from rasterized perimeter

# Compute Sorensen coefficient (dice similarity)
intersection = np.sum(simulated_burned & observed_burned)
sorensen = 2 * intersection / (np.sum(simulated_burned) + np.sum(observed_burned))
print(f"Sorensen coefficient: {sorensen:.3f}")  # 1.0 = perfect match
```

### Step 5: Compute validation metrics

For fire spread models, common metrics include:

```python
# Area ratio (simulated / observed)
area_ratio = sim_area_ha / obs_area_ha

# Perimeter agreement (Jaccard index)
jaccard = intersection / (np.sum(simulated_burned | observed_burned))

# Commission error (over-prediction)
commission = np.sum(simulated_burned & ~observed_burned) / np.sum(simulated_burned)

# Omission error (under-prediction)
omission = np.sum(~simulated_burned & observed_burned) / np.sum(observed_burned)

# RMSE of time of arrival (at observed perimeter points)
# Only meaningful where both model and observation have data
```

### Step 6: Generate validation figure

```python
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Panel 1: Fire progression (area vs time)
ax = axes[0]
ax.plot(time_hrs, sim_area_ha, color='#2563EB', linewidth=2, label='Simulated')
if obs_area_ha is not None:
    ax.plot(obs_time_hrs, obs_area_ha, 'ko-', linewidth=2, label='Observed')
ax.set_xlabel('Time (hours)')
ax.set_ylabel('Burned area (hectares)')
ax.legend()
ax.set_title('Fire Growth')

# Panel 2: Spatial comparison
ax = axes[1]
ax.imshow(toa, cmap='YlOrRd', origin='lower')
ax.set_title('Time of Arrival')

# Metrics box
textstr = f'Area: {sim_area_ha:.0f} ha\nSorensen: {sorensen:.3f}'
props = dict(boxstyle='round', facecolor='white', alpha=0.8)
ax.text(0.95, 0.95, textstr, transform=ax.transAxes,
        verticalalignment='top', horizontalalignment='right',
        bbox=props, fontsize=10)

plt.tight_layout()
plt.savefig('validation_figure.png', dpi=150)
```

## Verification

1. **Area plausibility**: Compare total area against known fire size or analytical solution
2. **Spread rate range**: Grass: 50–300 ft/min; Timber: 5–50 ft/min; Brush: 20–100 ft/min
3. **Fire shape**: Under constant wind, fire should be elliptical
4. **Sorensen > 0.5**: Reasonable agreement with observed perimeter
5. **No systematic bias**: Commission ≈ omission for well-calibrated model

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| ROS in ft/min vs m/s | Values seem 200× too high | Convert: ×0.00508 for m/s |
| Area in acres vs ha | Values seem 2.5× too high | Convert: ×0.4047 for ha |
| TOA = -9999 | Pixel never burned | Mask NODATA before analysis |
| Comparing different CRS | Spatial mismatch | Reproject to common CRS |
| Wrong contour interval | Isochrones too sparse/dense | Match to DTDUMP interval |

## Example

Analyzing Tutorial 01 output:

```bash
python parse_elmfire_output.py \
    --outputs_dir ./tutorials/01-constant-wind/outputs \
    --out tutorial01_results.csv

# Expected metrics:
# Total area: 200-400 acres (80-160 ha)
# Max spread rate: 150-250 ft/min
# Max fireline intensity: 500-2000 kW/m
# Max flame length: 5-15 ft
# Duration: 5.5 hours
```
