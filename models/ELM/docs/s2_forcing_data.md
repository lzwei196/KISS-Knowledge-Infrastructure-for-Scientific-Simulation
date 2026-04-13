# Stage 2: Atmospheric Forcing Data Preparation

## Purpose

Convert atmospheric forcing data (ERA5, GSWP3, CRU-NCEP, or custom
observations) into the NetCDF format required by ELM's data atmosphere
component (DATM). Unit conversion is the single highest-risk operation
in the entire pipeline — every variable has a specific unit that differs
from common meteorological conventions.

## Prerequisites

- Stage 0 completed
- Atmospheric forcing data source available (ERA5, GSWP3, station data)
- Python with netCDF4, numpy, pandas installed

## Inputs

| Variable | Common Source Units | ELM Required Units | Conversion |
|----------|--------------------|--------------------|------------|
| Air temperature | °C | **K** | +273.15 (dt_001) |
| Precipitation | mm/day or mm/hr | **mm/s** | ÷86400 or ÷3600 (dt_002) |
| Humidity | % RH or g/kg | **kg/kg** (specific) | Complex conversion (dt_003) |
| Shortwave radiation | W/m² | **W/m²** | Usually OK, check for J/m² |
| Longwave radiation | W/m² | **W/m²** | Usually OK |
| Wind speed | m/s | **m/s** | If u,v components: sqrt(u²+v²) |
| Surface pressure | hPa or kPa | **Pa** | ×100 or ×1000 (dt_004) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| elm_forcing.nc | NetCDF4 | DATM-compatible forcing file |
| Conversion log | JSON | Unit detections and conversions applied |

## Procedure

### 1. Inspect source data units

**CRITICAL**: Before any conversion, manually check the units of your source
data. Do NOT trust variable names alone — many datasets have inconsistent
metadata.

```python
import netCDF4 as nc
ds = nc.Dataset("era5_data.nc")
for var in ds.variables:
    v = ds.variables[var]
    print(f"{var}: units={getattr(v, 'units', 'NONE')}, "
          f"range=[{v[:].min():.4f}, {v[:].max():.4f}]")
ds.close()
```

### 2. Run the forcing converter

```bash
# From ERA5 NetCDF
python tools/convert_forcing_to_elm.py \
    --input era5_2000.nc \
    --output elm_forcing.nc \
    --format era5 \
    --start 2000-01-01 --end 2000-12-31 \
    --lat 40.0 --lon 117.0

# From CSV (e.g., flux tower data)
python tools/convert_forcing_to_elm.py \
    --input station_data.csv \
    --output elm_forcing.nc \
    --format csv \
    --start 2000-01-01 --end 2000-12-31 \
    --lat 40.0 --lon 117.0
```

### 3. Verify the output

```python
import netCDF4 as nc
ds = nc.Dataset("elm_forcing.nc")
# Check temperature is in K (should be ~250-310 K)
print("TBOT range:", ds.variables["TBOT"][:].min(),
      ds.variables["TBOT"][:].max())
# Check precip is in mm/s (should be ~0-0.01 mm/s for most timesteps)
print("PRECTmms range:", ds.variables["PRECTmms"][:].min(),
      ds.variables["PRECTmms"][:].max())
# Check pressure is in Pa (should be ~50000-110000 Pa)
print("PSRF range:", ds.variables["PSRF"][:].min(),
      ds.variables["PSRF"][:].max())
ds.close()
```

## Unit Conversion Reference

### Temperature: °C → K
```python
T_kelvin = T_celsius + 273.15
# Verify: median should be ~250-300 K for most land surfaces
```

### Precipitation: mm/day → mm/s
```python
P_mm_s = P_mm_day / 86400.0
# Verify: max should be < 0.1 mm/s (even for extreme events)
# 0.1 mm/s = 8.64 mm/hr = 207 mm/day
```

### Specific humidity from RH
```python
# Saturation vapor pressure (Pa)
e_sat = 610.94 * exp(17.625 * T_C / (T_C + 243.04))
# Actual vapor pressure
e = (RH / 100) * e_sat
# Specific humidity
q = 0.622 * e / (P_Pa - 0.378 * e)
# Verify: q should be ~0.001-0.025 kg/kg
```

### Pressure: hPa → Pa
```python
P_Pa = P_hPa * 100.0
# Verify: should be ~50000-110000 Pa
```

## Verification

- [ ] TBOT: 180-340 K (median ~260-300 K for your site)
- [ ] PRECTmms: 0-0.1 mm/s (most values near 0)
- [ ] SHUM: 0-0.06 kg/kg
- [ ] FSDS: 0-1400 W/m² (0 at night)
- [ ] FLDS: 50-600 W/m²
- [ ] WIND: 0-75 m/s
- [ ] PSRF: 30000-110000 Pa
- [ ] Time axis is monotonically increasing
- [ ] No >10% NaN values in any variable

## Traps

| Trap | dt_ID | Symptom | Detection |
|------|-------|---------|-----------|
| Temperature in °C | dt_001 | Energy balance failure, perpetual ice | Median < 70 |
| Precip in mm/day | dt_002 | 86400x too much rain, flooding | Max > 0.5 |
| RH instead of q | dt_003 | Values > 1 → wrong latent heat | Max > 0.06 |
| Pressure in hPa | dt_004 | Air density 100x too low | Median < 1200 |
| SW as J/m² not W/m² | dt_010 | Values > 50000 → radiation way too high | Max > 1500 |
| Calendar mismatch | dt_013 | Date drift over multi-year runs | Compare noleap vs gregorian |
| Lat orientation | dt_014 | Forcing applied to wrong hemisphere | Check first/last lat values |

## Example

```bash
# Complete workflow for a Chinese site
python tools/convert_forcing_to_elm.py \
    --input /data/era5/era5_2000_beijing.nc \
    --output /cases/elm_test/forcing/elm_forcing.nc \
    --format era5 \
    --start 2000-01-01 --end 2005-12-31 \
    --lat 39.9 --lon 116.4

# Output will show:
# {
#   "status": "success",
#   "unit_conversions": {
#     "TBOT": "°C → K (+273.15)",
#     "PRECTmms": "mm_per_day → mm/s",
#     "PSRF": "hPa → Pa"
#   },
#   "warnings": [
#     "Temperature detected as °C, converted to K (dt_001)",
#     "Precipitation detected as mm_per_day, converted to mm/s (dt_002)"
#   ]
# }
```
