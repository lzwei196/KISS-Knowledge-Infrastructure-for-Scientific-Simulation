# Stage 1: Climate Forcing Preparation

## Purpose

Convert global or station meteorological data into the MONICA `climate.csv` format.
MONICA requires daily weather data in a specific semicolon-separated CSV with a
two-row header (column names + units).

## Inputs

| Source               | Format        | Typical variables                          |
|----------------------|---------------|--------------------------------------------|
| ERA5 / ERA5-Land     | NetCDF / GRIB | t2m, tp, u10, v10, ssrd, d2m               |
| CMFD / MSWX          | NetCDF        | tmp, pre, srad, wnd, rhu                   |
| Station data         | CSV           | Tmax, Tmin, Precip, Wind, Radiation, RH    |

## Outputs

File: `climate.csv` — semicolon-separated, 2 header rows + daily data rows.

### Required columns

| Column     | MONICA internal name | Unit         | Notes                          |
|------------|---------------------|--------------|--------------------------------|
| iso-date   | iso-date            | YYYY-MM-DD   | or DE-date (DD.MM.YYYY)        |
| tavg       | tavg                | °C           | Mean daily temperature          |
| tmin       | tmin                | °C           | Minimum temperature             |
| tmax       | tmax                | °C           | Maximum temperature             |
| wind       | wind                | m s⁻¹        | Wind speed at measurement height|
| globrad    | globrad             | MJ m⁻² d⁻¹  | Global radiation                |
| precip     | precip              | mm           | Daily precipitation             |
| relhumid   | relhumid            | %            | Relative humidity (0–100)       |

### Optional columns

| Column     | Unit     | Notes                                   |
|------------|----------|-----------------------------------------|
| sunhours   | h        | Used if globrad unavailable              |
| vappd      | kPa      | Vapour pressure deficit                  |
| T_s10      | °C       | Soil temp at 10 cm (initial conditions)  |
| T_s20      | °C       | Soil temp at 20 cm                       |

## Procedure

1. **Read source data** — open CSV or extract point from NetCDF at (lat, lon)
2. **Map columns** — match source variable names to MONICA names
3. **Convert units** — apply conversion factors (see table below)
4. **Fill gaps** — use tmin/tmax to estimate tavg if missing: `tavg = (tmin + tmax) / 2`
5. **Estimate radiation** — if only sunhours available, use Angström formula
6. **Write output** — two-header-row CSV with semicolon separator
7. **Validate** — check physical ranges (T: -60–60°C, P: 0–500 mm, RH: 0–100%)

## Unit Conversion Table

| Variable | Source unit    | MONICA unit    | Conversion              |
|----------|---------------|----------------|-------------------------|
| globrad  | W m⁻²         | MJ m⁻² d⁻¹   | × 0.0864                |
| globrad  | J cm⁻²        | MJ m⁻² d⁻¹   | ÷ 100                   |
| globrad  | kJ m⁻²        | MJ m⁻² d⁻¹   | ÷ 1000                  |
| wind     | km h⁻¹        | m s⁻¹         | ÷ 3.6                   |
| precip   | m d⁻¹         | mm d⁻¹        | × 1000                  |
| relhumid | fraction 0–1  | % 0–100        | × 100                   |
| temp     | K             | °C             | − 273.15                |
| vappd    | mm Hg         | kPa            | × 0.1333                |

## Verification

- [ ] Date column parses correctly and covers the simulation period
- [ ] No gaps in daily time series (every calendar day present)
- [ ] Temperature range plausible for the climate zone
- [ ] globrad values in [0, 40] MJ m⁻² d⁻¹
- [ ] Precipitation non-negative; annual total within expected range
- [ ] RH in [0, 100]% — values outside indicate wrong unit

## Traps

| ID  | Symptom                        | Cause                               | Fix                    |
|-----|-------------------------------|--------------------------------------|------------------------|
| UT1 | Yield 10–100× too high        | globrad in J cm⁻² not MJ m⁻² d⁻¹   | Divide by 100          |
| UT2 | Yield unrealistic, huge LAI   | globrad in W m⁻² not MJ m⁻² d⁻¹    | Multiply by 0.0864     |
| UT5 | ET0 = 0, no transpiration     | relhumid as fraction, not %          | Multiply by 100        |
| UT4 | Unrealistic ET                | wind in km h⁻¹ not m s⁻¹            | Divide by 3.6          |

## Example

```bash
python convert_climate_to_monica.py \
    --input era5_daily.csv --format generic_csv \
    --output climate.csv \
    --date-col time --date-fmt "%Y-%m-%d" \
    --tavg-col t2m_mean --tmin-col t2m_min --tmax-col t2m_max \
    --precip-col tp --wind-col u10 --globrad-col ssrd \
    --relhumid-col rh \
    --globrad-unit W_m2 --precip-unit m
```
