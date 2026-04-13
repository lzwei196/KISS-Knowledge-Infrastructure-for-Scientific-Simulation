# Stage 7: Output Parsing

## Purpose

Extract and analyze fields from ESMF application output files. ESMF-based
models typically produce NetCDF output containing multi-dimensional fields
on the computational grid. This stage extracts time series at specific
locations, computes spatial statistics, and converts output to analysis-
friendly CSV format.

## Inputs

| Input                  | Format       | Description                          |
|------------------------|--------------|--------------------------------------|
| Model output           | NetCDF       | ESMF application output fields       |
| Grid definition        | NetCDF       | Grid for coordinate lookup           |
| Variable list          | Text         | Variables to extract                 |
| Extract locations      | lat/lon      | Points for time series extraction    |

## Outputs

| Output                 | Format       | Description                          |
|------------------------|--------------|--------------------------------------|
| Time series CSV        | CSV          | Extracted variables at points        |
| Metadata JSON          | JSON         | Statistics, units, coordinate info   |
| Spatial field CSV      | CSV          | 2D field at specific timestep        |

## Procedure

1. **Inspect output file**:
   ```bash
   ncdump -h output.nc
   ```
   Check variable names, dimensions, units, fill values.

2. **Extract time series**:
   ```bash
   python parse_esmf_output.py \
       --input output.nc \
       --variables temperature,precipitation_flux \
       --output timeseries.csv \
       --extract-type timeseries \
       --lat 40.0 --lon 116.0
   ```

3. **Check extracted data**:
   - Verify units match expectations
   - Check for fill values treated as real data
   - Verify temporal continuity (no gaps)

4. **Compute derived quantities** (if needed):
   - Evapotranspiration = Rn - G - H (energy balance)
   - Runoff = Precipitation - ET - ΔStorage
   - Mean areal precipitation (area-weighted average)

5. **Generate summary statistics**:
   ```python
   import pandas as pd
   df = pd.read_csv("timeseries.csv")
   print(df.describe())
   ```

## Verification

- CSV file has correct number of rows (matching timesteps)
- All requested variables present in output
- Values within physical bounds:
  - Temperature: 200–330 K
  - Precipitation flux: 0–0.05 kg/m²/s
  - Wind: 0–50 m/s
  - Radiation: 0–1400 W/m²
- No all-NaN columns (fill value issue)
- Extracted point coordinates match expected location (±grid spacing)

## Traps

| Trap | Description | Severity |
|------|-------------|----------|
| Fill value as data | -9999 or 1e20 not filtered → statistics corrupted | silent |
| Longitude convention | Query uses -180/180 but data uses 0/360 → wrong point | silent |
| Wrong time calendar | 360-day output parsed with standard calendar → date drift | silent |
| Missing variable | Typo in variable name → silently skipped | silent |
| Stagger location | Data at corners but coordinates at centers → half-cell offset | silent |
| 4D vs 3D extraction | Level dimension not handled → wrong depth extracted | silent |

## Example

```python
from netCDF4 import Dataset
import numpy as np

# Quick inspection of ESMF output
ds = Dataset("output.nc", "r")
for name, var in ds.variables.items():
    if var.ndim >= 2:
        data = var[:]
        valid = data[np.isfinite(data)] if hasattr(data, '__len__') else data
        print(f"{name}: shape={var.shape}, "
              f"units={getattr(var, 'units', 'N/A')}, "
              f"range=[{np.min(valid):.4g}, {np.max(valid):.4g}]")
ds.close()
```

```bash
# Extract temperature time series at Beijing
python parse_esmf_output.py \
    --input coupled_output.nc \
    --variables air_temperature,surface_temperature \
    --output beijing_temp.csv \
    --lat 39.9 --lon 116.4

# Check the result
head -5 beijing_temp.csv
python -c "
import pandas as pd
df = pd.read_csv('beijing_temp.csv')
print(f'Rows: {len(df)}')
print(f'Temp range: {df.air_temperature.min():.1f} - {df.air_temperature.max():.1f} K')
print(f'  = {df.air_temperature.min()-273.15:.1f} - {df.air_temperature.max()-273.15:.1f} °C')
"
```
