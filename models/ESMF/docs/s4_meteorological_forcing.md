# Stage 4: Meteorological Forcing

## Purpose

Convert external meteorological forcing data into ESMF-compatible CF-convention
NetCDF files. This stage handles unit conversions, temporal interpolation,
and spatial regridding of forcing fields from global reanalysis or station data
onto the model's computational grid.

## Inputs

| Input                  | Source           | Native Units        | Target Units (CF) |
|------------------------|------------------|---------------------|--------------------|
| Air temperature        | CMFD/ERA5/MSWX   | K or °C            | K                  |
| Precipitation          | CMFD/ERA5         | mm/hr, mm/day, m/day | kg/m²/s          |
| Shortwave radiation    | CMFD/ERA5         | W/m² or MJ/m²/day | W/m²               |
| Longwave radiation     | CMFD/ERA5         | W/m² or MJ/m²/day | W/m²               |
| Surface pressure       | CMFD/ERA5         | Pa, hPa, kPa      | Pa                 |
| Specific humidity      | CMFD/ERA5         | kg/kg or g/kg      | kg/kg              |
| Relative humidity      | Station data      | % (0-100)          | fraction (0-1)     |
| Wind speed / U,V       | CMFD/ERA5         | m/s                | m/s                |

## Outputs

| Output                 | Format       | Description                          |
|------------------------|--------------|--------------------------------------|
| Forcing NetCDF         | NetCDF-4/CF  | All forcing variables on model grid  |
| Conversion log         | JSON         | Unit conversions applied, QC stats   |

## Procedure

1. **Identify source format and units**:
   ```bash
   ncdump -h raw_forcing.nc | grep units
   ```

2. **Run conversion tool**:
   ```bash
   python convert_forcing_to_esmf.py \
       --input raw_forcing.csv \
       --source-format cmfd \
       --output forcing_cf.nc \
       --start-date 2000-01-01 \
       --end-date 2010-12-31
   ```

3. **Verify CF compliance**:
   - Time axis has `units = "X since YYYY-MM-DD"` format
   - All variables have `units` and `standard_name` attributes
   - Fill values use `_FillValue` attribute (not missing_value alone)

4. **Regrid forcing to model grid** (if different resolution):
   ```bash
   python generate_regrid_weights.py \
       --source forcing_grid.nc \
       --destination model_grid.nc \
       --weight forcing_to_model.nc \
       --method bilinear
   ```

5. **Quality control checks**:
   - Temperature: 150–350 K (no °C values mixed in)
   - Precipitation: 0–0.1 kg/m²/s (no mm/day values)
   - Pressure: 30000–110000 Pa (no hPa values)
   - Radiation: 0–1500 W/m² (no MJ/m²/day values)
   - Humidity fraction: 0–1 (no percentage values)

## Verification

- `ncdump -h` shows CF-convention attributes on all variables
- Time axis parseable by `cftime` / ESMF_Clock
- Physical bounds within expected ranges (see QC checks above)
- No all-NaN timesteps or variables
- Temporal coverage matches simulation period

## Traps

| Trap | Description | Factor | Severity |
|------|-------------|--------|----------|
| Precip mm/day → kg/m²/s | Forget to divide by 86400 | 86400x | silent |
| Precip m/day → kg/m²/s | ERA5 total precip in meters | 1000× then 86400× | silent |
| Humidity % → fraction | Pass 50% as 50.0 instead of 0.50 | 100x | silent |
| Temp °C → K | Forget to add 273.15 | offset | silent |
| Radiation MJ/m²/day → W/m² | Forget to multiply by 1e6/86400 | ~11.6x | silent |
| Pressure hPa → Pa | Forget to multiply by 100 | 100x | silent |
| Humidity g/kg → kg/kg | Forget to divide by 1000 | 1000x | silent |
| Time as integer index | No "since" epoch → ESMF crash | — | fatal |
| Wrong calendar | 360-day calendar treated as Gregorian | ~1.4% drift/year | silent |

## Example

```python
# Quick check: are precipitation values in the right units?
import numpy as np
from netCDF4 import Dataset

ds = Dataset("forcing.nc", "r")
precip = ds.variables["precipitation_flux"][:]

# CF standard: kg/m²/s.  1 mm/day = 1.157e-5 kg/m²/s
mean_p = np.nanmean(precip)
if mean_p > 0.01:
    print(f"WARNING: mean precip = {mean_p:.4f} kg/m²/s")
    print("This is ~860 mm/day — likely mm/day was not converted!")
elif mean_p > 1e-3:
    print(f"WARNING: mean precip = {mean_p:.4f} kg/m²/s")
    print("This is ~86 mm/day — possibly mm/hr not converted!")
else:
    print(f"Precip looks reasonable: {mean_p:.2e} kg/m²/s = {mean_p*86400:.1f} mm/day")
```
