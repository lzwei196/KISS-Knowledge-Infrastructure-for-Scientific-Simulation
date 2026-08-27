# s2 Met Forcing

## Purpose

Convert meteorological forcing to the GLM CSV columns required by the `&meteorology` namelist block: `time,ShortWave,LongWave,AirTemp,RelHum,WindSpeed,Rain,Snow`.

## Inputs

- Lake `lat`, `lon`, `start_date`, and `end_date` from s0/s1.
- One forcing source:
  - `--forcing_source nasa_power` through `ki_tools_common.load_forcing`.
  - `--forcing_dir` for CMFD/MSWX-like local data.
  - `--vic_forcing_dir` for VIC ASCII forcing.
- Tool: `tools/s2_met_forcing/convert_met_to_glm.py`.
- Unit references in `docs/format_spec.yaml`.

## Outputs

- GLM meteorology CSV, usually `bcs/met.csv` or `bcs/met_hourly.csv`.
- Stderr JSON summary with `columns`, `num_records`, date range, unit summary, and validation warnings.

## Procedure

1. Prefer NASA POWER when no vetted local CMFD/MSWX/VIC forcing exists:

```bash
python tools/s2_met_forcing/convert_met_to_glm.py \
  --forcing_source nasa_power \
  --lat 34.1932 --lon -86.8052 \
  --start_date 2014-01-01 --end_date 2020-12-31 \
  --output bcs/met.csv
```

2. Use VIC forcing when this GLM run is coupled to a VIC workflow:

```bash
python tools/s2_met_forcing/convert_met_to_glm.py \
  --vic_forcing_dir outputs/run/vic_temp/forcing/forcing_final \
  --lat 46.0 --lon -89.7 \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --output bcs/met_hourly.csv
```

3. Use a local CMFD/MSWX-style forcing directory only when it is known to cover the lake:

```bash
python tools/s2_met_forcing/convert_met_to_glm.py \
  --forcing_dir /path/to/cmfd_or_mswx \
  --lat 40.48 --lon 116.97 \
  --start_date 2001-01-01 --end_date 2010-12-31 \
  --output bcs/met.csv
```

## Verification

- The CSV contains exactly the GLM meteorology columns listed above.
- `RelHum` values are percentages, usually between 0 and 100, not fractions.
- `Rain` and `Snow` are in `m/day`; most daily values should be far below `0.5`.
- `ShortWave` minimum is `>= 0`.
- Longwave handling in s6 will match the forcing: `--lw_type LW_IN` when `LongWave` is supplied as incoming longwave.

## Traps

- `dt_001`: GLM rain is `m/day`, not `mm/day`; a 1000x error floods the lake silently.
- `dt_002`: `RelHum` is percent, not fraction; `0.7` is read as `0.7%`.
- `dt_003`: negative shortwave after interpolation can produce NaNs.
- `dt_020`: `lw_type` inconsistent with the `LongWave` column can create a 3-5 degC warm bias.
- `dt_024`: older CMFD/VIC conversions may produce all-zero precipitation; check annual rain/snow sums.
- `dt_026`: 3-hourly CMFD with `subdaily=.true.` produced flat temperatures; use daily forcing with `subdaily=.false.` unless forcing is hourly.

## Example

```bash
python tools/s2_met_forcing/convert_met_to_glm.py \
  --forcing_source nasa_power \
  --lat 46.0 --lon -89.7 \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --wind_height 10 --snow_threshold 0 \
  --output bcs/met.csv
```
