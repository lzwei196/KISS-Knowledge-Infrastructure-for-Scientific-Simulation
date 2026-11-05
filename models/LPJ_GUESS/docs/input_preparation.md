# LPJ-GUESS input preparation plan (real engine 4.1.1)

Written 2026-10-07 from the engine source (`src/modules/cfinput.cpp`, `soilinput.cpp`,
`globalco2file.cpp`, `commonoutput.cpp`), the shipped instruction files
(`src/data/ins/*.ins`) and real runs on this server. The Python LUE stand-in
(`tools/run_lpjguess.py` and its converters) is a SURROGATE and is not covered here.

LPJ-GUESS is mostly an **instruction-file model**: almost every parameter (PFT traits,
soil-water scheme, spin-up length, fire model) already has a working value in the shipped
`global.ins`. Preparing a new case means supplying **climate, CO2, soil code and a
gridlist**, then flipping a few switches. We do not derive PFT parameters.

## 1. Capabilities and the tool that serves each

| # | Capability | Configure | Parse |
|---|---|---|---|
| 1 | [PRIMARY] Point/site C-water fluxes (GPP, Ra, Rh, NEE, NPP, ET) with `-input cf` | `build_lpjguess_cf_forcing.py` + `build_lpjguess_co2_file.py` + `run_lpjguess_engine.py cf` | `parse_lpjguess_engine_output.py` |
| 2 | Official demo / install check (`-input demo`, 13 cells) | `run_lpjguess_engine.py example` | built-in byte comparison + `parse_lpjguess_engine_output.py` (annual tables) |
| 3 | Vegetation composition (PFT selection, PNV vs real stand) | `run_lpjguess_engine.py cf --set 'pft "X" ( include 0 )'` | `annual.csv` columns `cmass_<PFT>`, `lai_<PFT>`, `fpc_<PFT>` (+ `_Total`) |
| 4 | Fire model choice (GLOBFIRM / NOFIRE / BLAZE) | `--firemodel` (BLAZE needs `--simfire_file`) | `annual.csv` columns `cflux_Veg`, `cflux_Repr`, `cflux_Soil`, `cflux_Fire`, `cflux_Est`, `cflux_NEE` |
| 5 | Spin-up length / patches / any `.ins` switch | `--nyear_spinup`, `--npatch`, `--set` | — |
| 6 | Monthly water fluxes (transpiration, evaporation, interception, runoff, PET) | switched on by the cf mode | `monthly_long.csv`, water-balance check |
| 7 | Scoring against FLUXNET2015 | — | `parse_lpjguess_engine_output.py --fluxnet_dir` (one cell; `--cell LON LAT` when the run has several) |
| — | Crop / land-cover / managed forest (`crop.ins`, `landcover.ins`) | NOT wired yet (needs land-use + management files) | — |
| — | N deposition time series | NOT available (Lamarque `.bin` not on server); constant 2 kgN/ha/yr | — |

## 2. Inputs and parameters

| Input | Unit the engine wants | Where it lives | New case | If not available |
|---|---|---|---|---|
| `temp` daily mean air temperature | K, `standard_name=air_temperature` | NetCDF from `build_lpjguess_cf_forcing.py` | build from `load_daily_forcing` | abort (no fill) |
| `prec` precipitation | kg m-2 s-1, `precipitation_flux` | same | mm/day / 86400 | abort |
| `insol` shortwave | W m-2 (24-h mean), `surface_downwelling_shortwave_flux_in_air` | same | loader `srad_wm2` as is | NASA POWER has none before 1984 → start ≥1984 |
| `min_temp`, `max_temp` | K | same | loader tmin/tmax + 273.15 | abort |
| `relhum` | fraction `1` | same | from shum, pres, temp (Bolton es) | abort |
| `wind` | m s-1 | same | loader `wind_ms` (10 m) | abort |
| gridlist | `x y label` **array indices** | `gridlist_cf.txt` | `0 0 <site>` for a point | — |
| CO2 | ppm, `<year> <ppm>` every year | `models/LPJ_GUESS/inputs/co2/co2_1901_2014.txt` | `build_lpjguess_co2_file.py` | extend from NOAA records |
| soil code | LPJ class 0-9 | shipped `soils_lpj.dat` (0.5°) | run tool adds an exact site line | site outside map → abort (exit 2) |
| N deposition | kgN/ha/yr | `file_ndep` (Lamarque bin) | not on server → `""` = 2 kgN/ha/yr | state it in results |
| SIMFIRE input | binary | `file_simfire` | not on server | use GLOBFIRM |
| PFT traits | many | `global.ins` pft blocks | keep shipped values | — |

**Why NASA POWER:** the CF module needs ≥30 full years (spin-up climate = first 30 years).
FLUXNET met (FULLSET/ERAI, 1989-2014) is only 26 years. NASA POWER is global, proxy-safe and
fast (~4 s/year); CMFD is China-only; MSWX is slow and its 1979 file is faulty.

## 3. Shared-library schema (verified 2026-10-07)

`load_daily_forcing('nasa_power', 50.9624, 13.5652, 1984, 1984, on_missing='nan')` returned:

```
dates        datetime64[D] (366,)
precip_mm    float64 (366,)  mean 1.87
temp_mean_c  float64 (366,)  mean 7.16
temp_max_c   float64 (366,)  mean 11.27
temp_min_c   float64 (366,)  mean 3.47
srad_wm2     float64 (366,)  mean 111.0
lrad_wm2     float64 (366,)  ALL NaN (POWER has no longwave) -> why on_missing='nan'
wind_ms      float64 (366,)  mean 4.39  (10 m)
wind2_ms     float64 (366,)  mean 2.92
wind_height_m float64 ()     10.0
shum_kgkg    float64 (366,)  mean 0.0057
pres_pa      float64 (366,)  mean 97910
```
With the default `on_missing='raise'` the 1981 call fails on `srad_wm2` (365/365 missing) and
1984 fails on `lrad_wm2`. `all_metrics(obs, sim)` returns `NSE, KGE, PBIAS, RMSE` (upper case)
and `r`. `validate_water_balance(P, ET, Q, period_days=n)` returns `residual_mm, residual_pct,
status, components, ...`.

## 4. File formats (no Fortran fixed-width files)

All engine inputs are free-form: `.ins` keyword files, whitespace text (gridlist, CO2, soil
codes) and NetCDF. The run tool **copies** the shipped `.ins` files and edits only the
`param "file_*" (str "...")` values of active (non-`!`) lines, then appends override lines
(later lines win). Nothing is generated from a dict.

## 5. What changes for a new site

1. lat/lon/label and a ≥30-year period → `build_lpjguess_cf_forcing.py`.
2. CO2 file must reach the last forcing year → rebuild with `--end_year`.
3. Optional: PFT restriction for managed stands, fire model, spin-up.
Everything else stays as shipped.
