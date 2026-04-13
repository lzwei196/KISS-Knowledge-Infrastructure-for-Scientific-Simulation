# Weather Data Preparation — Skill Document

> **Stage ID**: s3_weather_prep
> **Pipeline order**: 3 of 8
> **Depends on**: none

## Purpose

Provide the PCSE engine with daily meteorological data via a WeatherDataProvider. This is the most error-prone stage because PCSE uses non-standard units (kJ/m2/day for radiation, cm/day for precipitation) that differ from both VIC and DSSAT. Getting units wrong produces no error — the model runs to completion with plausible-looking but scientifically wrong results.

## Prerequisites

- [ ] Raw weather data available (VIC forcing, station data, or internet access for NASA POWER)
- [ ] Location coordinates known (lat, lon, elevation)
- [ ] Simulation period defined (start/end dates)
- [ ] Knowledge of source data units for conversion

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| IRRAD | float | forcing/station | Daily irradiance — **must be kJ/m2/day** (NOT MJ, NOT W/m2) |
| TMIN | float | forcing/station | Minimum daily temperature (Celsius) |
| TMAX | float | forcing/station | Maximum daily temperature (Celsius) |
| VAP | float | forcing/station | Vapor pressure (**kPa**, NOT hPa) |
| WIND | float | forcing/station | Wind speed at 2m (**m/s**, NOT km/day) |
| RAIN | float | forcing/station | Daily precipitation — **must be cm/day** (NOT mm) |
| SNOWDEPTH | float | optional | Snow depth (cm) |
| lat | float | location | Latitude (decimal degrees) |
| lon | float | location | Longitude (decimal degrees) |
| elev | float | location | Elevation above sea level (meters) |

## Procedure

### Step 1: Choose weather data provider

PCSE offers four options:

**Option A: NASAPowerWeatherDataProvider (easiest, online)**
```python
from pcse.input import NASAPowerWeatherDataProvider
weather = NASAPowerWeatherDataProvider(latitude=52.0, longitude=5.5)
# Automatically fetches NASA POWER data (global, ~0.5 degree, 1981-NRT)
# Units are automatically correct — no conversion needed
```
**Limitation**: Coarse resolution (0.5 degree), only 1981 onward, requires internet.

**Option B: CSVWeatherDataProvider (local CSV files)**
```python
from pcse.input import CSVWeatherDataProvider
weather = CSVWeatherDataProvider('/path/to/weather.csv')
```
Requires specific CSV format (see Step 2).

**Option C: ExcelWeatherDataProvider (local Excel files)**
```python
from pcse.input import ExcelWeatherDataProvider
weather = ExcelWeatherDataProvider('/path/to/weather.xlsx')
```

**Option D: Custom provider from VIC forcing (HydroCraft coupling)**
Use tool `convert_vic_to_pcse_weather` to create CSV files from VIC forcing.

### Step 2: Create CSV weather file (if using Option B)

The CSV format has two sections: header and data.

```csv
## Site Characteristics
Country    = Netherlands
Station    = Wageningen
Description = Example weather data
Source     = VIC forcing
Contact    = user@example.com
Longitude  = 5.5; decimal degrees
Latitude   = 52.0; decimal degrees
Elevation  = 10; meters
AngstromA  = 0.18; Angstrom A coefficient
AngstromB  = 0.55; Angstrom B coefficient
HasSunshine = False

## Daily weather observations
DAY,IRRAD,TMIN,TMAX,VAP,WIND,RAIN,SNOWDEPTH
2000-01-01,2500,0.5,5.2,0.65,3.5,0.12,-999
2000-01-02,3100,-1.0,3.8,0.55,2.8,0.00,-999
```

**CRITICAL UNIT RULES**:
- IRRAD: **kJ/m2/day** — typical range 2000-35000. If your values are 2-35, you have MJ — multiply by 1000.
- RAIN: **cm/day** — typical range 0-10. If your values are 0-100, you have mm — divide by 10.
- VAP: **kPa** — typical range 0.1-5.0. If your values are 1-50, you have hPa — divide by 10.
- WIND: **m/s** — typical range 0-15. If your values are 0-500, you have km/day — divide by 86.4.
- TMIN/TMAX: **Celsius** — if values > 200, you have Kelvin — subtract 273.15.

### Step 3: Convert VIC forcing to PCSE weather (HydroCraft coupling)

```python
# VIC forcing columns: PREC(mm), TMAX(C), TMIN(C), WIND(m/s), SW(W/m2), LW(W/m2), VP(kPa), PRESS(kPa)
# PCSE needs: IRRAD(kJ/m2/day), TMIN(C), TMAX(C), VAP(kPa), WIND(m/s), RAIN(cm/day)

# Unit conversions:
IRRAD_kj = sw_wm2 * 86.4       # W/m2 → kJ/m2/day (×3600×24/1000)
RAIN_cm = prec_mm / 10.0        # mm → cm
# TMIN, TMAX, WIND, VAP: no conversion needed (same units)
```

Run tool `convert_vic_to_pcse_weather`:
```bash
python tools/s3_weather_prep/convert_vic_to_pcse_weather.py
```

**Expected result**: One CSV weather file per VIC grid cell in `outputs/{run}/wofost/weather/`.

**If this fails**: Check VIC forcing file column order — it must match the expected layout.

### Step 4: Validate weather data

```python
# Quick validation checks
import pandas as pd
df = pd.read_csv('weather.csv', comment='#')

# IRRAD range check — the #1 silent error
assert df['IRRAD'].max() > 100, \
    f"IRRAD max={df['IRRAD'].max()} — likely in MJ, multiply by 1000!"
assert df['IRRAD'].max() < 50000, \
    f"IRRAD max={df['IRRAD'].max()} — unreasonably high, check units"

# RAIN range check — the #2 silent error
assert df['RAIN'].max() < 50, \
    f"RAIN max={df['RAIN'].max()} — likely in mm, divide by 10!"

# Temperature sanity
assert (df['TMIN'] <= df['TMAX']).all(), "TMIN > TMAX on some days!"
assert df['TMAX'].max() < 60, "TMAX > 60C — check units (Kelvin?)"

# Completeness
date_range = pd.date_range(df['DAY'].min(), df['DAY'].max())
assert len(df) == len(date_range), \
    f"Missing days: expected {len(date_range)}, got {len(df)}"
```

**If this fails**: See diagnostic triplets dt_003 (IRRAD units), dt_004 (RAIN units), dt_011 (weather gaps).

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Weather CSV(s) | `outputs/{run}/wofost/weather/weather_{lat}_{lon}.csv` | Header + daily data; IRRAD 2000-35000 |
| OR WeatherDataProvider | in-memory object | `provider(datetime.date(2000,7,1))` returns data |

## Validation Checks

1. **IRRAD unit check**: Values should be in thousands (kJ/m2/day), NOT single digits (MJ/m2/day)
   - Quick test: `if max(IRRAD) < 100: ERROR — multiply by 1000`
   - If unexpected: See diagnostic triplet dt_003

2. **RAIN unit check**: Values should be in tenths (cm/day), NOT whole numbers (mm/day)
   - Quick test: `if max(RAIN) > 50: WARNING — possibly mm, divide by 10`
   - If unexpected: See diagnostic triplet dt_004

3. **No gaps**: Every day from start to end must have data
   - If unexpected: See diagnostic triplet dt_011

4. **TMIN <= TMAX**: For every day
   - Swapped values indicate column order error

## Common Pitfalls

> **PITFALL**: IRRAD in MJ/m2/day instead of kJ/m2/day (THE MOST COMMON ERROR)
> DSSAT uses MJ/m2/day. If you copy DSSAT weather conversion code, IRRAD will be 1000x too low. Photosynthesis approaches zero. Yield is near-zero. **No error message.**
> **Do this instead**: Always multiply MJ by 1000 to get kJ. Verify: typical clear-sky summer IRRAD is 20000-30000 kJ/m2/day.
> See diagnostic triplet dt_003.

> **PITFALL**: RAIN in mm/day instead of cm/day
> VIC, DSSAT, and most datasets use mm. PCSE uses cm. If you forget to divide by 10, precipitation is 10x too high. Soil is permanently waterlogged. Yield drops. **No error message.**
> **Do this instead**: Always divide mm by 10 for PCSE. Verify: typical daily rainfall in cm is 0-5.
> See diagnostic triplet dt_004.

> **PITFALL**: NASAPowerWeatherDataProvider timeout
> The NASA POWER API can be slow or unavailable. If it times out, the provider raises an exception and the simulation cannot start.
> **Do this instead**: Wrap in try/except, have CSV fallback ready. For batch runs, download all data first.
> See diagnostic triplet dt_015.

---

*This skill document is part of the wofost-pcse-knowledge infrastructure.*
*Stage 3 of 8 | Tools: convert_vic_to_pcse_weather, create_csv_weather_file, validate_weather_data | Related triplets: dt_003, dt_004, dt_011, dt_015*
