# s1 Forcing preparation (real engine): weather time functions

## Purpose
Produce the five daily weather series that the WASP 8.5 heat module and wind-driven reaeration
read: solar radiation, air temperature, dew point, wind speed and cloud cover.
(The old surrogate forcing doc is kept in `surrogate/`.)

## Inputs
- `--source nasa_power | cmfd | mswx`, `--lat`, `--lon`, `--start`, `--end`, `--elev`
- Loader: `ki_tools_common.load_forcing.load_daily_forcing` (schema in `input_preparation.md` §2)
- NASA POWER is fetched live (`REALTIME=1`, no cache); CMFD is China-only; MSWX is global.

## Outputs
CSV with a `# source=... wind_height_m=10.0` header line and columns
`date, solar_wm2, air_temp_c, dew_point_c, wind_ms, cloud_frac` — one row per day, no gaps.

## Procedure
```bash
python tools/build_wasp_weather_from_source.py --source nasa_power --lat 41.95 --lon -81.55 \
    --start 2004-01-01 --end 2014-12-31 --elev 174 --out weather_nasa_power.csv
```
Dew point: Magnus inverse (Alduchov & Eskridge 1996) of specific humidity and pressure.
Cloud cover: Kasten & Czeplak (1980) inverse of Rs/Rso with FAO-56 clear-sky Rso; clipped to 0–1.

## Verification
- The tool's `validate_outputs()` refuses gaps, NaN, values outside physical ranges, mean solar
  outside 50–300 W/m² (MJ or J given by mistake), and dew point above air temperature on average.
- Lake Erie 2004–2014 result: solar 151.1 W/m², air 10.23 °C, dew 6.73 °C, wind 5.64 m/s @ 10 m,
  cloud 0.78.

## Traps
- **Cloud cover must be a 0–1 fraction.** Tenths gave 70 °C water; percent hung the engine
  (dt_wasp_029, dt_wasp_033).
- NASA POWER is a 0.5° land/lake grid cell; over a large lake the over-water wind and humidity
  differ from it (assumption recorded in dag.yaml safety).
- Wind is the loader's 10 m wind (`wind_height_m`), not `wind2_ms`.

## Example
`KISSPATH_OUTPUTS/wasp_lake_erie_central_real_engine/weather_nasa_power.csv`
(4,018 days).
