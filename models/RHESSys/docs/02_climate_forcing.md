# Stage 2: Climate Forcing Preparation

## Purpose

Convert global or regional meteorological data into RHESSys ASCII forcing files.
RHESSys requires separate files for each climate variable, with a date header
line followed by one value per day.

## Inputs

| Input | Format | Source | Variables |
|-------|--------|--------|-----------|
| Daily temperature | CSV/NetCDF | ERA5, CMFD, MSWX, NASA POWER | Tmax, Tmin (C) |
| Daily precipitation | CSV/NetCDF | ERA5, CMFD, MSWX, NASA POWER | Precip (mm/day) |
| Relative humidity | CSV (optional) | ERA5, stations | RH (%) |
| Wind speed | CSV (optional) | ERA5, stations | Wind (m/s) |
| Radiation | CSV (optional) | ERA5, stations | SW_down (W/m^2) |

## Outputs

| Output | Format | Extension | Unit |
|--------|--------|-----------|------|
| Max temperature | ASCII daily | `.tmax` | deg C |
| Min temperature | ASCII daily | `.tmin` | deg C |
| Precipitation | ASCII daily | `.rain` | **m/day** |
| Relative humidity | ASCII daily | `.relative_humidity` | fraction (0-1) |
| Wind speed | ASCII daily | `.wind` | m/s |

## Procedure

### Step 1: Extract Point Data

If using gridded data (ERA5, CMFD), extract the nearest grid cell to the
watershed centroid or climate station location.

### Step 2: Unit Conversion

**CRITICAL CONVERSIONS:**

| Variable | Source Unit | Target Unit | Formula |
|----------|-----------|-------------|---------|
| Precipitation | mm/day | **m/day** | `P_m = P_mm / 1000.0` |
| Temperature | K | deg C | `T_C = T_K - 273.15` |
| Relative humidity | % | fraction | `RH_frac = RH_pct / 100.0` |

**TRAP dt_001:** If precipitation remains in mm/day, all water fluxes
(streamflow, ET, storage) will be **1000x too high**. This is the most common
and most dangerous error in RHESSys setup.

**TRAP dt_003:** ERA5 and some reanalysis products report temperature in Kelvin.
If not converted, the model receives temperatures of ~290 C, causing absurd
evaporation and immediate water balance failure.

### Step 3: Write ASCII Files

Format per file:
```
YYYY M D HH
value_day1
value_day2
value_day3
...
```

Example (precipitation in m/day):
```
1988 10 1 01
0.000000
0.002341
0.015678
0.000000
```

The header date is the **start date** of the time series. Each subsequent line
is one day forward. No date column in the body — the model infers dates from
the header and line position.

### Step 4: Base Station File

The base station file links climate files to the model:
```
101                    base_station_ID
w8_daily               base_station_filename
100.0                  x
200.0                  y
574.0                  z (elevation, m)
0.0                    effective_lai
0                      screen_height
```

### Step 5: Validate

```bash
# Check file lengths match (all variables should have same number of days)
wc -l clim/w8_daily.tmax clim/w8_daily.tmin clim/w8_daily.rain

# Check precipitation range (should be 0 to ~0.3 m/day max)
python3 -c "
vals = [float(x) for x in open('clim/w8_daily.rain').readlines()[1:] if x.strip()]
print(f'Rain: min={min(vals):.4f} max={max(vals):.4f} mean={sum(vals)/len(vals):.4f} m/day')
if max(vals) > 1.0:
    print('WARNING: max > 1 m/day (1000 mm/day) — likely still in mm!')
"

# Check temperature range (should be -40 to 50 C)
python3 -c "
vals = [float(x) for x in open('clim/w8_daily.tmax').readlines()[1:] if x.strip()]
print(f'Tmax: min={min(vals):.1f} max={max(vals):.1f} C')
if max(vals) > 100:
    print('WARNING: max > 100 C — likely still in Kelvin!')
"
```

## Tool

```bash
python ki/tools/convert_forcing.py \
  --input forcing_data.csv \
  --output-dir clim/ \
  --prefix site_daily \
  --precip-unit mm \
  --temp-unit C \
  --start-date "1988-10-01"
```

## Traps

| Trap | Symptom | Magnitude | Fix | Triplet |
|------|---------|-----------|-----|---------|
| Precip in mm not m | Streamflow 1000x too high | x1000 | Divide by 1000 | dt_001 |
| Temp in K not C | Extreme ET, rapid drying | ~260 C offset | Subtract 273.15 | dt_003 |
| Wrong start date header | All output shifted in time | variable | Correct header | — |
| Missing days in series | Model reads wrong values | variable | Fill gaps | — |
| RH as % not fraction | Over-estimated humidity | x100 | Divide by 100 | — |

## Example

The test case uses climate from HJ Andrews Experimental Forest:
- `source/repo/Testing/clim/w8_daily.tmax` (1988-2000, deg C)
- `source/repo/Testing/clim/w8_daily.tmin` (1988-2000, deg C)
- `source/repo/Testing/clim/w8_daily.rain` (1988-2000, m/day)
