# Stage 7: Output Analysis

## Purpose

Extract, analyze, and validate ELM history output. History files are NetCDF
with CF conventions, containing gridded time series of energy, water, carbon,
nitrogen, and phosphorus fluxes and states. This stage converts raw NetCDF
output into analysis-ready CSV/DataFrame format.

## Prerequisites

- Stage 6 completed (model run successful)
- Python with netCDF4, pandas, numpy, matplotlib installed

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| History files | NetCDF | *.elm.h0.*.nc (monthly), *.elm.h1.*.nc (daily), etc. |
| Variable list | CLI args | Names of variables to extract |
| Location | lat/lon | For point extraction from gridded output |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Time series CSV | CSV | Extracted variables with time index |
| Statistics JSON | JSON | Summary statistics per variable |
| Validation report | JSON | Quality flags and range checks |

## Procedure

### 1. Locate history files

```bash
# For a CIME case
HIST_DIR=$(./xmlquery --value DOUT_S_ROOT)/lnd/hist/
ls $HIST_DIR/*.elm.h0.*  # Monthly files
ls $HIST_DIR/*.elm.h1.*  # Daily files (if configured)
```

### 2. Quick inspection with ncdump

```bash
# List variables in a history file
ncdump -h case.elm.h0.2000-01.nc | grep "float\|double" | head -20

# Check a specific variable
ncdump -v GPP case.elm.h0.2000-01.nc | tail -5
```

### 3. Extract time series with the KI tool

```bash
# Extract key carbon and water fluxes
python tools/parse_elm_output.py \
    --input_dir /archive/lnd/hist/ \
    --variables GPP NPP QRUNOFF FSH EFLX_LH_TOT H2OSOI TSOI \
    --output timeseries.csv

# Extract at a specific point
python tools/parse_elm_output.py \
    --input_file case.elm.h0.2000-01.nc \
    --variables GPP NPP QRUNOFF \
    --lat 40.0 --lon 117.0 \
    --output point_timeseries.csv

# Convert to daily totals (flux rates → daily amounts)
python tools/parse_elm_output.py \
    --input_dir /archive/lnd/hist/ \
    --variables QRUNOFF GPP NPP \
    --to_daily \
    --output daily_totals.csv
```

### 4. Unit conversion reference for analysis

**CRITICAL (dt_020)**: ELM output fluxes are in per-second rates:

| Variable | ELM Output | To daily | To annual |
|----------|------------|----------|-----------|
| GPP | gC/m²/s | ×86400 → gC/m²/day | ×86400×365 → gC/m²/yr |
| QRUNOFF | mm/s | ×86400 → mm/day | ×86400×365 → mm/yr |
| FSH | W/m² | Already energy rate | ×86400/1e6 → MJ/m²/day |
| EFLX_LH_TOT | W/m² | Already energy rate | ÷2.501e6 → mm/day (ET) |

### 5. Compute diagnostic metrics

```python
import pandas as pd
import numpy as np

# Read extracted data
df = pd.read_csv("timeseries.csv", index_col="time", parse_dates=True)

# Annual GPP (gC/m²/yr)
annual_gpp = df["GPP"].resample("Y").mean() * 86400 * 365

# Annual runoff (mm/yr)
annual_runoff = df["QRUNOFF"].resample("Y").mean() * 86400 * 365

# Energy balance check
df["Rnet"] = df["FSA"] - df["FIRA"]
df["energy_residual"] = df["Rnet"] - df["FSH"] - df["EFLX_LH_TOT"]
# Should be < 5 W/m² for monthly averages
print("Energy balance residual:", df["energy_residual"].mean(), "W/m²")
```

### 6. Typical value ranges by biome

| Variable | Tropical Forest | Temperate Forest | Grassland | Desert |
|----------|----------------|------------------|-----------|--------|
| GPP (gC/m²/yr) | 2000-3500 | 800-2000 | 200-800 | 0-100 |
| NPP (gC/m²/yr) | 800-1500 | 400-1000 | 100-400 | 0-50 |
| ET (mm/yr) | 1000-1800 | 400-800 | 200-500 | 0-100 |
| Runoff (mm/yr) | 500-2000 | 200-600 | 50-200 | 0-50 |
| Soil T @ 10cm (°C) | 22-28 | 5-15 | 5-20 | 15-40 |

## Verification

- [ ] All requested variables are present in output
- [ ] No more than 10% NaN values in any variable
- [ ] GPP is non-negative
- [ ] Energy balance residual < 10 W/m² (monthly average)
- [ ] Water balance residual < 1 mm/day (monthly average)
- [ ] Values within biome-typical ranges (table above)
- [ ] Seasonal cycle is physically reasonable

## Traps

| Trap | dt_ID | Symptom | Prevention |
|------|-------|---------|------------|
| Runoff units wrong | dt_020 | 86400x too high if treated as mm/day | Always multiply mm/s by 86400 |
| Missing variables | — | Variable not in history file | Check hist_fincl1 in namelist |
| Wrong tape | — | Daily data in h0 (monthly) file | Use --tape h1 for daily |
| Grid averaging | — | Unexpected spatial average | Use --lat --lon for point extraction |

## Example

```bash
# Full analysis workflow
python tools/parse_elm_output.py \
    --input_dir /archive/elm_test/lnd/hist/ \
    --variables GPP NPP NEE HR QRUNOFF FSH EFLX_LH_TOT \
    --lat 42.5 --lon -72.2 \
    --to_daily \
    --output harvard_forest_daily.csv

# Quick plot
python3 -c "
import pandas as pd
import matplotlib.pyplot as plt
df = pd.read_csv('harvard_forest_daily.csv', index_col='time', parse_dates=True)
fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
df['GPP'].plot(ax=axes[0], title='GPP (gC/m²/day)')
df['QRUNOFF'].plot(ax=axes[1], title='Runoff (mm/day)')
df['FSH'].plot(ax=axes[2], title='Sensible Heat (W/m²)')
plt.tight_layout()
plt.savefig('elm_diagnostics.png', dpi=150)
"
```
