# Stage 7: Output Analysis and Post-processing

## Purpose

Extract, analyze, and validate PCR-GLOBWB 2 model outputs. Convert gridded NetCDF results to point time series, compute basin averages, calculate performance metrics, and compare with observations.

## Inputs

| Input | Format | Location | Description |
|-------|--------|----------|-------------|
| Model output | NetCDF | outputDir/netcdf/ | Gridded time series |
| End states | PCRaster .map | outputDir/states/ | End-of-run states |
| Observations | CSV | User-provided | Gauge discharge, ET, etc. |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Point time series | CSV | Variable values at specified lat/lon |
| Basin averages | CSV | Area-weighted averages over landmask |
| Performance metrics | JSON/text | NSE, KGE, PBIAS, R2 |
| Validation figures | PNG | Hydrographs, scatter plots |

## Procedure

### Step 1: Identify Available Outputs

PCR-GLOBWB output files follow the naming convention:
```
{variable}_{frequency}{aggregation}_output.nc
```

Examples:
- `discharge_dailyTot_output.nc` — Daily total discharge
- `actualET_monthTot_output.nc` — Monthly total actual ET
- `storGroundwater_monthAvg_output.nc` — Monthly average GW storage
- `discharge_monthMax_output.nc` — Monthly maximum discharge

### Step 2: Extract Point Time Series

For validation against gauged stations:

```python
from tools.parse_pcrglobwb_output import extract_point_timeseries

extract_point_timeseries(
    netcdf_dir="/output/netcdf/",
    variable="discharge",
    lat=51.97,       # Gauge latitude
    lon=5.67,        # Gauge longitude
    output_csv="discharge_lobith.csv"
)
```

### Step 3: Extract Basin Averages

For basin-scale water balance analysis:

```python
from tools.parse_pcrglobwb_output import extract_basin_average

extract_basin_average(
    netcdf_dir="/output/netcdf/",
    variable="totalRunoff",
    landmask_nc="basin_mask.nc",
    output_csv="runoff_basin_avg.csv",
    cell_area_nc="cellarea.nc"
)
```

### Step 4: Compute Performance Metrics

Standard hydrological metrics:

```python
import numpy as np

def nash_sutcliffe(obs, sim):
    """Nash-Sutcliffe Efficiency (NSE). Range: -inf to 1.0"""
    return 1.0 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

def kling_gupta(obs, sim):
    """Kling-Gupta Efficiency (KGE). Range: -inf to 1.0"""
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return 1.0 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

def pbias(obs, sim):
    """Percent Bias (PBIAS). Target: 0%"""
    return 100.0 * np.sum(sim - obs) / np.sum(obs)
```

### Step 5: Key Output Variables and Their Units

| Variable | Daily Unit | Monthly Unit | Annual Unit |
|----------|-----------|-------------|-------------|
| discharge | m3/s | m3/s (avg) | m3/s (avg) |
| totalRunoff | m/day | m/month | m/year |
| actualET | m/day | m/month | m/year |
| precipitation | m/day | m/month | m/year |
| gwRecharge | m/day | m/month | m/year |
| storGroundwater | m | m (avg) | m (avg/end) |
| channelStorage | m3 | m3 (avg) | m3 (avg/end) |
| snowCoverSWE | m | m (avg) | m (avg/end) |

### Step 6: Merge Parallel Outputs

For runs split across multiple clones:
```bash
cd model/
python merge_netcdf.py
```

## Verification

- [ ] Discharge is non-negative at all cells
- [ ] Water balance: P - ET - Q ≈ dS/dt (within 1-5%)
- [ ] NSE > 0.5 for calibrated basins
- [ ] No constant zero values at gauge locations
- [ ] Seasonal patterns match expected climate

## Traps

| Trap ID | Symptom | Root Cause | Fix |
|---------|---------|-----------|-----|
| dt_009 | Zero values everywhere | Wrong variable name in extraction | Check exact name |
| - | Discharge = 0 at known gauge | Extraction point not on river cell | Snap to nearest LDD cell |
| - | Negative storage values | Abstraction exceeding storage | Check water demand settings |
| - | No seasonal variation | Wrong forcing data period | Verify forcing temporal coverage |

## Example

```bash
# Summarize all outputs
python tools/parse_pcrglobwb_output.py /scratch/output/netcdf/ --summary

# Extract discharge at Lobith (Rhine outlet)
python tools/parse_pcrglobwb_output.py /scratch/output/netcdf/ \
    -v discharge --lat 51.97 --lon 5.67 -o discharge_lobith.csv

# Extract basin-average ET
python tools/parse_pcrglobwb_output.py /scratch/output/netcdf/ \
    -v actualET --landmask basin_mask.nc -o et_basin.csv
```
