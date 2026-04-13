# S3: Meteorological Forcing Preparation

## Purpose

Convert global reanalysis or station-based meteorological data into tRIBS
forcing format. This includes station metadata files (.sdf) and per-station
time-series data files (.mdf) with the correct units and column structure.

Meteorological forcing drives evapotranspiration, snow processes, and energy
balance calculations. Incorrect units here produce **silent failures** — the
model runs but produces systematically wrong ET and water balance.

## Inputs

| Input | Format | Units (source) | Source |
|-------|--------|----------------|--------|
| Air temperature | NetCDF, CSV | K (reanalysis) or °C (station) | ERA5, CMFD, MSWX |
| Dew-point temperature or RH | NetCDF, CSV | K or % or fraction | ERA5, CMFD |
| Atmospheric pressure | NetCDF, CSV | Pa (reanalysis) | ERA5, CMFD |
| Wind speed (u, v components) | NetCDF, CSV | m/s | ERA5, CMFD |
| Shortwave radiation | NetCDF, CSV | W/m² | ERA5, CMFD |
| Cloud cover / sky cover | NetCDF, CSV | fraction (0–1) or tenths | ERA5 |
| Rainfall rate | NetCDF, CSV | m/s or mm/day or mm/hr | varies |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Station metadata (`.sdf`) | Text | Station count, ID, lat, lon, elev, filepath |
| Time-series data (`.mdf`) | Space-delimited text | Y M D H PA TD XC US TA TS NR |

## Procedure

### Step 1: Download and extract source data
Select the nearest grid cell(s) or station(s) to the basin centroid.

### Step 2: Apply unit conversions

**CRITICAL — these are the most common sources of silent error:**

| Variable | Source → tRIBS | Conversion | Trap |
|----------|---------------|------------|------|
| Temperature | K → °C | T_C = T_K − 273.15 | dt_002 |
| Pressure | Pa → mb (hPa) | P_mb = P_Pa / 100 | dt_004 |
| RH | % → fraction (0–1) | RH_frac = RH_pct / 100 | dt_003 |
| RH | fraction already | No conversion needed | — |
| Dew point | K → °C | Same as temperature | dt_002 |
| Sky cover | fraction (0–1) → tenths (0–10) | XC = frac × 10 | — |
| Vapor pressure | kPa → mb | VP_mb = VP_kPa × 10 | dt_011 |
| Wind speed | m/s → m/s | No conversion | — |
| Radiation | W/m² → W/m² | No conversion | — |

### Step 3: Compute derived variables if needed
- **Dew point from RH**: Use Magnus formula
  ```
  alpha = (17.27 × T) / (237.7 + T) + ln(RH)
  Td = (237.7 × alpha) / (17.27 − alpha)
  ```
- **Wind speed from components**: `WS = sqrt(u² + v²)`
- **Net radiation**: If only shortwave provided, estimate longwave

### Step 4: Write tRIBS format files

```bash
python convert_met_forcing.py \
    --source era5 \
    --input /path/to/era5_data/ \
    --output /path/to/met/ \
    --lat 33.5 --lon 117.2 --elev 450
```

### Step 5: Configure control file
```
HYDROMETFILE
/path/to/met/station.sdf
METDATAOPTION
1
METSTEP
1
```
**Note:** METSTEP is in **hours** (not minutes!). Setting METSTEP=60 means
60-hour intervals, not 60-minute.

## Verification

- [ ] Temperature values are in °C (typical range: -40 to +50)
- [ ] Pressure values are in mb/hPa (typical: 500–1050 mb)
- [ ] Dew point ≤ air temperature at all times
- [ ] Relative humidity in range 0–1 (not 0–100)
- [ ] Wind speed is non-negative (typical: 0–25 m/s)
- [ ] Shortwave radiation is non-negative, zero at night
- [ ] Sky cover in range 0–10 (tenths)
- [ ] No gaps in time series (tRIBS interpolates but may produce artifacts)
- [ ] METSTEP matches actual data interval (in hours)
- [ ] Station coordinates match basin location

## Traps

| Trap ID | Symptom | Root Cause | Fix |
|---------|---------|------------|-----|
| dt_002 | ET is enormous or zero, snow never forms | Temperature in K instead of °C (values ~293 instead of ~20) | Subtract 273.15 |
| dt_003 | ET wildly high, lake/soil dries instantly | RH=65 instead of 0.65 | Divide by 100 |
| dt_004 | Wrong psychrometric calculations, bad ET | Pressure in Pa (~101325) instead of mb (~1013) | Divide by 100 |
| dt_010 | Huge gaps in forcing, artifacts | METSTEP in minutes instead of hours | Divide by 60 |
| dt_011 | Wrong dew point, ET errors | Vapor pressure in kPa instead of mb | Multiply by 10 |

## Example

### Station metadata file (.sdf)
```
1
1  33.500000  117.200000  450.0  /path/to/met/station_1.mdf
```

### Time-series data file (.mdf)
```
Y  M  D  H  PA  TD  XC  US  TA  TS  NR
2020  01  01  00  1013.25  5.20  7.0  3.50  8.40  7.80  0.00
2020  01  01  01  1013.10  5.10  8.0  3.20  8.10  7.50  0.00
2020  01  01  06  1012.80  4.80  5.0  2.80  9.50  8.90  120.50
```
