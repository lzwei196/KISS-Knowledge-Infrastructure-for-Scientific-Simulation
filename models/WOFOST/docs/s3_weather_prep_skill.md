# Weather Data Preparation — Skill Document

> **Stage ID**: s3_weather_prep
> **Pipeline order**: 3 of 8
> **Depends on**: none

## Purpose

Provide the PCSE engine with daily meteorological data via a WeatherDataProvider. This is the most error-prone stage because PCSE uses non-standard *internal* units (kJ/m2/day for radiation, cm/day for precipitation) that differ from DSSAT and from the weather products — but note the **CSVWeatherDataProvider CSV columns are mm/day for RAIN** (provider divides /10 → cm) and kJ/m2/day for IRRAD; the provider does the unit scaling, so author the CSV in mm. Getting units wrong produces no error — the model runs to completion with plausible-looking but scientifically wrong results.

## Prerequisites

- [ ] Weather source chosen: a product read by the shared loader (`cmfd` China, `mswx` global local disk, `nasa_power` global, needs the network) or your own station table
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
| RAIN | float | forcing/station | Daily precipitation — **mm/day in the CSV** (CSVWeatherDataProvider divides by 10 → cm internally) |
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

**Option D: CSV built straight from a weather product (the HydroCraft route)**
Use tool `build_pcse_weather_from_source` (Step 3): CMFD, MSWX or NASA POWER, read through the shared loader, written as the Option B CSV.

### Step 2: Create CSV weather file (if using Option B)

The CSV format has two sections: header and data.

```csv
## Site Characteristics
Country = 'Netherlands'
Station = 'Wageningen'
Description = 'Example weather data'
Source = 'station file'
Contact = 'user@example.com'
Longitude = 5.5; Latitude = 52.0; Elevation = 10.0; AngstromA = 0.18; AngstromB = 0.55; HasSunshine = False
## Daily weather observations (missing values are NaN)
DAY,IRRAD,TMIN,TMAX,VAP,WIND,RAIN,SNOWDEPTH
20000101,2500.0,0.5,5.2,0.650,3.5,1.2000,NaN
20000102,3100.0,-1.0,3.8,0.550,2.8,0.0000,NaN
```

**HEADER RULES** (pcse 6.0.12 runs `ast.literal_eval` on every header value): text values are quoted; the site line is ONE line of `name = value` pairs split by `;` with no comments after the values; `DAY` is `YYYYMMDD`; a missing value is `NaN`, not `-999`. Do not hand-write this file: both stage tools write it through the same writer (`write_pcse_csv` in `create_csv_weather_file.py`).

**CRITICAL UNIT RULES**:
- IRRAD: **kJ/m2/day** — typical range 2000-35000. If your values are 2-35, you have MJ — multiply by 1000.
- RAIN: **mm/day** — typical range 0-100. CSVWeatherDataProvider divides this column by 10 → cm/day internally. **Do NOT pre-convert to cm**; writing cm here makes rainfall 10x too low (drought, poor yield).
- VAP: **kPa** — typical range 0.1-5.0. If your values are 1-50, you have hPa — divide by 10.
- WIND: **m/s** — typical range 0-15. If your values are 0-500, you have km/day — divide by 86.4.
- TMIN/TMAX: **Celsius** — if values > 200, you have Kelvin — subtract 273.15.

### Step 3: Build the PCSE weather file from a weather product

One tool, one point, straight from the data source:

```bash
PY=KISSPATH_PYTHON_ENV/bin/python
# NASA POWER (global, needs the network; the loader goes around the proxy)
$PY tools/s3_weather_prep/build_pcse_weather_from_source.py --source nasa_power \
    --lat 41.5 --lon -93.5 --elev 300 --start_year 2016 --end_year 2020 \
    --output weather_pcse_41.50_-93.50.csv
# CMFD (China, local 3-hourly store, about 50 s per point-year)
$PY tools/s3_weather_prep/build_pcse_weather_from_source.py --source cmfd \
    --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg \
    --lat 36.5 --lon 116.5 --elev 30 --start_year 2015 --end_year 2015 \
    --output weather_pcse_36.50_116.50.csv
# MSWX (global, local): --source mswx --forcing_dir KISSPATH_FORCING   (ONE build at a time)
```

`--source` has no default. What the tool does:

| Loader value (`load_daily_forcing`) | PCSE CSV column | Conversion |
|---|---|---|
| `srad_wm2` (24-h mean W/m2) | `IRRAD` kJ/m2/day | × 86.4 |
| `temp_min_c`, `temp_max_c` | `TMIN`, `TMAX` °C | none |
| `shum_kgkg` + `pres_pa` (the source's own pressure) | `VAP` kPa | e = q·p / (0.622 + 0.378·q), ÷ 1000 |
| `wind_ms` | `WIND` m/s | none (source height, 10 m) |
| `precip_mm` (mm in the day) | `RAIN` mm/day | none |
| — | `SNOWDEPTH` | NaN |

**Expected result**: the CSV plus `<output>.summary.json` (source, point, period, rain per year, mean temperature). Read the summary and check the numbers are believable for the site. Checked 2026-10-03: `nasa_power` (41.5, -93.5) 2016-2020 = 1827 days, 862 mm/yr, 10.3 °C; `cmfd` (36.5, 116.5) 2015 = 365 days, 617 mm, 15.7 °C.

**If this fails** (exit code 2, nothing written): the tool refuses a missing or non-finite value, a time axis that is not one row per day, a period the source does not fully cover (NASA POWER daily starts 1981; CMFD is China only) and impossible values. Pick another source or period. Do not patch the gap by hand. See dt_023.

**Many points**: give every point its own output file name. PCSE caches a loaded CSV under the file's basename, so two files with the same name in different folders can return the first one's weather (dt_022).

**Own station data**: put it in a daily CSV (`date,IRRAD,TMIN,TMAX,VAP,WIND,RAIN`) and run `create_csv_weather_file.py <in.csv> <lat> <lon> <out.csv> [elev]`; unit flags are the `WX_*` environment variables listed in that tool.

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

# RAIN range check — the #2 silent error (CSV column is mm/day; provider divides /10 → cm)
assert df['RAIN'].max() < 500, \
    f"RAIN max={df['RAIN'].max()} mm — unreasonably high for mm/day, check units"

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

2. **RAIN unit check**: CSV column is **mm/day** (CSVWeatherDataProvider divides by 10 → cm internally). Do NOT pre-convert to cm.
   - Quick test: `if max(RAIN) > 500: WARNING — unreasonably high for mm/day`
   - If unexpected: See diagnostic triplets dt_004, dt_016

3. **No gaps**: Every day from start to end must have data
   - If unexpected: See diagnostic triplet dt_011

4. **TMIN <= TMAX**: For every day
   - Swapped values indicate column order error

## Common Pitfalls

> **PITFALL**: IRRAD in MJ/m2/day instead of kJ/m2/day (THE MOST COMMON ERROR)
> DSSAT uses MJ/m2/day. If you copy DSSAT weather conversion code, IRRAD will be 1000x too low. Photosynthesis approaches zero. Yield is near-zero. **No error message.**
> **Do this instead**: Always multiply MJ by 1000 to get kJ. Verify: typical clear-sky summer IRRAD is 20000-30000 kJ/m2/day.
> See diagnostic triplet dt_003.

> **PITFALL**: pre-dividing the CSV RAIN column to cm/day
> The CSVWeatherDataProvider RAIN column is **mm/day** — PCSE divides it by 10 to get the model's internal cm/day. If you also divide mm→cm yourself, precipitation reaches the soil 10x too low. The crop is chronically water-stressed. Yield drops. **No error message.** (Only a hand-built WeatherDataContainer / the internal model variable use cm/day directly.)
> **Do this instead**: Pass mm/day straight into the CSV RAIN column; let the provider do the /10. Verify: typical daily rainfall in mm is 0-50.
> See diagnostic triplets dt_004, dt_016.

> **PITFALL**: NASAPowerWeatherDataProvider timeout
> The NASA POWER API can be slow or unavailable. If it times out, the provider raises an exception and the simulation cannot start.
> **Do this instead**: Wrap in try/except, have CSV fallback ready. For batch runs, download all data first.
> See diagnostic triplet dt_015.

---

*This skill document is part of the wofost-pcse-knowledge infrastructure.*
*Stage 3 of 8 | Tools: build_pcse_weather_from_source, create_csv_weather_file, validate_weather_data | Related triplets: dt_003, dt_004, dt_011, dt_015, dt_017-dt_023*
