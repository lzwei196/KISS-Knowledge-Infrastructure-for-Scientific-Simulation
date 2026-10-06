# QUINCY input preparation plan (real engine `qs.bin`)

QUINCY standalone (public release qs-2026.04-public) needs only three files in its run directory:

| file | what | made by |
|---|---|---|
| `qs.namelist` | all switches and site values (Fortran namelist groups) | `run_quincy_engine.py` from `templates/qs.namelist.template` + `site_config.json` + `climate_meta.json` |
| `climate.dat` | meteorology, CO2 and nutrient deposition, one row per time step (or per day) | `build_quincy_climate.py` |
| `lctlib_quincy_nlct14.def` | PFT parameter library (14 land-cover types) | copied from the engine (`src/data/`) unchanged |
| `parameter_slm_run.list` (optional) | proportional parameter changes | `edit_quincy_parameters.py` |

The public release ships no namelist, no run script and no site forcing (they live in the
DKRZ development repository, login required). So the namelist template lists the engine's own
defaults (read from the `mo_*_config_class.f90` sources) and the tools change single values.
The model is mostly "namelist + one forcing file"; there is no soil file, no initial-state file
(the state is built by spin-up) and no grid file.

## 1. Forcing — `climate.dat`

Format from `mo_qs_atmland_forcing.f90` (`read_forcing_header`, `read_or_calculate_forcing`):
2 header lines, then free-format rows. The file is read LINE BY LINE; dates in the rows are
not matched to the model clock.

| column | name | unit in file | engine conversion | new case: where it comes from | if missing |
|---|---|---|---|---|---|
| 1-3 | year, doy, hour | – | none (logged only) | timestamps; doy in the 365-day calendar | – |
| 4 | sw_srf_down | W m-2 (daily route: 24-h mean) | split 50/50 vis/nir | FLUXNET `SW_IN_F`; loader `srad_wm2` | abort |
| 5 | lw_srf_down | W m-2 | daily: scaled by T^4 | FLUXNET `LW_IN_F`; loader `lrad_wm2` | abort (NASA POWER has it) |
| 6 | t_air (timestep) / tmin, tmax (daily) | **K** | none | FLUXNET `TA_F`+273.15; loader `temp_min_c/temp_max_c`+273.15 | abort |
| | q_air | **g kg-1** | /1000 | from `TA_F`, `VPD_F`, `PA_F` (Tetens); loader `shum_kgkg`×1000 | abort |
| | press_srf | **hPa** | ×100 | FLUXNET `PA_F` (kPa)×10; loader `pres_pa`/100 | abort |
| | rain, snow (timestep) / precip (daily) | **mm day-1 rate** | /86400 | FLUXNET `P_F` (mm per step)×86400/dt; loader `precip_mm` | abort |
| | wind_air | m s-1 | none | FLUXNET `WS_F` (tower height); loader `wind_ms` (10 m) | abort |
| | co2_mixing_ratio | ppm | none | FLUXNET `CO2_F_MDS`, gaps from `inputs/co2/` annual record | annual record |
| | co2_dC13, co2_DC14 | permil | ignored (flags off) | written as -8, 0 | – |
| | nhx, noy | mg N m-2 day-1 | → µmol m-2 s-1 | `--ndep_kgN_ha_yr` × 100/365, split by `--nhx_fraction` | **user must give a cited value** (no server dataset) |
| | p_srf_down | mg P m-2 day-1 | → µmol m-2 s-1 | `--pdep_kgP_ha_yr` × 100/365 | user value (state it as an assumption) |

Two routes:
* **timestep** (`--source fluxnet`): half-hourly or hourly tower data; the run tool sets
  `dtime_step_length_sec` to the data step. Snow column = 0 and
  `flag_forcing_with_snow_data = .FALSE.`, so the engine turns rain into snow below 2.5 °C.
* **daily** (`--source nasa_power|cmfd|mswx`): `ki_tools_common.load_daily_forcing`; the engine
  builds the diurnal cycle (`is_daily_forcing = .TRUE.`, `read_precipitation = .TRUE.`).
  CMFD is China only; MSWX and NASA POWER are global; NASA POWER needs network (REALTIME=1).

Shared-library schema, verified by calling it (2026-10-07, NASA POWER, 61.85 N 24.29 E, 2005):
`load_daily_forcing(...)` → dict with keys `dates` (str array), `precip_mm`, `temp_mean_c`,
`temp_max_c`, `temp_min_c`, `srad_wm2`, `lrad_wm2`, `wind_ms` (10 m), `wind2_ms`,
`wind_height_m` (float 10.0), `shum_kgkg`, `pres_pa` — all 1-D float arrays of length n_days.
`lookup_hwsd(lat, lon)` → dict with `sand`, `silt`, `clay` (percent), `bulk_density` (g cm-3),
`ph`, `oc` (percent), `texture`, `mu_id`, sub-soil `sub_*`, `hydraulics{...}`.
`all_metrics(obs, sim, dates=..., label=..., meta=...)` → keys `NSE`, `KGE`, `PBIAS`, `RMSE`, `r`.
`validate_water_balance(P, ET, Q, period_days=n)` → dict.

Rules: drop Feb 29 (365-day calendar); the file must cover whole years; the solar clock is
local solar time (FLUXNET local standard time is used as is).

## 2. Site — namelist values (`build_quincy_site_config.py`)

| value | namelist | unit | new case | if missing |
|---|---|---|---|---|
| latitude, longitude | `&grid_ctl` | deg | user | abort |
| PFT | `&lnd_veg_nml plant_functional_type_id` | 1-14 | engine site lists `fluxnet2_siteset_pft_info.csv` / `cruncep_v7_siteset_pft_info.csv`, else `--pft` | abort |
| sand/silt/clay | `&lnd_spq_nml spq_soil_*` AND `&jsb_sse_nml qs_soil_*` | fraction | HWSD topsoil %/100, or explicit | engine default 0.3/0.4/0.3 (`--soil default`) |
| bulk density | `spq_bulk_density`, `qs_bulk_density` | kg m-3 | HWSD g cm-3 ×1000 | default 1500 |
| soil pH | `&lnd_sb_nml soil_ph` | – | HWSD topsoil pH | default 6.5 |
| soil depth | `spq_soil_depth`, `&jsb_hydro_nml qs_soil_depth` | m | user | default 9.5 |
| elevation | `spq_elevation` | m | site metadata | default 0 |

Soil P pools (`soil_p_labile` etc.) keep the engine defaults (DE-Hainich values per the source
comment); there is no server dataset for them.

## 3. Run control (`run_quincy_engine.py`)

`quincy_model_name` (land/plant/canopy/test_canopy/test_radiation), transient spin-up
(`forcing_mode='transient'`, `transient_spinup_years` default 500, cycling the first
`--spinup_cycle_years` of the file), simulation length = forcing years, output interval
(`daily` default; monthly = 30-day blocks, not calendar months), output file set (`basic`).
Nutrient switches `include_nitrogen`/`include_phosphorus` stay at the engine default (on).
Other capabilities are plain namelist switches passed with `--nml group.key=value`, e.g.
`lnd_q_syl_nml.flag_stand_harvest=.TRUE.` + `stand_replacing_year`, `lnd_dist_fire_nml.flag_dfire`,
`lnd_q_assimi_nml.flag_optimal_Nfraction`. File-based land use and fertiliser (`bc_*.nc`) are not
available in this build.

## 4. Parameters (`edit_quincy_parameters.py`)

Proportional multipliers in `parameter_slm_run.list` (groups `lnd_q_assimi_nml`, `lnd_q_pheno_nml`,
`jsb_rad_nml`, `qs_shared_nml`, `lnd_spq_nml`, `lnd_veg_nml`, `lnd_sb_nml`, `lctlib_pft1..8_nml`).
Names are validated against the engine source. The engine echoes old/new values to
`parameter_sensi_param_values.txt`.

## 5. Observations (`score_quincy_vs_fluxnet.py`)

FLUXNET2015 `FULLSET_DD.csv`: `GPP_NT_VUT_REF`, `RECO_NT_VUT_REF`, `NEE_VUT_REF` in **g C m-2 day-1**,
`LE_F_MDS`, `H_F_MDS` in W m-2, daily QC = fraction of good half hours.
