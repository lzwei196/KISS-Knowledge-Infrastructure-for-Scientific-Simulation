# Weather Data Preparation -- Skill Document

> **Stage ID**: s3_weather_prep
> **Pipeline order**: 3 of 10
> **Depends on**: none

## Purpose

Prepare the daily weather DataFrame that drives the AquaCrop simulation. This is the **most error-prone stage** because AquaCrop requires a specific DataFrame format with pre-computed reference evapotranspiration (ET0), which most raw data sources do not provide. Unlike DSSAT (which computes ET internally from radiation/wind/humidity), AquaCrop expects ET0 as an input variable.

## Prerequisites

- [ ] Daily weather data available for the simulation period
- [ ] If ET0 is not in source data: solar radiation, wind speed, and humidity data available for Penman-Monteith computation
- [ ] Latitude and elevation of the site (needed for ET0 computation)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| weather_source | file/DataFrame | VIC forcing, CMFD, MSWX, local station | Raw daily weather data |
| lat | float | Site location | Latitude in degrees (for ET0 computation) |
| elevation | float | DEM | Elevation in meters (for ET0 computation) |

## Procedure

### Step 1: Determine data source and available variables

| Source | Available Variables | ET0 Available? | Action |
|--------|-------------------|---------------|--------|
| AquaCrop sample files | MinTemp, MaxTemp, Precip, ET0 | Yes | Use `prepare_weather()` directly |
| VIC forcing | Tmin, Tmax, Precip, SWrad, LWrad, Wind, Pressure, Humidity | No | Compute ET0 via Penman-Monteith |
| CMFD/MSWX | Same as VIC | No | Compute ET0 via Penman-Monteith |
| Local station | Tmin, Tmax, Precip, possibly SWrad | Maybe | Compute ET0 or use Hargreaves if only T available |
| NASA POWER | Tmin, Tmax, Precip, SWrad, LWrad, Wind, Humidity | No | Compute ET0 via Penman-Monteith |

### Step 2A: Load from AquaCrop text file

```python
from aquacrop.utils import prepare_weather
weather_df = prepare_weather('/path/to/weather.txt')
```

File format: whitespace-separated, 7 columns, no header:
```
Day Month Year MinTemp MaxTemp Precipitation ReferenceET
1   1     2000 2.1     12.5    0.0           1.2
2   1     2000 1.8     11.9    3.2           1.1
```

### Step 2B: Construct DataFrame from VIC/CMFD/MSWX

```python
import pandas as pd
import numpy as np

# After extracting VIC forcing variables for the grid cell:
weather_df = pd.DataFrame({
    'MinTemp': daily_tmin,          # deg C
    'MaxTemp': daily_tmax,          # deg C
    'Precipitation': daily_precip,  # mm/day
    'ReferenceET': daily_et0,       # mm/day (MUST compute first!)
    'Date': pd.date_range(start='2000-01-01', periods=N, freq='D')
})
```

### Step 3: Compute ET0 if not available

Use FAO-56 Penman-Monteith method. Run tool `compute_eto_penman_monteith`.

**Simplified Hargreaves** (if only temperature available):
```python
# Hargreaves-Samani equation (less accurate than PM):
et0 = 0.0023 * (tmax - tmin)**0.5 * ((tmax + tmin)/2 + 17.8) * Ra
# where Ra = extraterrestrial radiation (MJ/m2/day) from latitude and DOY
```

### Step 4: Validate the DataFrame

Run tool `validate_weather_df`. Checks:
- All 5 required columns present: `MinTemp`, `MaxTemp`, `Precipitation`, `ReferenceET`, `Date`
- Column names are EXACTLY as shown (case-sensitive)
- No NaN values
- `MaxTemp >= MinTemp` for all rows
- `Precipitation >= 0` for all rows
- `ReferenceET > 0` for all rows (clipped to 0.1 internally)
- No missing days in the Date column

**If this fails**: See diagnostic triplets dt_001 (missing ET0), dt_007 (wrong column names).

### Step 5: Clip to simulation period

The weather DataFrame must cover at least `sim_start_time` to `sim_end_time`. Extra days are acceptable (AquaCrop will subset internally).

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| weather_df | in-memory DataFrame | `len(weather_df) >= (end_date - start_date).days`, all 5 columns present |

## Validation Checks

1. **Column presence**: `set(['MinTemp','MaxTemp','Precipitation','ReferenceET','Date']).issubset(df.columns)`
   - If missing column: ValueError at model construction. See dt_007.

2. **ET0 positivity**: `weather_df.ReferenceET.min() >= 0.1`
   - If zero/negative: divide-by-zero errors during simulation. See dt_001.

3. **Temperature range**: `-50 < MinTemp < MaxTemp < 60` for all rows
   - If units are Kelvin (values > 200): convert to Celsius first. See common failure pattern cfp_005.

4. **Date continuity**: `weather_df.Date.diff().dropna().unique()` should be `[timedelta(days=1)]`
   - If gaps: model may produce wrong results for missing days.

## Common Pitfalls

> **PITFALL**: Missing ReferenceET column (most common error)
> AquaCrop REQUIRES pre-computed ET0. Most raw weather data does not include it. The symptom is ValueError: "Check if all the following columns exist (Date MinTemp MaxTemp Precipitation ReferenceET)."
> **Do this instead**: Compute ET0 using FAO Penman-Monteith before creating the DataFrame.
> See diagnostic triplet dt_001.

> **PITFALL**: Column name capitalization mismatch
> AquaCrop expects `MinTemp` not `min_temp`, `ReferenceET` not `ET0` or `ETo` or `ref_et`. Case matters.
> **Do this instead**: Rename columns to exact AquaCrop format: `df.rename(columns={'tmin': 'MinTemp', ...})`
> See diagnostic triplet dt_007.

> **PITFALL**: Precipitation in mm/timestep instead of mm/day
> VIC forcing provides precipitation per timestep (3-hourly = mm/3hr). Must sum to daily before passing to AquaCrop.
> **Do this instead**: Resample to daily: `daily_precip = hourly_precip.resample('D').sum()`

---

*This skill document is part of the aquacrop-ospy-knowledge infrastructure.*
*Stage 3 of 10 | Tools used: prepare_weather_df, compute_eto_penman_monteith, validate_weather_df | Related triplets: dt_001, dt_007*
