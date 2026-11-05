# s1 — Forcing: build `climate.dat`

## Purpose
Write the engine's only time-varying input: meteorology, CO2 and N/P deposition, in the exact
column order and FILE units the Fortran reader expects.

## Inputs
- `--source fluxnet --site <ID>`: FLUXNET2015 `FULLSET_HH.csv` (or `_HR`), gap-filled `_F` columns.
- `--source nasa_power|cmfd|mswx --lat --lon`: `ki_tools_common.load_daily_forcing`.
- `--ndep_kgN_ha_yr`, `--pdep_kgP_ha_yr` (required; cite the value), `--nhx_fraction` (default 0.5).
- CO2: `KISSPATH_KI_ROOT/QUINCY/inputs/co2/` (Law Dome + Mauna Loa annual).

## Outputs
`<out_dir>/climate.dat`, `<out_dir>/climate_meta.json` (route, dtime, years, row count, deposition,
summary means). The run tool reads the meta file to set `is_daily_forcing`, `read_precipitation`
and `dtime_step_length_sec`.

## Procedure
```
$PY tools/build_quincy_climate.py --source fluxnet --site FI-Hyy --start_year 1996 --end_year 2014 \
    --ndep_kgN_ha_yr 7.4 --pdep_kgP_ha_yr 0.05 --out_dir case/climate
$PY tools/build_quincy_climate.py --source nasa_power --lat 61.8474 --lon 24.2948 \
    --start_year 2004 --end_year 2005 --ndep_kgN_ha_yr 7.4 --pdep_kgP_ha_yr 0.05 --out_dir case/climate_np
```
Units and columns: see `docs/input_preparation.md` §1 and the tool docstring.

## Verification
`validate_outputs()` refuses the file (exit 3) when mean T is outside 230-315 K, SW 40-350 W m-2,
LW 150-450, q 0.3-30 g kg-1, p 500-1100 hPa, P 0.05-15 mm day-1, wind 0.1-20 m s-1, CO2 270-450 ppm.
FI-Hyy 1996-2014: 332 880 rows, mean T 4.37 °C, P 604 mm yr-1, SW 99 W m-2, CO2 383 ppm.

## Traps
- t_air must be K, q_air g kg-1, pressure hPa (dt_quincy_029).
- Precipitation is a mm/day RATE on every row, also half-hourly (dt_quincy_030).
- Feb 29 must be dropped; whole years only (dt_quincy_027, dt_quincy_028).
- Daily vs timestep columns differ (tmin/tmax/precip vs t_air/rain/snow); the flags must match the
  file (dt_quincy_040). Daily SW must be the 24-h mean.
- FLUXNET HH timestamps are local standard time; the engine clock is local SOLAR time — up to
  ~1 h phase offset at sites far from their time-zone meridian.

## Example
`outputs/quincy_fihyy_real_engine/climate/` (FI-Hyy, tower met, 1996-2014).
