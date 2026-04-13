# Stage 1: Meteorological Forcing Preparation

## Purpose

Convert global reanalysis or site-level meteorological observations into CLASSIC-compatible netCDF forcing files. CLASSIC requires **7 separate netCDF files** (one variable per file) with a specific time encoding that differs from standard CF conventions.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Air temperature | CRU-JRA, ERA5, CMFD, or site CSV | K or deg C |
| Precipitation | CRU-JRA, ERA5, CMFD, or site CSV | mm/hr, mm/day, or kg/m2/s |
| Shortwave radiation | CRU-JRA, ERA5, CMFD | W/m2 (or J/m2 for ERA5 accumulated) |
| Longwave radiation | CRU-JRA, ERA5, CMFD | W/m2 |
| Specific humidity | CRU-JRA, ERA5, CMFD | kg/kg or g/kg |
| Wind speed | CRU-JRA, ERA5, CMFD | m/s |
| Surface pressure | CRU-JRA, ERA5, CMFD | Pa, hPa, or kPa |

## Outputs

Seven netCDF-4 files, one variable per file:
- `dswrf.nc` — Downwelling shortwave (W/m2)
- `dlwrf.nc` — Downwelling longwave (W/m2)
- `pre.nc` — Precipitation rate (kg m-2 s-1)
- `tmp.nc` — Air temperature (**deg C**, NOT Kelvin)
- `spfh.nc` — Specific humidity (kg/kg)
- `wind.nc` — Wind speed (m/s)
- `pres.nc` — Surface pressure (Pa)

Each file has dimensions `(time, lat, lon)` with time encoded as `"day as %Y%m%d.%f"`.

## Procedure

1. **Identify source dataset** and its native units/resolution
2. **Extract nearest grid cell** (for gridded data) or load CSV
3. **Convert units** using the conversion functions:
   - Temperature: K → deg C (subtract 273.15)
   - Precipitation: mm/hr → kg/m2/s (divide by 3600)
   - Humidity: g/kg → kg/kg (divide by 1000)
   - Pressure: hPa → Pa (multiply by 100)
4. **Clip shortwave** to >= 0 (interpolation can produce negatives)
5. **Encode time** as `"day as %Y%m%d.%f"` (e.g., 20010601.5 = noon June 1 2001)
6. **Write netCDF-4** with proper attributes
7. **Validate output** ranges

## Verification

```python
import netCDF4 as nc
ds = nc.Dataset("tmp.nc")
t = ds.variables["tmp"][:]
assert t.min() > -90 and t.max() < 60, "Temperature out of physical range"
# Check time encoding
time_vals = ds.variables["time"][:]
assert time_vals[0] > 18000000, "Time should be YYYYMMDD.f format, not days-since"
ds.close()
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Temperature in K instead of C | Soil temperatures ~300K, energy balance wrong | Subtract 273.15 |
| Precipitation in mm/day instead of kg/m2/s | Runoff 86400x too high | Divide by 86400 |
| Specific humidity in g/kg | Evaporation 1000x too high | Divide by 1000 |
| Pressure in hPa | Atmospheric density 100x too low | Multiply by 100 |
| Time as "days since" | Model reads wrong dates, crashes or wrong season | Rewrite as YYYYMMDD.f |
| Missing first timestep at 00:00 day 1 | Model assigns wrong initial values | Ensure data starts at hour 0, minute 0, day 1 |
| Shortwave negative after interpolation | NaN propagation | Clip to max(0, SW) |

## Example

```bash
python ki/tools/convert_forcing_to_classic.py \
    --source_type crujra \
    --source_dir /path/to/crujra/ \
    --lat 45.5 --lon -75.5 \
    --start_year 1991 --end_year 2010 \
    --output_dir met_files/ \
    --timestep_minutes 30
```
