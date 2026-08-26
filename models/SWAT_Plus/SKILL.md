> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)

> **HWSD soil lookup:** Use `from ki_tools_common.soil_utils import lookup_hwsd` to get sand/silt/clay/OC/pH for any lat/lon. Returns texture class and Saxton-Rawls hydraulic properties.

> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (40 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (9 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (61 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (23 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |
| what past runs learned | `.kdt_evolution.jsonl` | append-only memory of previous runs and fixes on this KI. |

*Projected 2026-08-24 from the KI's actual contents — 10 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/calib_run.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help` |
| `tools/s1/build_channel_topology.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1/build_channel_topology.py --help` |
| `tools/s1/define_subbasins.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1/define_subbasins.py --help` |
| `tools/s1/delineate_watershed.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1/delineate_watershed.py --help` |
| `tools/s10/configure_fertilizer.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s10/configure_fertilizer.py --help` |
| `tools/s10/configure_nutrient_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s10/configure_nutrient_output.py --help` |
| `tools/s10/configure_point_sources.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s10/configure_point_sources.py --help` |
| `tools/s10/parse_nutrient_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s10/parse_nutrient_output.py --help` |
| `tools/s10/validate_water_quality.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s10/validate_water_quality.py --help` |
| `tools/s2/apply_hru_threshold.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2/apply_hru_threshold.py --help` |
| `tools/s2/create_hru_overlay.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2/create_hru_overlay.py --help` |
| `tools/s2/generate_hru_from_global.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2/generate_hru_from_global.py --help` |
| `tools/s2/write_channel_geometry.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2/write_channel_geometry.py --help` |
| `tools/s3/generate_weather_stations.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3/generate_weather_stations.py --help` |
| `tools/s3/prepare_weather_files.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3/prepare_weather_files.py --help` |
| `tools/s3/validate_weather_data.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3/validate_weather_data.py --help` |
| `tools/s3/vic_forcing_to_swatplus.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3/vic_forcing_to_swatplus.py --help` |
| `tools/s4/build_soils_database.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4/build_soils_database.py --help` |
| `tools/s4/hwsd_to_swatplus_soil.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4/hwsd_to_swatplus_soil.py --help` |
| `tools/s4/validate_soil_properties.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4/validate_soil_properties.py --help` |
| `tools/s5/build_management_schedules.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5/build_management_schedules.py --help` |
| `tools/s5/configure_landuse.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5/configure_landuse.py --help` |
| `tools/s6/apply_calibration.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6/apply_calibration.py --help` |
| `tools/s6/calibrate_swatplus.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6/calibrate_swatplus.py --help` |
| `tools/s6/generate_calibration_file.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6/generate_calibration_file.py --help` |
| `tools/s6/sensitivity_swatplus.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6/sensitivity_swatplus.py --help` |
| `tools/s7/adapt_swatplus_project.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7/adapt_swatplus_project.py --help` |
| `tools/s7/configure_file_cio.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7/configure_file_cio.py --help` |
| `tools/s7/configure_print_prt.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7/configure_print_prt.py --help` |
| `tools/s7/configure_time_sim.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7/configure_time_sim.py --help` |
| `tools/s7/validate_txtinout.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7/validate_txtinout.py --help` |
| `tools/s8/compile_swatplus.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8/compile_swatplus.py --help` |
| `tools/s8/run_swatplus.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8/run_swatplus.py --help` |
| `tools/s8/run_swatplus_with_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8/run_swatplus_with_params.py --help` |
| `tools/s9/check_mass_balance.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9/check_mass_balance.py --help` |
| `tools/s9/compare_swatplus_vic.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9/compare_swatplus_vic.py --help` |
| `tools/s9/compute_performance_metrics.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9/compute_performance_metrics.py --help` |
| `tools/s9/extract_discharge.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9/extract_discharge.py --help` |
| `tools/s9/parse_basin_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9/parse_basin_output.py --help` |
| `tools/s9/parse_channel_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9/parse_channel_output.py --help` |

*40 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
SWAT+ forcing tools are in `tools/s3/` in this KI:
- `tools/s3/prepare_weather_files.py` — Converts CMFD/MSWX/CSV to SWAT+ weather files (.pcp, .tmp, .slr, .hmd, .wnd) with unit conversions (K→°C, W/m²→MJ/m²/d, specific humidity→RH)
- `tools/s3/vic_forcing_to_swatplus.py` — Converts VIC 3-hourly forcing to SWAT+ daily weather format
- `tools/s3/generate_weather_stations.py` — Creates weather-sta.cli and **weather-wgn.cli**
- `tools/s3/validate_weather_data.py` — QC weather files (Tmax≥Tmin, Tmax≠Tmin, precip≥0, solar 0-40 MJ/m²)

**CMFD forcing store — use the 3-HOURLY one.** `load_daily_forcing('cmfd', ...)` defaults to
`data/forcing/Data_forcing_03hr_010deg`. The *daily* store (`Data_forcing_01dy_010deg`) carries
only a daily MEAN temperature, so it yields **Tmax == Tmin**: Hargreaves PET collapses toward zero
and temperature-index snowmelt loses its melt/freeze cycle, silently. `validate_weather_data.py`
now flags this (>95% of days with Tmax==Tmin). See `dt_043`.

For a basin with several weather stations use
`from ki_tools_common.load_forcing import load_daily_forcing_points`: the 3-hourly NetCDFs are
chunked across the whole lat/lon slab, so a per-station loop re-inflates ~3.4 GB per station-year
(~214 s). Reading each file once for all stations makes a 6-station basin cost what 1 station did.
`prepare_weather_files.py` already does this.

### Soil properties

**Data Sources**: Use `from ki_tools_common.soil_utils import lookup_hwsd` for soil properties.
`tools/s2/generate_hru_from_global.py` builds `soils.sol` from the HWSD raster + MDB directly, so
S4 needs no separate call when you use the from-scratch chain below.

**Data Validation Reference**: CMFD unit documentation and known traps live in
`ki_tools_common.load_forcing` and in `diagnostics/triplets.yaml` (dt_012, dt_043).
The old `data_ki/CMFD/SKILL.md` / `data_ki/HWSD/SKILL.md` references are STALE (KDT 5.0 removed them).

---

## Building a NEW basin from scratch (validated chain)

There is no `quickstart_swatplus.py` in this KI — the Bengbu/Wangjiaba decks under `outputs/` were
built by a script that no longer exists on disk. Use this chain instead. Validated end-to-end at
Zijingguan (紫荆关, Juma River, Haihe, 1767 km², 6 subbasins / 27 HRUs) on 2026-07-09.

```bash
# S1 — clip the national DEM to a bbox around the basin first, then delineate.
#      ALWAYS pass snap_dist explicitly and CHECK the reported area (dt_038).
python tools/s1/delineate_watershed.py dem_clip.tif <lat> <lon> delin/ 25 0.01
#   -> delineated_area_km2 must match the gauge's published drainage area.
#   Find the true outlet cell first: the flow-accumulation cell whose upstream area
#   equals the published area. A coarse "station lat/lon" is usually a few km off, and
#   snap_pour_points only ever moves DOWNSTREAM (toward higher accumulation).

# S1b — REQUIRED for any multi-subbasin basin: build the real channel routing topology.
#       Without channel_topology.json the deck falls back to one-hop "STAR" routing (every
#       subbasin discharging straight to the outlet), which destroys hydrograph timing —
#       this is the documented root cause of an NSE = -1.26 run on 2026-08-19, where the
#       agent only found this tool by listing tools/s1/ after 5 model runs and 4 calibration
#       rounds. Run it here, not after you see a bad NSE.
#      Feed it the RASTER + the grids delineate_watershed.py already wrote — that is
#      the tool's own documented preference and it matters: with only
#      --subbasin_shp + --dem_path it re-breaches the DEM and every reach length
#      falls back to the local-area relation (11/11 on the Rio San Pedro Mezquital).
python tools/s1/build_channel_topology.py \
    --subbasin_raster delin/subbasins.tif --dem_path dem_clip.tif \
    --flow_dir delin/flow_direction.tif --flow_acc delin/flow_accumulation.tif \
    --streams_shp delin/streams.shp \
    --repair_spurious_outlets \
    --output delin/channel_topology.json
#   -> CHECK the printed validation block: single_terminal, acyclic, and
#      outlet_area_matches_basin must ALL be true, and
#      n_length_from_local_area_fallback should be 0.
#   -> ALWAYS pass --repair_spurious_outlets on a DEM-clipped basin. Some subbasin
#      outlet cells drain off the clip edge, the trace then yields >1 terminal
#      channel, and the tool exits 2 ("must have exactly ONE"). If your runner
#      treats that as "topology optional" you land straight back on STAR routing —
#      which is what the flag exists to prevent. Every repair is logged as a
#      WARNING, so read them: a repair on the MAIN stem means the DEM clip is wrong.
#   -> subbasins.shp must already be MASKED to the watershed. wbt.subbasins() runs
#      over the whole DEM; delineate_watershed.py masks it (fixed 2026-08-20). On
#      an unmasked file you get a partition of the DEM box, not of the basin —
#      639 polygons instead of 11 on the Rio San Pedro Mezquital.
#   -> BUILDING IT IS NOT ENOUGH: it is only used if you PASS it to S2 below
#      (--channel_topology). Building it and omitting the flag leaves you with STAR routing
#      and no error message.

# S2 — one call builds a complete runnable TxtInOut (HRUs + soils.sol + all aux files).
#      esco / cn3_swf / perco are STRUCTURAL (hydrology.hyd) and can ONLY be set here.
#      ⚠️ THEIR DEFAULTS (esco 0.15 / cn3_swf 0.0 / perco 0.75) ARE A HUMID-MONSOON
#      PRESET, chosen for the Chinese Huai/Yangtze basins. perco=0.75 sends most
#      percolation to the aquifer, which returns as delayed baseflow. In an ARID or
#      SEMI-ARID basin that is the dominant error: at Rio San Pedro Mezquital
#      (Mexico, P 609 mm/yr, PET 1430 mm/yr) the default deck put ET/P at only 55%
#      and yielded 266 mm/yr (44% runoff coefficient) against a real ~95 mm/yr, i.e.
#      2.7x the observed discharge, with 46% of outlet flow arriving as groundwater
#      return two to three months after the rain. Landscape fluxes (basin_ls) were
#      correctly timed — it is the routed channel hydrograph that lags.
#      For a basin with PET/P > ~2, start from `--perco 0.30` and re-check ET/P
#      against an independent ET product before trusting the water yield.
python tools/s2/generate_hru_from_global.py --basin_shp delin/watershed.shp \
    --dem_path dem_clip.tif --output_dir TxtInOut --basin_name <name> \
    --start_year 2003 --end_year 2023 --n_subbasins 8 \
    --channel_topology delin/channel_topology.json   # from S1b — OMITTING THIS = STAR routing

# S3 — weather. Pass S2's station names (the `wst` column, index 8, of rout_unit.con)
#      or SWAT+ cannot bind objects to weather (dt_040).
NAMES='["sta01","sta02","sta03","sta04","sta05","sta06"]'
python tools/s3/prepare_weather_files.py cmfd $CMFD_3HR "$COORDS" \
    2003-01-01 2023-12-31 weather/ "$NAMES"
#   OUTSIDE CHINA there is no CMFD. Use `nasa_power` — it is an ONLINE point API,
#   so pass a PLACEHOLDER for the forcing-dir argument (it is ignored):
#       python tools/s3/prepare_weather_files.py nasa_power - "$COORDS" \
#           2008-01-01 2021-12-31 weather/ "$NAMES"
#   ~2 s per station-year, all 5 SWAT+ variables, verified in Mexico 2026-08-20.
#   MSWX (`mswx $MSWX_DIR`) is the higher-resolution global option but its annual
#   files are gzip-chunked ONE GLOBAL SLAB PER TIMESTEP: every (variable, year)
#   costs a full ~76 GB decompression (~5 min each, more on a loaded box), i.e.
#   ~6 h for a 12-year 5-variable basin. Prefer NASA POWER unless you specifically
#   need 0.1 deg precipitation. UNSET http_proxy/https_proxy first — POWER stalls
#   through the local proxy.
python tools/s3/validate_weather_data.py weather/          # 0 silent_errors required
cp weather/* TxtInOut/
python tools/s3/generate_weather_stations.py TxtInOut/pcp.cli "$COORDS" "$COORDS" TxtInOut

# S7 — config. configure_print_prt edits print.prt IN PLACE; never regenerate it (dt_041).
python tools/s7/configure_time_sim.py 2003-01-01 2023-12-31 TxtInOut 3

# ⚠️ THE print.prt LINE BELOW CONFIGURES **HYDROLOGY ONLY**. It leaves nutrient/sediment output
# OFF (basin_nb / basin_ls = n n n n). For ANY water-quality question (N, P, sediment, TN, TP),
# you MUST also run the S10 branch below — otherwise the model runs fine and simply produces no
# water-quality output at all, which is exactly how a WQ request silently ends up as a
# discharge-only answer. See §Water Quality Simulation (N/P/Sediment) for the full workflow.
python tools/s7/configure_print_prt.py '{"channel":{"daily":true},"basin_wb":{"yearly":true}}' TxtInOut 3

# S10 — WATER QUALITY BRANCH (run this BEFORE S8 whenever the question involves nutrients/sediment)
# python tools/s10/configure_fertilizer.py --management_sch TxtInOut/management.sch \
#     --crop wheat_maize --region huai_river
# python tools/s10/configure_nutrient_output.py --print_prt TxtInOut/print.prt
# (then after S8: tools/s10/parse_nutrient_output.py, tools/s10/validate_water_quality.py
#  --variable {TN,TP,sediment} — acceptance bands are in docs/validation_convention.yaml)

python tools/s7/validate_txtinout.py TxtInOut   # exits 1 on weather-WIRING fatals (null/single-station/missing refs, dt_053); other fatals warn, exit 0 (--strict fails on all; SWATPLUS_WGN_ONLY=1 opts out a deliberate generated-weather deck)

# S8 / S9
python tools/s8/run_swatplus.py $BIN TxtInOut
python tools/s9/extract_discharge.py --txtinout_dir TxtInOut --output_csv sim.csv
```

**Weather file contract** (verified against the shipped rev59 demo `run_lrew/swatplus_rev59_demo`).
`weather-sta.cli` columns are, in this order, and pcp..wnd hold the FILE name *with extension*:

```
name    wgn         pcp         tmp         slr         hmd         wnd         wnd_dir  atmo_dep
sta01   wgn_sta01   sta01.pcp   sta01.tmp   sta01.slr   sta01.hmd   sta01.wnd   null     null
```

The weather-generator file rev59 reads is **`weather-wgn.cli`** (named in `file.cio`), *not* a
SWAT2012-style `wgn.wgn`. Per station: a header line (`name lat lon elev rain_yrs`), a 14-column
header, then 12 monthly rows. `generate_weather_stations.py` now computes those 14 statistics from
the station's own weather files instead of writing constants.

**The generated topology is a VIC-grid surrogate**: every subbasin channel routes directly into
`cha1`, which routes to nothing. `cha1` is therefore the outlet regardless of the (misleading,
cumulative-looking) `area` column in `channel.con`. `extract_discharge.py` detects this from
`channel.con` topology — do not override with `--outlet_gis_id`.

---

# SWAT+ Knowledge Infrastructure — Agent Entry Point

**Model**: SWAT+ (Soil and Water Assessment Tool Plus)
**Developer**: USDA-ARS / Texas A&M AgriLife Research
**Version**: Rev 60.5+ (Fortran CLI, modular text-based inputs)
**Domain**: Watershed hydrology, water quality (nitrogen, phosphorus, sediment)
**Repository**: https://github.com/swat-model/swatplus
**Documentation**: https://swatplus.gitbook.io/io-docs

---

## What This Infrastructure Enables

Autonomous operation of SWAT+ for watershed-scale simulation of:
- **Hydrology**: Surface runoff (SCS CN method), lateral flow, groundwater recharge/return flow, channel routing, ET, snowmelt
- **Water Quality**: Nitrogen cycle (5 pools: NO3, NH4, active/stable organic N, fresh organic N), phosphorus cycle (6 pools), sediment yield (MUSLE)
- **Land Management**: Crop growth, tillage, fertilizer application, irrigation, pesticide fate

SWAT+ is the successor to SWAT2012 with key architectural differences:
- **No ArcGIS dependency** — all inputs are modular text files in a TxtInOut folder
- **Flexible spatial connectivity** — any object can route to any other object (not forced subbasin hierarchy)
- **file.cio master control** — single file lists all input files by category
- **calibration.cal** — text-based parameter adjustment without editing individual files

---

## Pipeline Overview (10 Stages)

| Stage | Name | Key Tools | Skill Document |
|-------|------|-----------|----------------|
| S1 | Watershed Delineation | `delineate_watershed`, `define_subbasins` | `docs/s1_watershed_delineation_skill.md` |
| S2 | HRU Definition | `create_hru_overlay`, `apply_hru_threshold` | `docs/s2_hru_definition_skill.md` |
| S3 | Weather Data Preparation | `prepare_weather_files`, `generate_weather_stations`, `validate_weather_data` | `docs/s3_weather_preparation_skill.md` |
| S4 | Soil Database | `build_soils_database`, `validate_soil_properties` | `docs/s4_soil_database_skill.md` |
| S5 | Land Use & Management | `build_management_schedules`, `configure_landuse` | `docs/s5_landuse_management_skill.md` |
| S6 | Calibration Parameters | `generate_calibration_file`, `apply_calibration` | `docs/s6_calibration_parameters_skill.md` |
| S7 | Simulation Configuration | `configure_file_cio`, `configure_time_sim`, `configure_print_prt`, `validate_txtinout` | `docs/s7_simulation_config_skill.md` |
| S8 | Model Execution | `compile_swatplus`, `run_swatplus` | `docs/s8_model_execution_skill.md` |
| S9 | Output Parsing & Analysis | `parse_channel_output`, `parse_basin_output`, `compute_performance_metrics`, `check_mass_balance` | `docs/s9_output_parsing_skill.md` |
| S10 | Water Quality (N/P/Sediment) | `configure_nutrient_output`, `configure_fertilizer`, `configure_point_sources`, `parse_nutrient_output`, `validate_water_quality` | (inline below) |

**Dependency graph**: S1 -> S2 -> S5; S1 -> S3; S4 (independent); S2+S4 -> S6; S1-S6 -> S7 -> S8 -> S9; S5+S7 -> S10 -> S8 -> S9

---

## Tools Reference

| Stage | Tool ID | Script Path | Purpose |
|-------|---------|-------------|---------|
| S1 | `delineate_watershed` | `tools/s1/delineate_watershed.py` | DEM processing to subbasins + stream network |
| S1 | `define_subbasins` | `tools/s1/define_subbasins.py` | Generate subbasin connectivity files |
| S1 | `build_channel_topology` | `tools/s1/build_channel_topology.py` | REAL channel routing topology (channel_topology.json). Without it routing degrades to one-hop STAR — see the validated chain S1b |
| S2 | `write_channel_geometry` | `tools/s2/write_channel_geometry.py` | Channel geometry into the deck |
| S4 | `hwsd_to_swatplus_soil` | `tools/s4/hwsd_to_swatplus_soil.py` | HWSD → SWAT+ soils.sol |
| S6 | `calibrate_swatplus` | `tools/s6/calibrate_swatplus.py` | AUTOMATED calibration (pySWATPlus + pymoo; --objective NSE --algorithm GA/DE/NSGA2). Use this instead of hand-editing calibration.cal |
| S6 | `sensitivity_swatplus` | `tools/s6/sensitivity_swatplus.py` | Parameter sensitivity screening |
| S6 | `calib_run` | `tools/calib_run.py` | Calibration driver |
| S7 | `adapt_swatplus_project` | `tools/s7/adapt_swatplus_project.py` | Adapt an existing deck to a new basin/period (REUSE before rebuilding) |
| S8 | `run_swatplus_with_params` | `tools/s8/run_swatplus_with_params.py` | Run with a parameter set (calibration inner loop) |
| S9 | `compare_swatplus_vic` | `tools/s9/compare_swatplus_vic.py` | Cross-model comparison |
| S2 | `create_hru_overlay` | `tools/s2/create_hru_overlay.py` | Overlay landuse/soil/slope to create HRUs |
| S2 | `apply_hru_threshold` | `tools/s2/apply_hru_threshold.py` | Filter small HRUs below area thresholds |
| S3 | `prepare_weather_files` | `tools/s3/prepare_weather_files.py` | Convert forcing data to SWAT+ .pcp/.tmp/.slr/.hmd/.wnd format |
| S3 | `generate_weather_stations` | `tools/s3/generate_weather_stations.py` | Create weather-sta.cli and wgn.wgn |
| S3 | `validate_weather_data` | `tools/s3/validate_weather_data.py` | QC weather files for physical consistency |
| S4 | `build_soils_database` | `tools/s4/build_soils_database.py` | Generate soils.sol from HWSD/SSURGO/SoilGrids |
| S4 | `validate_soil_properties` | `tools/s4/validate_soil_properties.py` | Validate soil physical consistency |
| S5 | `build_management_schedules` | `tools/s5/build_management_schedules.py` | Generate management.sch operation sequences |
| S5 | `configure_landuse` | `tools/s5/configure_landuse.py` | Generate landuse.lum lookup table |
| S6 | `generate_calibration_file` | `tools/s6/generate_calibration_file.py` | Create calibration.cal parameter file |
| S6 | `apply_calibration` | `tools/s6/apply_calibration.py` | Validate calibration parameters |
| S7 | `configure_file_cio` | `tools/s7/configure_file_cio.py` | Generate/update file.cio master control |
| S7 | `configure_time_sim` | `tools/s7/configure_time_sim.py` | Set simulation period and warmup |
| S7 | `configure_print_prt` | `tools/s7/configure_print_prt.py` | Configure output printing options |
| S7 | `validate_txtinout` | `tools/s7/validate_txtinout.py` | Cross-check all file references |
| S8 | `compile_swatplus` | `tools/s8/compile_swatplus.py` | Compile SWAT+ Fortran source with CMake |
| S8 | `run_swatplus` | `tools/s8/run_swatplus.py` | Execute SWAT+ binary |
| S9 | `parse_channel_output` | `tools/s9/parse_channel_output.py` | Parse channel_sd discharge/sediment/nutrients |
| S9 | `parse_basin_output` | `tools/s9/parse_basin_output.py` | Parse basin-level water/nutrient balance |
| S9 | `compute_performance_metrics` | `tools/s9/compute_performance_metrics.py` | Compute NSE, PBIAS, KGE, RMSE |
| S9 | `check_mass_balance` | `tools/s9/check_mass_balance.py` | Verify water/nutrient mass balance closure |
| S10 | `configure_nutrient_output` | `tools/s10/configure_nutrient_output.py` | Enable N/P/sediment output in print.prt |
| S10 | `configure_fertilizer` | `tools/s10/configure_fertilizer.py` | Generate fertilizer schedules for Chinese crops |
| S10 | `configure_point_sources` | `tools/s10/configure_point_sources.py` | Generate recall.rec for point source pollution |
| S10 | `parse_nutrient_output` | `tools/s10/parse_nutrient_output.py` | Parse channel nutrient/sediment output to CSV |
| S10 | `validate_water_quality` | `tools/s10/validate_water_quality.py` | Validate nutrient output vs observations |

---

## 6. Output Description

**Source of truth:** `dag.yaml`. The dag is the model identity for outputs:
every observable output's variable name, unit, description, validation rank and
observability live there. If this section ever disagrees with `dag.yaml`, the dag
wins and this section must be corrected.

**Headline output** (the dag's `validation_rank: 1` variable):

> `streamflow at channel outlet (flo_out)` - Daily channel discharge leaving each routed segment; primary calibration target for hydrology. (`m3/s (after conversion from ha-m/day)`)

The KI judges hydrologic skill first against `streamflow at channel outlet (flo_out)`.
Agents reading only this file should treat that variable as the primary calibration
and validation target.

| Output group from dag | Rank / role | Unit stated here | Description / notes |
|---|---:|---|---|
| `streamflow at channel outlet (flo_out)` | 1 | `m3/s (after conversion from ha-m/day)` | Daily channel discharge leaving each routed segment; primary calibration target for hydrology. |
| `basin water balance components (precip, snofall, snomlt, surq_gen, latq, perc, et, qtile, wateryld, sw_final)` | dag output | See `dag.yaml` | Basin water-balance components. |
| `HRU water balance (hru_wb: per-HRU surq, latq, perc, et, sw)` | dag output | See `dag.yaml` | Per-HRU water-balance outputs. |
| `basin landscape nutrient losses (basin_ls: sedorgn, surqno3, sedmin)` | dag output | See `dag.yaml` | Landscape nutrient losses. |
| `basin nutrient balance (basin_nb: fertn, denit, act_nit_n, plant uptake)` | dag output | See `dag.yaml` | Basin nutrient balance terms. |
| `channel nutrient loads (orgn_out, no3_out, sedp_out, solp_out)` | dag output | See `dag.yaml` | Channel nutrient-load outputs. |
| `sediment yield (HRU sedyld; channel sed_in/sed_out)` | dag output | See `dag.yaml` | HRU and channel sediment yield outputs. |
| `crop yield (basin yield_yr / yield_aa, hru_pw)` | dag output | See `dag.yaml` | Crop-yield outputs. |
| `aquifer state (storage, water-table depth, baseflow flo)` | dag output | See `dag.yaml` | Aquifer state and baseflow outputs. |
| `snow water equivalent (hru%sno_mm; snofall, snomlt fluxes)` | dag output | See `dag.yaml` | Snowpack state and snowfall/snowmelt fluxes. |
| `evapotranspiration (basin et, eplant, esoil, pet)` | dag output | See `dag.yaml` | Evapotranspiration components and potential ET. |

---

## 8. Unit Conversion Table

**Source of truth:** `docs/format_spec.yaml`, `dag.yaml`, and the S3 weather tools.
This table records the unit conversions an agent must preserve when preparing
inputs or parsing outputs. Verify source data attributes before running a new
basin, and use `docs/format_spec.yaml` as the exact I/O contract.

| Variable | Source unit | Model / parsed unit | Conversion | Type |
|---|---|---|---|---|
| CMFD precipitation | `kg/m2/s` | `mm/day` | `x86400` for daily totals; for 3-hourly CMFD, `x10800` per step and sum 8 steps | multiplicative |
| CMFD temperature | `K` | `degC` | `-273.15` | additive |
| CMFD shortwave radiation | `W/m2` | `MJ/m2/day` | `x0.0864` | multiplicative |
| MSWX precipitation | `mm/3hr` | `mm/day` | sum 8 steps; no `x10800` | aggregation |
| MSWX temperature | `degC` | `degC` | none | identity |
| SWAT+ outlet discharge `flo_out` | `ha-m/day` in SWAT+ text output | `m3/s` | after conversion from `ha-m/day` | unit conversion |
| Specific humidity for SWAT+ weather | source forcing humidity variable | relative humidity | converted by `tools/s3/prepare_weather_files.py` | diagnostic-sensitive |

Do not use the daily CMFD store (`Data_forcing_01dy_010deg`) for SWAT+ weather
generation: it only carries daily mean temperature, leading to `Tmax == Tmin`.
Use the 3-hourly CMFD store (`Data_forcing_03hr_010deg`) so Tmin/Tmax are derived
from sub-daily observations.

---

## 11. Validated Results

**Source of truth:** `docs/validation_convention.yaml` for pass/fail bars and
`dag.yaml` for the output being judged. A metric value without the field's cited
bar is not a verdict. The body validation campaign is pending unless a run's
artifact and observation binding are supplied by the user or present in `outputs/`.

### Validation Target

| Property | Value |
|---|---|
| Rank-1 dag variable | `streamflow at channel outlet (flo_out)` |
| Unit | `m3/s (after conversion from ha-m/day)` |
| Description | Daily channel discharge leaving each routed segment; primary calibration target for hydrology. |
| Primary use | Hydrology calibration and validation target |

### Performance Bars - Convention, Cited

| Dag variable | Metric | Direction | Bands from convention |
|---|---|---|---|
| `streamflow at channel outlet (flo_out)` | `nse` | maximize | satisfactory `>= 0.5` (`moriasi2007`, `moriasi2015`); good `>= 0.65` (`moriasi2007`, `moriasi2015`); very_good `>= 0.75` (`moriasi2007`, `moriasi2015`) |
| `streamflow at channel outlet (flo_out)` | `pbias` | zero_centered | very_good `abs(PBIAS) <= 10` (`moriasi2007`, `moriasi2015`); good: no cited threshold; satisfactory `abs(PBIAS) <= 15` (`moriasi2007`, `moriasi2015`) |
| `sediment yield (HRU sedyld; channel sed_in/sed_out)` | `pbias` | zero_centered | very_good `abs(PBIAS) <= 15` (`moriasi2007`, `moriasi2015`); good: no cited threshold; satisfactory `abs(PBIAS) <= 20` (`moriasi2007`, `moriasi2015`) |

`docs/validation_convention.yaml` carries a duplicate identical PBIAS convention
for `streamflow at channel outlet (flo_out)`: metric `pbias`, direction
`zero_centered`, bands `very_good: 10` and `satisfactory: 15`, citations
`moriasi2007` and `moriasi2015`. Treat it as the same convention bar, not a
second independent threshold.

### Current Body-Campaign Status

| Component | Status | Notes |
|---|---|---|
| Rank-1 streamflow validation | pending | Judge against `streamflow at channel outlet (flo_out)` using `nse` and `pbias` bars above. |
| Sediment-yield validation | pending | If validating sediment yield, use the cited `pbias` bands above. |
| Water-quality concentration validation | domain-limited | Bare in-stream concentration series at gate-regulated sluices are not valid targets for this KI when `wq_cha=0`; compare loads or concentration paired with measured discharge. |

---

## Water Quality Simulation (N/P/Sediment)

SWAT+ simulates nutrient cycling (5 N pools, 6 P pools) and sediment yield (MUSLE)
in every HRU. HRU-level nutrient outputs are reliable. Channel-level routing has
limitations in Rev 59.3 (see Known Issues below).

### WQ Workflow

0. ⚠️ **The fertilizer step is a NO-OP unless you also repoint `landuse.lum`.**
   `tools/s2/generate_hru_from_global.py` hard-codes `mgt = no_mgt` for EVERY land
   use (see dt_v004), so a schedule written into `management.sch` is referenced by
   no HRU: the run succeeds, prints `basin_ls`, and quietly reports the
   *unfertilised* N export. Pass `--landuse_lum TxtInOut/landuse.lum` to
   `configure_fertilizer.py` (added 2026-08-20) — it rewrites the `mgt` column of
   the agricultural rows. Then RUN THE BINARY ONCE and check it did not die in
   `mgt_operatn_`; if it did, restore `no_mgt` (dt_v004) and say so in the result.
1. Configure fertilizer: `python tools/s10/configure_fertilizer.py --management_sch TxtInOut/management.sch --crop wheat_maize --region huai_river --landuse_lum TxtInOut/landuse.lum`
   **Outside China** the four `--region` tables (huai_river / north_china /
   northeast / south_china) are wrong in BOTH rate and calendar — a Chinese
   winter-wheat October planting in a summer-rainfall basin fertilises the wrong
   months. Use the data-driven path instead:
   `--crop maize --region global --lat <basin_lat> --lon <basin_lon>`, which reads
   rates from NPKGRIDS (`ki_tools_common.fertilizer`) and planting/harvest dates
   from the GGCMI calendar (`ki_tools_common.crop_calendar`) at that point.
2. Enable output: `python tools/s10/configure_nutrient_output.py --print_prt TxtInOut/print.prt`
3. (Optional) Add point sources: `python tools/s10/configure_point_sources.py --sources_csv sources.csv --output_dir TxtInOut/`
4. Run SWAT+: same binary, same command
5. Parse results (RECOMMENDED — uses HRU-level outputs, avoids QUAL2E issues):
   `python tools/s10/parse_nutrient_output.py --basin_ls TxtInOut/basin_ls_day.txt --basin_area_km2 1500 --output_csv nutrient_ts.csv`
6. Validate: `python tools/s10/validate_water_quality.py --sim_csv nutrient_ts.csv --obs_csv observed_wq.csv`

### CRITICAL: Use HRU-Level Outputs for Nutrient Loads

**Do NOT use channel_day.txt no3_out/orgn_out for nutrient load estimation with Rev 59.3.**
The QUAL2E in-stream routing algorithm has a numerical instability that causes nutrient
concentrations to blow up during extreme flow events (>10x bankfull), producing physically
impossible values (e.g., 10⁹ mg/L NO₃).

Instead, use these RELIABLE output files:
- **basin_ls_day.txt**: landscape (edge-of-field) export — see the species table below
- **basin_nb_yr.txt**: `fertn`, `denit`, `act_nit_n` (kgN/ha/yr) — basin N budget
- **hru_nb_yr.txt**: Per-HRU nutrient cycling (most spatially detailed)
- **channel_day.txt**: `flo_in`, `flo_out` only (flow routing is correct)

**basin_ls_day.txt species and units** — from the SWAT+ source
(`swatplus/src/src/output_landscape_module.f90`, type `output_nutcarb_gain_loss`).
Do NOT read them off the file's unit row: rev59 prints `----` for `usle`, `sedmin`
and `tileno3` instead of their real unit.

| column | species | unit |
|---|---|---|
| `sedyld` | sediment yield | t/ha/day |
| `sedorgn` | organic **N** in sediment | kg N/ha/day |
| `sedorgp` | organic **P** in sediment | kg P/ha/day |
| `surqno3` | NO3-**N** in surface runoff | kg N/ha/day |
| `lat3no3` | NO3-**N** in lateral runoff | kg N/ha/day |
| `surqsolp` | soluble **P** in surface runoff | kg P/ha/day |
| `usle` | USLE erosion | t/ha/day |
| `sedmin` | mineral **P** in sediment | kg **P**/ha/day |
| `tileno3` | NO3-**N** in tile flow | kg N/ha/day |

⚠️ **`sedmin` is PHOSPHORUS, not nitrogen** (corrected 2026-08-20). Until then this
section and `parse_nutrient_output.py` both summed `sedmin` into TN — that adds a P flux
to the N load *and* drops the two real N terms `lat3no3` and `tileno3`. At Wangjiaba the
error was ~+40 % on TN. The correct landscape loads are:

```
TN_load (kg) = basin_area_ha × (sedorgn + surqno3 + lat3no3 + tileno3)   # kg N/ha/day
TP_load (kg) = basin_area_ha × (sedorgp + surqsolp + sedmin)             # kg P/ha/day
sed_load (t) = basin_area_ha × sedyld
```

`parse_nutrient_output.py --basin_ls` now writes `TN_kg`, `TP_kg` and `sed_out`
(absolute basin loads) in addition to the per-hectare columns. It previously wrote only
`TN_kgha`, while `validate_water_quality.py` reads `TN_kg`/`TP_kg`/`sed_out` — so step 5
→ step 6 of the workflow above silently compared *nothing* and reported an empty result
rather than an error. If you see a validation with `n_paired = 0`, check this first.

### Known Issues: Rev 59.3 Channel WQ

| Issue | Symptom | Workaround |
|-------|---------|------------|
| QUAL2E numerical instability | no3_out = 10⁹+ kgN during floods | Use HRU outputs (basin_ls_day) |
| solp produces NaN | Division by zero in P routing | Use HRU outputs (hru_nb_yr) |
| orgn_out always zero | orgn_in too small for QUAL2E | Use sedorgn from basin_ls_day |
| om_water.ini extreme defaults | Initial conc 90 mg/L orgn | Set all to 0 (clean start) |
| New binary (post-2023 source) segfaults | `ch` array not allocated for sd_channel projects | Use Rev 59.3 binary only |

### codes.bsn WQ Flags

| Flag | Position | Description | Recommended |
|------|----------|-------------|-------------|
| rtu_wq | 6 | Routing unit WQ transfer | 0 (off) |
| wq_cha | 10 | Channel QUAL2E processing | 0 (off for Rev 59.3) |

Setting `wq_cha=1` enables QUAL2E but triggers the numerical blowup. Keep it at 0
and use HRU-level nutrient exports instead.

### CRITICAL: Validating WQ against CONCENTRATION observations (guokongzhan / 国控站)

China National Surface-Water Quality auto-monitoring stations (guokongzhan, e.g. station
2258 蚌埠闸上) report **in-stream CONCENTRATION (mg/L)** of specific species (NH3-N, TP,
CODMn, DO), usually with **no co-located discharge**.

Because `wq_cha=0` is mandatory (Rev 59.3 QUAL2E blowup, see above), SWAT+ here produces
only HRU-level edge-of-field nutrient **LOADS (kg)** and has **no in-stream concentration
state** — no baseflow / benthic / point-source / gate-retention floor. Therefore:

1. **Never derive in-stream concentration as `HRU_load / channel_flo_out`.** With no
   in-stream floor it reads ~0 mg/L in dry/winter months while a real gate-regulated
   station holds a ~0.1 mg/L floor, so pattern correlation collapses (station 2258 TP:
   r=0.27, NSE=-7.25, 2026-06-08). This is a DOMAIN limit, **not** a calibration target —
   do not tune parameters to chase it (no state variable exists to fit).

2. **Species must match.** Reliable SWAT+ output is TOTAL-N export (surqno3 + sedorgn),
   NOT a single dissolved species. Comparing it to obs NH3-N gives PBIAS ~ -3000%.
   NH3-N speciation needs in-stream QUAL2E, which is disabled — do not compare them.

**Correct WQ validation target:** compare annual/monthly **LOADS (kg)** with
`validate_water_quality.py` (PBIAS for loads, R for monthly) against obs given as
TN_kg/TP_kg, or concentration **paired with measured discharge** so load = C×Q can be
formed. A bare concentration series at a gate-regulated sluice is NOT a valid target for
this KI. (At station 2258 the load-side TP PBIAS was +37.7%, within Moriasi 2007/2015
±40% "satisfactory" — loads are usable; the derived-concentration comparison is not.)


### om_water.ini (Channel Initial Concentrations)

If `wq_cha` is ever enabled, set ALL nutrient initial concentrations to zero:
```
low_init    0.0   0   0.0   0.0   0.0   0.0   0.0   0.0   0.0   0.0   8.0   0   0   0   0   0   0   15
high_init   0.0   0   0.0   0.0   0.0   0.0   0.0   0.0   0.0   0.0   7.0   0   0   0   0   0   0   20
```
Non-zero initial concentrations cause mass generation from channel storage and
benthic sources, overwhelming HRU inputs.

### Key Water Quality Parameters
| Parameter | File | Range | Sensitivity |
|-----------|------|-------|-------------|
| NPERCO | codes.bsn | 0-1 | N leaching |
| PPERCO | codes.bsn | 10-17.5 | P leaching |
| CDN | codes.bsn | 0-3 | Denitrification |
| SDNCO | codes.bsn | 0-1 | Denitrification threshold |
| USLE_P | hru-data.hru | 0-1 | Erosion practice factor |
| FILTERW | filterstrip.str | 0-100 m | Filter strip width |

### Expected Nutrient Loads (Huai River reference)
| Variable | Range | Source |
|----------|-------|--------|
| TN load | 5-20 kgN/ha/yr | Chinese watershed studies |
| TP load | 0.5-3 kgP/ha/yr | Chinese watershed studies |
| Sediment | 5-50 t/ha/yr | USLE for agricultural land |

### Chinese Fertilizer Application Rates (NPKGRIDS reference)
| Crop | Region | Basal N | Topdress N | P | Total N |
|------|--------|---------|------------|---|---------|
| Winter wheat | Huai River | 150 kgN/ha | 75 kgN/ha | 40 kgP/ha | 225 kgN/ha |
| Summer maize | Huai River | 120 kgN/ha | 60 kgN/ha | 35 kgP/ha | 180 kgN/ha |
| Paddy rice | Huai River | 100 kgN/ha | 90 kgN/ha | 40 kgP/ha | 190 kgN/ha |
| Wheat+Maize | Huai River | (rotation) | (rotation) | 75 kgP/ha | 405 kgN/ha |

---

## Critical Domain Knowledge

### 1. TxtInOut Is the Working Directory
SWAT+ reads file.cio from the current working directory. You MUST `cd` into TxtInOut before running the binary. All paths in file.cio are relative to TxtInOut.

### 2. file.cio Category Order Matters
The file.cio categories must appear in the exact order expected by SWAT+. Do not rearrange lines. Use 'null' for unused optional categories — do not delete the line.

**CMFD unit conversions** (CRITICAL — not documented in default SWAT+ tools):
- Precipitation: kg/m²/s → mm/day (×86400)
- Temperature: K → °C (-273.15), split daily mean into Tmax=T+5, Tmin=T-5 (approximate)
- Solar radiation: W/m² → MJ/m²/day (×0.0864)

### 3. Weather File Format Is Strict
Each .pcp/.tmp/.slr/.hmd/.wnd file has a 3-line header:
- Line 1: Title/comment (free text)
- Line 2: Column headers (variable names)
- Line 3: Station metadata (name, nbyr, tstep, lat, lon, elev)
- Line 4+: Data rows (year, jday, value(s))

Files are space-delimited. Missing data must be -99.0 (not NaN or blank).

### 4. soils.sol Has Multi-Line Records
Unlike most SWAT+ files (one line per record), soils.sol uses 2-10 lines per soil:
- Line 1: Profile-level properties (SNAM, HYDGRP, SOL_ZMX, ANION_EXCL, SOL_CRK, TEXTURE)
- Lines 2-N: Per-layer properties (SOL_Z, SOL_BD, SOL_AWC, SOL_K, SOL_CBN, CLAY, SILT, SAND, ROCK, SOL_ALB, USLE_K, SOL_EC, SOL_CAL, SOL_PH)
The number of layer lines must match the number of soil layers. Mismatch causes silent wrong results.

### 5. Calibration.cal Uses Three Change Types
- `absval`: Set parameter to this exact value (replaces)
- `abschg`: Add this value to current parameter (shift)
- `pctchg`: Change by this percentage (multiply by 1 + value/100)

For spatially variable parameters (CN2, AWC, SOL_K), use `pctchg` to preserve spatial heterogeneity. Using `absval` overwrites all HRUs to the same value.

### 6. Warmup Period Is Essential
SWAT+ needs 2-3 years of warmup for soil moisture, groundwater, and nutrient pool initialization. Set `nyskip` in time.sim. Output during warmup years should be excluded from performance evaluation.

### 7. HRU Threshold Affects Mass Balance
Aggressive HRU thresholds (>20%) remove significant land area. The removed area is redistributed to dominant HRUs, which can bias water yield and nutrient loads. Typical safe thresholds: 5-10% for land use, 5-10% for soil, 10-20% for slope.

### 8. Key Calibration Parameters (Hydrology)

> **WHICH NAMES REV59 ACTUALLY APPLIES (dt_045).** Being listed in `cal_parms.cal` is
> NECESSARY BUT NOT SUFFICIENT — the rev59 binary declares many parameters it never applies
> from `calibration.cal`. Measured at Zijingguan (2026-07-10) by running the real binary once
> per parameter at an extreme value and md5-ing the 18-yr daily outlet series:
>
> - **APPLIED**: `cn2` `esco` `epco` `k` `alpha` `lat_ttime` `flo_min`
> - **SILENT NO-OP** (bit-identical output): `canmx` `surlag` `awc` `delay` `revap_co`
>   `slope_len` `perco` `dep_imp`
>
> Setting soil `LYR1`/`LYR2` does NOT rescue `awc`. A greedy sweep over a no-op name explores
> NOTHING while reporting "calibrated". `tools/s6/generate_calibration_file.py` now knows this
> table: it routes the no-ops to their real home file and DROPS the homeless ones with a loud
> warning. **Before sweeping any knob, confirm it moves the output.**

| Parameter | Range | Controls | Change Type | Route |
|-----------|-------|----------|-------------|-------|
| cn2 | 25-98 | Surface runoff generation | pctchg | calibration.cal |
| esco | 0-1 | Soil evaporation depth | absval | calibration.cal |
| epco | 0-1 | Plant ET compensation | absval | calibration.cal |
| k | pctchg | Soil sat. hydraulic conductivity | pctchg | calibration.cal |
| alpha | 0-1 | Baseflow recession | absval | calibration.cal |
| lat_ttime | 0-180 | Lateral flow travel time (days) | absval | calibration.cal |
| flo_min | 0-5000 | Aquifer storage gating return flow (mm) | absval | calibration.cal |
| awc | -50 to +50% | Soil water holding | pctchg | **soils.sol (structural)** |
| perco | 0-1 | Percolation coefficient | absval | **hydrology.hyd (structural)** |
| canmx | 0-100 | Canopy interception (mm) | absval | **hydrology.hyd (structural)** |
| lat_len | 1-5000 | Lateral flow distance (m) | absval | **topography.hyd (structural)** |
| rchg_dp | 0-1 | Deep-aquifer export (permanent loss) | absval | **aquifer.aqu (structural)** |
| surlag | 0.05-24 | Surface runoff lag | absval | **parameters.bsn `surq_lag` (structural)** |
| msk_co1 / msk_co2 | 0-10 | Muskingum storage-time weights (only the RATIO matters) | absval | **parameters.bsn (structural)** |
| msk_x | 0-0.5 | Muskingum weighting factor | absval | **parameters.bsn (structural)** |
| delay, dep_imp | — | *no-op in rev59, no structural home* | — | DROPPED |

**EVERY basin-object (`bsn`) name is a calibration.cal no-op** — that is what the `surlag` result
was really saying. `msk_co1`/`msk_co2`/`msk_x` are bsn names, so the Muskingum channel routing
was previously uncalibratable. This is not cosmetic: at Zijingguan the shipped default
`msk_co1/msk_co2 = 0.75/0.25` put the 2023-08-01 flood peak (89.2% of the observed variance) a
day LATE, pinning `r_val` at 0.647 and hence `NSE_val` at its r² ceiling of 0.418. Equal weights
land the peak on the observed day: `r_val` 0.823, `NSE_val` 0.417 → 0.669.

**Mass-balance invariants that actually catch a routing bug (dt_046).** `outlet / wateryld` is
NOT a mass-balance test: `basin_wb`'s `wateryld` column is `surq_gen + latq` only and EXCLUDES
aquifer return flow, so that ratio exceeds 1 for ANY basin with an aquifer. Assert instead:
1. area-weighted `aquifer_yr.rchrg` **==** `basin_wb.perc` (if it equals `wateryld`, then
   `rout_unit.con` is sending the surface hydrograph `tot` to the aquifer — see dt_046);
2. `outlet_mm` **==** `basin_wb.wateryld` + area-weighted `aquifer_yr.flo`.

**NSE is bounded above by r².** Before targeting an NSE, compute `r` on the uncalibrated run:
no parameter set can lift NSE above `r²`. If `r_val = 0.56`, then `NSE_val <= 0.31` and a greedy
search on NSE is near-degenerate — select on **KGE** instead and report NSE.
| perco | 0-1 | Percolation coefficient | absval |
| alpha (NOT `alpha_bf`) | 0-1 | Baseflow recession constant | absval |
| delay (NOT `gw_delay`) | 0-500 | Groundwater delay (days) | absval |
| revap_co | 0.02-0.2 | Groundwater revap coefficient | absval |
| flo_min | 0-5000 | Minimum flow to shallow aquifer (mm) | absval |

**Recommended starting calibration for new basins** — DIRECTION-AWARE. First run UNCALIBRATED (or with a neutral cn2 0 preset), read the outlet PBIAS sign, THEN pick the matching preset key in `generate_calibration_file.py`. Applying the OVER-predict recipe (cn2 -50%, esco 0.15) to an UNDER-predicting basin strips storm quickflow and collapses rainfall–runoff correlation (Xixian: r 0.31, NSE -2.36, PBIAS -32%). Do NOT assume the over-predict direction.
- Humid subtropical, OVER-predicting (PBIAS > 0, e.g. Bengbu +253%) -> preset `humid_subtropical_overpredict`: CN2 -50% pctchg, ESCO 0.15, cn3_swf 0.0, perco 0.75
- Humid subtropical, UNDER-predicting (PBIAS < 0, e.g. Xixian -32%) -> preset `humid_subtropical_underpredict`: CN2 +5% pctchg, ESCO 0.85, perco 0.50 (preserves quickflow -> restores r; restricts ET -> raises yield)
- Semi-arid: CN2 -20%, ESCO 0.50, perco 0.30
- Tropical: CN2 -40%, ESCO 0.20, perco 0.60

> **The `perco` / `cn3_swf` terms of these presets are NO-OPS via calibration.cal.** They are not
> in `cal_parms.cal` (they live in `hydrology.hyd`), so SWAT+ reads the line, fails to match, and
> silently ignores it — the `semi_arid` preset really applies only its CN2 and ESCO terms. Set them
> structurally with `tools/s2/generate_hru_from_global.py --perco --cn3_swf --esco`. Likewise the
> rev59 names are **`alpha`** and **`delay`**, not `alpha_bf` / `gw_delay`.
> `generate_calibration_file.py` now aliases the latter and DROPS any unmatched name with a warning
> instead of writing a silent no-op. Always diff a calibrated `channel_day.txt` against the
> uncalibrated baseline to confirm a preset actually did something (`dt_042`).
Without calibration, SWAT+ may OVER- or UNDER-estimate runoff depending on forcing/soil (Bengbu uncalibrated +253% PBIAS; Xixian under-predicts). Always check the PBIAS sign before selecting a preset.

**DEEP-AQUIFER LOSS (`rchg_dp`) — the dominant VOLUME lever when cn2/esco are already maxed.**
When a humid basin STILL over-predicts after the `_overpredict` preset (cn2 -50%, esco 0.15)
because the Rev 59.3 binary floors the effective wet-season CN high (~84) and surface runoff
cannot be cut further, raise `rchg_dp` (fraction of soil percolation diverted to the deep
aquifer and lost from the local stream balance). It removes water UNIFORMLY with **zero timing
lag** — unlike channel-slowing, which attenuates peaks but phase-shifts the hydrograph and
collapses daily r (see channel-routing note below). `rchg_dp` lives ONLY in `aquifer.aqu` and is
absent from `cal_parms.cal`, so a calibration.cal line for it is silently ignored. As of
2026-06-27 `tools/s6/generate_calibration_file.py` accepts `rchg_dp` (and `spec_yld`) and edits
`aquifer.aqu` directly:
```
python tools/s6/generate_calibration_file.py \
  '{"cn2":{"change_type":"absval","value":25},"rchg_dp":{"change_type":"absval","value":0.78}}' TxtInOut/
```
Physically `rchg_dp` lumps un-modeled consumptive losses (irrigation withdrawal, flood
diversion/detention, regional groundwater pumping) — defensible for heavily human-impacted
basins. **Validated WANGJIABA recipe (Huai 30,630 km², over-predicting +34% PBIAS):**
`cn2 absval 25` + `rchg_dp 0.78` closes the full-period water balance (PBIAS +34%→-0.87%) and
lifts held-out **validation NSE -0.83 → +0.20, KGE 0.11 → 0.60** (full NSE -0.94 → -0.49). The
residual ceiling is structural: daily r caps at ~0.59 (single-region CMFD cannot phase the
spring freshet, same as Xixian) and the un-attenuated surface-runoff peaks hold sd_ratio ~1.5.

**CHANNEL ROUTING attenuation (`n`, `s` on the `rte` object) — usually NOT worth it on daily
single-region-forced basins.** Slowing channels (high Manning `n`, low slope `s` in
`hydrology.cha`/`hyd-sed-lte.cha`, both calibratable via the `rte` obj in cal_parms.cal) DOES
attenuate over-predicted flood peaks, but at this grid resolution the multi-day travel time it
needs phase-shifts the daily hydrograph and CRASHES r (Wangjiaba: mann 0.05→0.30 + slope
0.01→0.0005 dropped r 0.60→0.43, net NSE worse). Manning `n` alone (at fixed slope) barely
attenuates because velocity is slope-dominated. Prefer `rchg_dp` for volume and accept the
peak-variance ceiling.

**STRUCTURAL (HRU-generation) hydrology defaults — NOT fixable by calibration.cal.** `perco` and `cn3_swf` live in `hydrology.hyd` (written by `tools/s2/generate_hru_from_global.py`) and are absent from `cal_parms.cal`, so calibration.cal CANNOT change them. The defaults (esco 0.15, cn3_swf 0.0, perco 0.75) are tuned for OVER-predicting humid basins (Bengbu): they route drainage to slow baseflow and suppress wet-season quickflow. On an UNDER-predicting basin (e.g. Xixian, PBIAS -32%, r 0.31) they produce a baseflow-dominated, over-smoothed hydrograph that decorrelates from rainfall (no calibration preset can recover r). For under-predicting humid basins, REGENERATE the HRUs with `python tools/s2/generate_hru_from_global.py ... --esco 0.85 --cn3_swf 0.5 --perco 0.30` to preserve storm quickflow and restore timing BEFORE applying the humid_subtropical_underpredict calibration preset.

---

## Error Handling

Diagnostic triplets are in `diagnostics/triplets.yaml`. Key failure patterns:

- **dt_001**: file.cio references missing file -> fatal, file not found in TxtInOut
- **dt_002**: Weather file format error -> fatal, wrong header line count or missing columns
- **dt_003**: Temperature Tmax < Tmin -> silent error, ET and snowmelt wrong
- **dt_004**: HRU threshold too aggressive -> silent, biased water yield
- **dt_005**: Fortran array bounds exceeded -> fatal, segfault or STOP
- **dt_008**: Wrong watershed delineation (outlet on wrong stream) -> silent, wrong basin area
- **dt_010**: Nutrient mass balance not closed -> silent, wrong water quality results
- **dt_012**: Solar radiation units wrong (MJ/m2 vs W/m2) -> silent, wrong ET

---

## SWAT+ vs VIC Comparison

| Aspect | SWAT+ | VIC |
|--------|-------|-----|
| Spatial unit | HRU (landuse+soil+slope) | Grid cell (lat/lon) |
| Routing | Internal channel routing | External (Lohmann or CaMa-Flood) |
| Water quality | Full N/P/sediment | Hydrology only |
| Calibration | calibration.cal text file | Edit soil parameter file |
| Management | Tillage, fertilizer, irrigation | None |
| Input format | Text files in TxtInOut folder | Text files + global param |
| Typical use | Agricultural water quality | Regional/continental hydrology |

---

## Coupling with HydroCraft

SWAT+ can use the same data sources as VIC:
- **DEM**: Same basin delineation tools (WhiteboxTools)
- **Forcing**: CMFD/MSWX converted to SWAT+ weather files via `prepare_weather_files`
- **Soil**: HWSD global raster shared with VIC soil parameters
- **Observed data**: Same GRDC/HYDAT station data for validation

See `docs/model_couplings.yaml` for detailed coupling specifications.

---

*This knowledge infrastructure was built using the Knowledge Dissection Toolkit v1.0 (Jianyun Zhang Research Group, Hohai University).*
