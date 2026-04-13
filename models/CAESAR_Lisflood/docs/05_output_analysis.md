# Stage 5: Output Analysis and Validation

## Purpose

Parse, analyse, and validate HAIL-CAESAR model output. Extract hydrographs and sediment transport data for comparison with observations or known good answers.

## Inputs

| Input | Format | Units | Description |
|-------|--------|-------|-------------|
| Timeseries file | `.dat` (text) | Various (see below) | Model discharge and sediment output |
| Raster files | `.asc` | metres | Water depth, elevation, etc. |
| Observations (optional) | CSV | m3/s | Observed discharge for validation |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Parsed CSV | `.csv` | Time, discharge, sediment in tidy format |
| Hydrograph plot | `.png` | Observed vs simulated discharge |
| Raster summaries | `.csv` | Statistics for each output raster |
| Validation metrics | text | NSE, KGE, PBIAS, RMSE, r |

## Procedure

### Step 1: Parse the timeseries file

The timeseries file has 14 space-delimited columns:

| Column | Variable | Units | Notes |
|--------|----------|-------|-------|
| 1 | Time index | count | Multiply by `timeseries_save_interval` for minutes |
| 2 | Actual discharge | m3/s | Instantaneous rate at outlet(s) |
| 3 | Expected discharge | m3/s | TOPMODEL estimation |
| 4 | Sand output | m3 | Legacy (usually zero) |
| 5 | Total sediment Q | m3 | Total for interval (NOT rate) |
| 6-14 | Grain fractions 1-9 | m3 | Sediment per grain size for interval |

**Critical unit note**: Discharge (col 2) is an instantaneous rate (m3/s), but sediment (cols 5-14) is a total volume (m3) for the save interval. To get sediment flux in m3/s, divide by `timeseries_save_interval * 60`.

### Step 2: Convert time index to real time

```python
time_minutes = time_index * timeseries_save_interval
time_hours = time_minutes / 60.0
```

### Step 3: Plot hydrograph

```python
import matplotlib.pyplot as plt
import numpy as np

data = np.loadtxt("results/output.dat")
time_hrs = data[:, 0] * 5 / 60  # 5-min save interval
discharge = data[:, 1]

fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(time_hrs, discharge, color='#2563EB', linewidth=1.5, label='Simulated')
ax.set_xlabel('Time (hours)')
ax.set_ylabel('Discharge (m³/s)')
ax.set_title('HAIL-CAESAR Hydrograph')
ax.legend()
plt.savefig('hydrograph.png', dpi=150, bbox_inches='tight')
```

### Step 4: Compute validation metrics

If observed discharge data is available:

```python
def nash_sutcliffe(obs, sim):
    """Nash-Sutcliffe Efficiency (NSE). 1.0 = perfect."""
    return 1 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

def kge(obs, sim):
    """Kling-Gupta Efficiency (KGE). 1.0 = perfect."""
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

def pbias(obs, sim):
    """Percent Bias (PBIAS). 0% = perfect. Positive = underestimate."""
    return 100 * np.sum(obs - sim) / np.sum(obs)

def rmse(obs, sim):
    """Root Mean Square Error."""
    return np.sqrt(np.mean((obs - sim)**2))
```

### Step 5: Analyse raster outputs

Water depth rasters can be:
- Animated to visualise flood progression
- Compared against observed flood extent (satellite imagery)
- Used to calculate max flood depth and inundation area

```python
# Read ASCII raster
data = np.loadtxt("results/WaterDepths0120.asc", skiprows=6)
data[data == -9999] = np.nan  # Mask NODATA

max_depth = np.nanmax(data)
flooded_cells = np.sum(data > 0.1)  # Cells with >10cm water
inundation_area_km2 = flooded_cells * (cellsize**2) / 1e6
```

### Step 6: Sediment transport analysis

If erosion was enabled:
- Total sediment output per grain fraction
- Cumulative erosion/deposition from elevation difference rasters
- Sediment yield (m3/km2/yr) for long-term simulations

```python
# Total sediment by fraction
total_sed = data[:, 4]  # Column 5: total sediment m3
grain_seds = data[:, 5:14]  # Columns 6-14: per-fraction

cumulative = np.cumsum(total_sed)
```

## Verification

1. **Hydrograph shape**: Should show rising limb, peak, recession
2. **Peak timing**: Should correspond to rainfall peak + lag time
3. **Water balance**: Total rainfall volume ~ total discharge volume (minus losses)
4. **Sediment**: Should be zero if `hydro_model_only: yes`
5. **Raster values**: Water depths should be physically reasonable (0-10m for most events)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Sediment values treated as rates | Overestimation of flux | Cols 5-14 are totals (m3), not rates (m3/s) |
| Time index mistaken for minutes | Wrong X-axis on plots | Multiply by `timeseries_save_interval` |
| Discharge from all edges summed | Higher Q than expected for single outlet | Model reports total from ALL edge cells |
| NODATA not masked in rasters | Extreme min/max values (-9999) | Filter NODATA before computing stats |
| Comparing different save intervals | Misaligned timeseries | Interpolate to common timestep before comparing |

## Example

Using the `parse_caesar_output.py` tool:

```bash
python parse_caesar_output.py \
    --timeseries_file results/boscastle_50m_72hr_u.dat \
    --save_interval 5 \
    --output_csv results/hydrograph.csv \
    --raster_dir results/ \
    --raster_prefix WaterDepths \
    --raster_summary_csv results/raster_stats.csv
```

Expected output for Boscastle 72hr:
- Peak discharge: ~20-80 m3/s (depends on TOPMODEL m value)
- Peak timing: ~12-18 hours (depends on rainfall pattern)
- Total output rows: ~864 (72hr * 60min / 5min interval)
