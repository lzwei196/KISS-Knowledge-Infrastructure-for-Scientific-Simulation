# EPIC0810 Stage 1 — Weather Preparation

## Purpose
Convert daily forcing data (CMFD, MSWX, NASA POWER, Daymet, GridMET) into the three
files EPIC0810 needs: `.DLY` (daily records), `.WP1` (monthly statistics), `.WND`
(wind direction/speed climatology).

## Inputs
- Forcing source name: one of `cmfd`, `mswx`, `nasa_power`
- Site coordinates (lat, lon) in WGS84 degrees
- Year range (year1, year2) — at least 5 years recommended for WP1 stability
- Output directory and station name

## Outputs
- `<station>.DLY` — daily weather records, fixed-width Fortran `(I6,2I4,6F6.2)`,
  one trailing metadata line.
- `<station>.WP1` — 14 monthly statistics × 12 months
- `<station>.WND` — 16 wind directions × 12 months + 12 monthly average wind speeds

## Procedure
```python
from tools.convert_forcing_to_dly import convert
result = convert(
    source="cmfd",
    lat=35.86, lon=-78.78,
    year1=1995, year2=2014,
    out_dir="/tmp/epic_run1",
    station_name="NCRDU",
    station_id=317079,
    elev=133.5,
)
```

Internally the tool:
1. Calls `ki_tools_common.load_forcing.load_daily_forcing(source, lat, lon, year1, year2)`
2. Validates the dict against physical-range checks (see traps)
3. Writes the three files in the target directory

## Verification
After running, inspect a few records:

```bash
head -5 NCRDU.DLY
# 1995   1   1  10.7  8.33 -3.33  0.00  0.71  2.08
```

Range checks:
- `tmax` between -60..60 °C
- `tmin <= tmax`
- `prcp >= 0`
- `0 <= rh <= 1.0`  (NOT 0..100)
- `0 <= srad <= 50` MJ/m²/day
- `ws >= 0`

## Traps
- **rh in percent vs fraction**: NASA POWER returns RH in percent — divide by 100
- **Solar radiation in W/m²**: must be converted to MJ/m²/day (× 0.0864 for daily mean,
  or × `dayl/1e6` for Daymet)
- **Temperature in Kelvin**: subtract 273.15
- **CMFD precipitation aggregation**: sum 8 × 3-hourly values to get daily total,
  do NOT average them
- **Missing days**: EPIC0810 uses sequential daily records — gaps cause silent
  off-by-one errors. Resample to `freq='D'` and forward-fill any gaps.

## Example
End-to-end:
```python
from tools.convert_forcing_to_dly import convert
import os
result = convert("cmfd", 32.95, 117.39, 2010, 2014, "/tmp/wf",
                 station_name="BENGBU")
assert os.path.getsize(result["dly"]) > 100_000
```
