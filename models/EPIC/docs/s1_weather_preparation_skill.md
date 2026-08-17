# Stage 1: Weather Data Preparation

## Purpose

Acquire and convert meteorological data from external sources (Daymet, GridMET,
NASA POWER, AgERA5) to EPIC's fixed-width .DLY daily weather format. Also
generate the monthly statistics file (.WP1) and wind file (.WND) needed by
EPIC's weather generator.

## Prerequisites

- Stage 0 (Configuration) completed
- Internet access for data download (or pre-cached data)
- For US locations: Daymet + GridMET available
- For global locations: NASA POWER or AgERA5

## Inputs

| Input | Source | Variables | Units |
|-------|--------|-----------|-------|
| Daymet | ORNL API | prcp, tmax, tmin, srad, vp, dayl | mm, C, W/m2, Pa, s |
| GridMET | THREDDS | tmmx, tmmn, srad, pr, rmax, rmin, vs | K, W/m2, mm, %, m/s |
| NASA POWER | API | T2M_MAX, T2M_MIN, ALLSKY_SFC_SW_DWN, PRECTOTCORR, RH2M, WS2M | C, MJ/m2/d, mm/hr, %, m/s |
| AgERA5 | GEE | Temperature, radiation, precipitation, humidity, wind | Various |

## Outputs

| Output | Format | Location |
|--------|--------|----------|
| {site}.DLY | Fixed-width text | weather/ |
| {site}.WP1 | Monthly statistics | weather/ |
| {site}.WND | Wind data | weather/ |

## Procedure

### Using Geo-EPIC built-in tools

```python
from geoEpic.io import DLY

# Fetch weather for a location
dly = DLY.from_daymet(lat=41.5, lon=-93.5, start='2015-01-01', end='2020-12-31')
dly.save('weather/site1.DLY')

# Generate WP1 and WND
dly.to_monthly('weather/site1.WP1')
```

### Using the KI converter tool

```bash
python tools/convert_weather_to_dly.py \
  --source nasa_power \
  --input KISSPATH_ROOT/.../nasa_power_cache/hourly/ \
  --output weather/site1.DLY \
  --lat 41.5 --lon -93.5 \
  --start-year 2015 --end-year 2020
```

### Unit Conversion Details

| Source | Variable | Source Unit | EPIC Unit | Conversion |
|--------|----------|-----------|-----------|------------|
| Daymet | srad | W/m2 | MJ/m2/day | `srad * dayl_s / 1e6` |
| Daymet | vp | Pa | RH fraction | `rh_vappr(vp, tmax, tmin)` |
| GridMET | tmmx/tmmn | K | deg C | `T - 273.15` |
| GridMET | srad | W/m2 | MJ/m2/day | `srad * 0.0864` |
| GridMET | rmax/rmin | % | fraction | `avg(rmax,rmin) / 100` |
| GridMET | pr | mm/day | mm/day | None |
| NASA POWER | RH2M | % | fraction | `/ 100` |
| NASA POWER | PRECTOTCORR | mm/hr | mm/day | `sum(24 hr)` |

### RH from Vapor Pressure (Daymet)

```python
def rh_vappr(vp_Pa, tmax, tmin):
    """Convert vapor pressure to relative humidity fraction."""
    T = (tmax + tmin) / 2.0
    dewpt = (243.04 * np.log(vp_Pa / 611.0)) / (17.625 - np.log(vp_Pa / 611.0))
    rh = np.exp((17.625 * dewpt) / (243.04 + dewpt)) / \
         np.exp((17.625 * T) / (243.04 + T))
    return np.clip(rh, 0.0, 1.0)
```

## Verification

1. Check DLY file has correct number of lines (365/366 per year)
2. Verify value ranges:
   - srad: 0-45 MJ/m2/day (0 in winter nights is OK)
   - tmax > tmin always
   - tmax: -50 to 55 deg C
   - prcp: 0-500 mm/day
   - rh: 0.0-1.0 (MUST be fraction, not percentage)
   - ws: 0-40 m/s

3. Check last line contains station metadata

## Traps

| Trap | Symptom | Root Cause | Fix |
|------|---------|------------|-----|
| srad in W/m2 not MJ | Peak biomass too high, early maturity | Forgot `* 0.0864` | Multiply by 0.0864 |
| srad missing dayl | Srad ~86x too high | Daymet srad needs `* dayl / 1e6` | Apply dayl conversion |
| Temp in Kelvin | EPIC crash or >200C temps | GridMET not converted | Subtract 273.15 |
| RH in % not fraction | Extreme evaporation, crop death | Source gives 0-100 | Divide by 100 |
| RH > 1.0 | RH capped at 1.0 anyway | Formula error | Clip to [0, 1] |
| Precip averaged not summed | Very low precipitation | Hourly→daily: must SUM | Use sum() not mean() |
| Wrong date range | Simulation runs with generated weather | DLY doesn't cover sim period | Extend DLY to cover start_date + duration |
| Wind from wrong source | Wind = 0 everywhere | Daymet has no wind | Must get wind from GridMET or other source |

## Example

```python
import pandas as pd
from geoEpic.io import DLY

# Load and inspect
dly = DLY.load('weather/NCRDU.DLY')
print(f"Records: {len(dly.data)}")
print(f"Date range: {dly.data.iloc[0][['year','month','day']]} to {dly.data.iloc[-1][['year','month','day']]}")
print(f"Srad range: {dly.data['srad'].min():.1f} - {dly.data['srad'].max():.1f} MJ/m2/day")
print(f"RH range: {dly.data['rh'].min():.2f} - {dly.data['rh'].max():.2f}")
```
