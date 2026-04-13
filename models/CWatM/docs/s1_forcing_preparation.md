# Stage 1: Forcing Preparation — Meteorological Input Data

## Purpose

Prepare meteorological forcing data in CWatM-compatible NetCDF format with correct units, coordinate system, and temporal resolution. This is the most error-prone stage due to unit conversion requirements.

## Inputs

| Input | Source | Format | Variables |
|-------|--------|--------|-----------|
| CMFD forcing | CMFD archive | NetCDF, 0.1° 3-hourly | prec, temp, shum, pres, wind, srad, lrad |
| ERA5 forcing | ECMWF CDS | NetCDF, 0.25° hourly | tp, t2m, sp, u10, v10, ssrd, strd |
| ISIMIP forcing | ISIMIP server | NetCDF, 0.5° daily | pr, tas, tasmin, tasmax, ps, sfcWind, rsds, rlds, huss |
| MSWX forcing | GloH2O | NetCDF, 0.1° 3-hourly | Similar to CMFD |

## Outputs

| Output | Format | Variables | Unit |
|--------|--------|-----------|------|
| precipitation.nc | NetCDF (time,lat,lon) | precipitation | kg m⁻² s⁻¹ |
| tavg.nc | NetCDF | tavg | K |
| tmin.nc, tmax.nc | NetCDF | tmin, tmax | K |
| psurf.nc | NetCDF | psurf | Pa |
| wind.nc | NetCDF | wind | m/s |
| rsds.nc | NetCDF | rsds | W/m² |
| rsdl.nc | NetCDF | rsdl | W/m² |
| qair.nc or rhs.nc | NetCDF | qair or rhs | kg/kg or % |

## Procedure

1. **Identify input data source and units**: Check the source documentation for exact variable units. This is critical — silent errors arise from wrong assumptions.

2. **Subset spatially**: Extract the bounding box covering your study area plus a small buffer.

3. **Convert units**: Apply the correct conversions for CWatM's expected input format:

   | Source → CWatM | Conversion |
   |----------------|------------|
   | CMFD prec (kg/m²/s) → CWatM | No conversion (set `precipitation_coversion = 86.4`) |
   | ERA5 tp (m/day) → CWatM | ÷86400 to get kg/m²/s (then `precipitation_coversion = 86.4`) |
   | ISIMIP pr (kg/m²/s) → CWatM | No conversion |
   | mm/day → CWatM | Set `precipitation_coversion = 0.001` |
   | ERA5 ssrd (J/m²/day) → W/m² | ÷86400 |
   | ERA5 u10/v10 → wind speed | sqrt(u10² + v10²) |
   | CMFD temp (K) → CWatM | No conversion (set `TemperatureInKelvin = True`) |
   | Celsius → CWatM | +273.15 or set `TemperatureInKelvin = False` |

4. **Clip shortwave radiation**: Ensure SW >= 0 (interpolation artifacts can produce negative values).

5. **Aggregate temporal resolution**: If sub-daily data, aggregate to daily:
   - Temperature: daily mean (Tavg), min (Tmin), max (Tmax)
   - Precipitation: daily sum (then convert to rate)
   - Radiation: daily mean
   - Wind: daily mean
   - Pressure: daily mean
   - Humidity: daily mean

6. **Write NetCDF**: CF-compliant with standard_name attributes, WGS84 coordinates.

7. **Validate outputs**: Check physical ranges of all variables.

## Verification

Run these checks on every converted forcing variable:

| Variable | Reasonable Range | Red Flag |
|----------|-----------------|----------|
| Precipitation (kg/m²/s) | 0 to 0.01 | > 0.1 means likely mm/day not kg/m²/s |
| Temperature (K) | 220 to 330 | < 100 means Celsius |
| Shortwave (W/m²) | 0 to 500 | < 0 means clipping needed |
| Longwave (W/m²) | 100 to 500 | < 50 is suspicious |
| Pressure (Pa) | 50000 to 110000 | < 2000 means hPa not Pa |
| Wind (m/s) | 0 to 30 | > 50 means km/hr not m/s |
| Specific humidity (kg/kg) | 0 to 0.04 | > 1 means wrong units |
| Relative humidity (%) | 0 to 100 | < 1 means fraction not % |

## Traps

1. **precipitation_coversion = 86.4 trap**: This is the MOST critical setting. 86.4 converts kg/m²/s to m/day (= 86400 s/day ÷ 1000 mm/m). If your input is already m/day, set to 1.0. If mm/day, set to 0.001. Wrong value → wrong by 86.4× or 86400×.

2. **Temperature Kelvin/Celsius mismatch**: No error is raised. Snow will never melt (if Celsius interpreted as Kelvin) or always melt (if Kelvin interpreted as Celsius).

3. **ERA5 accumulated radiation**: ERA5 provides radiation as accumulated J/m² per forecast step, NOT instantaneous W/m². Must divide by accumulation period (seconds).

4. **Wind speed zero**: If wind data is missing/zero, Penman-Monteith ET will be severely underestimated.

5. **Humidity variable choice**: CWatM can use either specific humidity (`QAirMaps`) or relative humidity (`RhsMaps`). Set `useHuss = True` for specific humidity, `False` for relative humidity.

## Example

```python
# Convert CMFD precipitation to CWatM format
# CMFD provides prec in kg/m²/s (= mm/s)
# CWatM settings: precipitation_coversion = 86.4
# Internal: m/day = kg/m²/s × 86.4

import netCDF4 as nc
import numpy as np

# Read CMFD
ds_in = nc.Dataset("cmfd_prec_2010.nc")
prec = ds_in.variables["prec"][:]  # kg/m²/s, shape (8760, nlat, nlon)

# Aggregate 3-hourly to daily (if needed)
prec_daily = prec.reshape(-1, 8, prec.shape[1], prec.shape[2]).mean(axis=1)

# Write CWatM-format NetCDF
ds_out = nc.Dataset("precipitation.nc", "w")
# ... create dimensions, write data as-is (no unit conversion here)
# CWatM's precipitation_coversion = 86.4 handles the conversion internally
```
