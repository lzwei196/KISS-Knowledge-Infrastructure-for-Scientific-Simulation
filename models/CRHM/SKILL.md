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
| to run the pipeline stages | `tools/` (16 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (38 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (17 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |
| what past runs learned | `.kdt_evolution.jsonl` | append-only memory of previous runs and fixes on this KI. |

*Projected 2026-10-18 from the KI's actual contents — 10 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/calib_run.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help` |
| `tools/s1_basin_setup/create_hru_config.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_basin_setup/create_hru_config.py --help` |
| `tools/s2_observation_data/build_obs.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_observation_data/build_obs.py --help` |
| `tools/s2_observation_data/netcdf_safe.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_observation_data/netcdf_safe.py --help` |
| `tools/s2_observation_data/screen_swe_obs.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_observation_data/screen_swe_obs.py --help` |
| `tools/s2_observation_data/validate_obs_file.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_observation_data/validate_obs_file.py --help` |
| `tools/s3_module_selection/select_modules.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_module_selection/select_modules.py --help` |
| `tools/s4_parameter_config/create_prj_file.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_parameter_config/create_prj_file.py --help` |
| `tools/s4_parameter_config/derive_parameters.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_parameter_config/derive_parameters.py --help` |
| `tools/s4_parameter_config/migrate_project_clock.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_parameter_config/migrate_project_clock.py --help` |
| `tools/s4_parameter_config/validate_prj.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_parameter_config/validate_prj.py --help` |
| `tools/s5_execution/check_water_balance.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_execution/check_water_balance.py --help` |
| `tools/s5_execution/parse_crhm_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_execution/parse_crhm_output.py --help` |
| `tools/s5_execution/plot_crhm_results.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_execution/plot_crhm_results.py --help` |
| `tools/s5_execution/run_crhm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_execution/run_crhm.py --help` |
| `tools/s6_vic_coupling/merge_crhm_vic.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_vic_coupling/merge_crhm_vic.py --help` |

*16 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

## Data Preparation

### Forcing data

**Build the weather input straight from the forcing source with `build_obs.py`, the only weather tool of this KI.**
CRHM forcing tools are in `tools/s2_observation_data/` in this KI:
- `tools/s2_observation_data/build_obs.py` — THE tool. `--source cmfd|mswx|nasa_power` (no default) read through the shared loader `ki_tools_common.load_forcing.load_hourly_forcing`; `--lat --lon` for one point or `--basin_shp` for the mean over every grid cell in the basin (cmfd); `--source table` for a dataset that has no reader yet (you write a standard table, see `docs/s2_observation_data_skill.md` Step 2c). Converts specific humidity→RH, refuses missing values and wrong units instead of filling them, and writes `<obs>.meta.json` with the yearly precipitation and `forcing_elev_m` (pass that to `derive_parameters.py --forcing_elev_m`).
- `tools/s2_observation_data/validate_obs_file.py` — Validates CRHM .obs format (header, variables, bounds, date continuity)

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.


# CRHM (Cold Regions Hydrological Model) -- Knowledge Infrastructure

**Package**: hydrocraft-crhm v1.0.0
**Model**: CRHM 1.3 (crhmcode, University of Saskatchewan)
**Domain**: Cold regions hydrology -- blowing snow, sublimation, frozen soil infiltration, energy-balance snowmelt
**Coupling target**: VIC 5.1.0 (cold regions process enhancement)

---

## What is CRHM?

CRHM is a modular, physically-based hydrological model designed for cold regions. Unlike grid-based models (VIC, WRF-Hydro), CRHM uses **Hydrological Response Units (HRUs)** -- irregular landscape units grouped by elevation, land cover, slope, and aspect. Its key strength is a library of cold-regions-specific modules:

- **PBSM** (Prairie Blowing Snow Model): Wind transport, sublimation, redistribution of snow
- **CRHMCanopy**: Forest canopy interception, sublimation (30-40% of snowfall in boreal forests)
- **SnobalCRHM**: Full energy-balance snowmelt with wind and radiation effects
- **PrairieInfil**: Frozen soil infiltration using Gray's equation (prairie clay soils)
- **Slope_Qsi**: Solar radiation correction for slope and aspect (critical in mountains)

Modules form a **chain**: output of one feeds input to the next via `declvar()`/`declgetvar()`. The chain order determines the physics.

## Output Description

**Source of truth:** `dag.yaml`. The dag is the model identity for observable
outputs; if this section and `dag.yaml` ever disagree, `dag.yaml` wins.

**Headline output** (`validation_rank: 1`):

> `basinflow_s` -- Watershed outlet discharge at simulation timestep (m^3/s); aggregates surface, sub-surface and groundwater contributions through Netroute. (`m^3/s`)

Other dag outputs: `['SWE', 'basinflow', 'hru_actet', 'Subl', 'soil_moist', 'snowmeltD', 'infil_act']`.

| Output variable (dag `var`) | Rank | Emitted in | Unit | Description |
|-----------------------------|------|------------|------|-------------|
| `basinflow_s` | 1 | Display_Variable output file from Netroute module | `m^3/s` | Watershed outlet discharge at simulation timestep (m^3/s); aggregates surface, sub-surface and groundwater contributions through Netroute. |
| `basinflow` | 2 | Display_Variable output file from Netroute module | `m^3/int` | Watershed outlet discharge per simulation interval; divide by 86400 for daily-timestep m^3/s; includes basingw. |
| `hru_actet` | 3 | Display_Variable output file from evap module | `mm/int` | Actual evapotranspiration from the HRU soil-column and land/water surface water balance per timestep (Granger / Priestley-Taylor / Penman-Monteith / Shuttleworth-Wallace depending on evap_type). |
| `SWE` | 4 | Display_Variable output file (Output.txt / .csv) when listed in .prj Display_Variable section | `mm` | Snow water equivalent per HRU; primary cold-region state variable, should peak late winter/early spring and reach zero in summer for non-glaciated basins. |
| `Subl` | 5 | Display_Variable output file from PBSM / CRHMCanopy modules | `mm/int` | Blowing-snow and canopy sublimation per timestep; PBSM contributes 15-40% of snowfall in prairie, CRHMCanopy 30-50% in boreal forest. |
| `soil_moist` | 6 | Display_Variable output file from Soil module | `mm` | Total soil moisture storage state per HRU (declstatvar). |
| `snowmeltD` | 7 | Display_Variable output file from ebsm / SnobalCRHM | `mm/d` | Daily snowmelt depth from ebsm or SnobalCRHM energy-balance solver. |
| `infil_act` | 8 | Display_Variable output file from Soil / infiltration module | `mm/int` | Actual infiltration into soil (GreenAmpt, PrairieInfil, or crack); partitioned from melt and net rain. |

## Installation

CRHM is built from C++ source with CMake and GCC:

```bash
bash KISSPATH_KI_ROOT/CRHM/knowledge_infrastructure/install_crhm.sh
```

**Requirements**: cmake, g++ (C++14), git, Boost 1.75.0 (auto-downloaded by install script).

**Executable**: `KISSPATH_BINARIES/crhmcode/crhmcode/build/crhm`

**CLI**:
```bash
crhm [-t ISO|YYYYMMDD] [-f STD|OBS] [-o output.txt] [-p 100] [--obs_file_directory dir] project.prj
```

## Pipeline Stages

| Stage | Name | Skill Document | Key Tools |
|-------|------|----------------|-----------|
| s1 | HRU Basin Setup | `docs/s1_basin_setup_skill.md` | `create_hru_config.py` |
| s2 | Observation Data | `docs/s2_observation_data_skill.md` | `build_obs.py`, `validate_obs_file.py` |
| s3 | Module Selection | `docs/s3_module_selection_skill.md` | `select_modules.py` |
| s4 | Parameter Config | `docs/s4_parameter_config_skill.md` | `create_prj_file.py`, `validate_prj.py` |
| s5 | Execution | `docs/s5_execution_skill.md` | `run_crhm.py`, `parse_crhm_output.py`, `plot_crhm_results.py` |
| s6 | VIC Coupling (combine / compare RESULTS of the two models) | `docs/s6_vic_coupling_skill.md` | `merge_crhm_vic.py` |

**Dependencies**: s1 and s2 can run in parallel. s3 depends on s1. s4 depends on s1+s3. s5 depends on s2+s4. s6 depends on s5.

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| create_hru_config | s1 | `tools/s1_basin_setup/create_hru_config.py` | Generate HRU definitions from DEM + land cover; `--single_hru --lat --lon --elevation_m --area_km2 --land_cover` for one user-described site with no rasters |
| **build_obs** | **s2** | `tools/s2_observation_data/build_obs.py` | Build the .obs straight from the forcing source (cmfd / mswx / nasa_power / a standard table); one point or a basin mean |
| validate_obs_file | s2 | `tools/s2_observation_data/validate_obs_file.py` | Check .obs format, units, gaps |
| select_modules | s3 | `tools/s3_module_selection/select_modules.py` | Configure module chain by landscape type (auto-detect from HRU config) |
| **derive_parameters** | **s4** | `tools/s4_parameter_config/derive_parameters.py` | **NEW** — Derive all module params from HWSD + DEM + Fang et al. (2013) |
| create_prj_file | s4 | `tools/s4_parameter_config/create_prj_file.py` | Generate .prj project file (accepts `--derived_params`) |
| validate_prj | s4 | `tools/s4_parameter_config/validate_prj.py` | Validate .prj structure and parameter ranges |
| run_crhm | s5 | `tools/s5_execution/run_crhm.py` | Execute CRHM with progress reporting |
| parse_crhm_output | s5 | `tools/s5_execution/parse_crhm_output.py` | Parse CRHM output to CSV/NetCDF |
| plot_crhm_results | s5 | `tools/s5_execution/plot_crhm_results.py` | Generate diagnostic plots (SWE, discharge, etc.) |
| merge_crhm_vic | s6 | `tools/s6_vic_coupling/merge_crhm_vic.py` | Combine CRHM + VIC results for comparison |

### Parameter Derivation Pipeline (NEW, 2026-04-11)

The S4 stage now has a two-step parameter derivation pipeline based on Fang et al. (2013):

```bash
# Step 1: Derive physically-based parameters from global datasets
python tools/s4_parameter_config/derive_parameters.py \
  --hru_config outputs/<run>/crhm/hru/hru_config.json \
  --output outputs/<run>/crhm/derived_params.json

# Step 2: Create .prj with derived parameters (overrides hardcoded defaults)
python tools/s4_parameter_config/create_prj_file.py \
  --hru_config outputs/<run>/crhm/hru/hru_config.json \
  --module_chain outputs/<run>/crhm/modules.json \
  --obs_path outputs/<run>/crhm/basin.obs \
  --start_date "2005 1 1" --end_date "2015 12 31" \
  --output_path outputs/<run>/crhm/basin.prj \
  --derived_params outputs/<run>/crhm/derived_params.json
```

`derive_parameters.py` STOPS (exit 1, nothing written) when a real input is
missing and a built-in value would be used instead: no basin coordinates
(it used to fall back to 50 N, −115 E) or no HWSD map unit at the site (it used
to return loam: soil_type 4, soil_moist_max 451, gw_max 400). Pass
`--allow_defaults` to accept them; the output JSON then lists them under
`defaults_used`. `create_prj_file.py` dates are ONE quoted argument,
`--start_date "2005 1 1"` (`2005-01-01` is also accepted). `run_crhm.py
--obs_dir` is only for a `.prj` whose obs path is relative to that directory;
CRHM joins the two strings as they are.

`derive_parameters.py` derives parameters for ALL 15 mountain modules:

| Module | Parameters | Data Source | Reference |
|--------|-----------|-------------|-----------|
| **obs** | obs_elev, lapse_rate=0.75, precip_elev_adj, catchadjust, snow_rain | Min HRU elev, Fang 2013 §3.1 | Fang et al. (2013) |
| **Soil** | soil_moist_max, soil_rechr_max, gw_max, Sdmax, gw_init | HWSD soil × CRHM porosity table × depth (from Fang §3.2.7) | GlobalDll.h SetSoilproperties |
| **GreenAmpt** | soil_type (0-12 USDA) | HWSD texture class | ClassGreenAmpt.cpp soilproperties |
| **evap** | evap_type (0=Granger land, 1=P-T water) | Land cover | Fang §12 |
| **walmsley_wind** | A, B, L, Walmsley_Ht | Terrain slope + DEM | Walmsley et al. (1989) |
| **pbsm** | fetch, distrib | Land cover + elevation | Fang §3.2.3 (300m min for mountains) |
| **crack** | fallstat, Major | Land cover (autumn SM proxy) | Fang §3.2.5 |
| **Netroute** | order, whereto, runK/ssrK/gwKstorage | Elevation sorting + sqrt(area) | Fang §14 |

### Auto Basin Type Detection (NEW, 2026-04-11)

`select_modules.py` now auto-detects basin type from HRU config:

```bash
# Auto-detect (no --basin_type needed):
python tools/s3_module_selection/select_modules.py \
  --hru_config outputs/<run>/crhm/hru/hru_config.json \
  --output_path outputs/<run>/crhm/modules.json
```

Classification logic (Pomeroy et al. 2007):
- **Mountain**: elevation relief > 500m
- **Prairie**: relief < 300m, grassland/cropland > 50%
- **Forest**: forest fraction > 60%
- **Arctic**: latitude > 60°N
- **Mixed**: forest + open mix

### Critical .prj Format Rules (Bugs fixed 2026-04-11)

1. **Flat module format ONLY** — `basin CRHM 02/24/12`, NOT `Basin_Group Macro` (dt_019). CLI binary crashes with Macro format.
2. **NO blank lines in Modules section** — CRHM parses blank lines as empty module names.
3. **Exactly 1 description line in .obs** — line 2 must be a variable declaration, not text (dt_020).
4. **Display_Variable needs module prefix** — `Netroute basinflow 1`, not just `basinflow 1`.

## .prj File Format

CRHM project files use section delimiters (`######`):

```
######
Dimensions:
######
nhru 5
nlay 1
nobs 1

######
Observations:
######
/absolute/path/to/basin.obs

######
Dates:
######
2000 1 1
2010 12 31

######
Modules:
######
Basin_Group Macro 04/20/06
 +basin CRHM 04/20/06
 +global CRHM 04/20/06
 +obs CRHM 04/20/06
 +PBSM CRHM 04/20/06
 +PrairieInfil CRHM 04/20/06
 +Soil CRHM 04/20/06
 +Netroute CRHM 04/20/06

######
Parameters:
######
PBSM fetch <10 to 10000>
1500.0 1500.0 200.0 50.0 30.0
```

**Shared vs module-local parameters (FATAL trap, dt_023).** CRHM resolves a
module's parameter as `<Module> <param>` first, then `Shared <param>`. Basin
geometry — `basin_area`, `hru_area`, `hru_elev`, `hru_lat`, `hru_GSL`,
`hru_ASL` — is read independently by MANY modules (Netroute, obs, pbsm, …), so
it MUST be declared with the `Shared` prefix, exactly as the shipped
`crhmcode/prj/badlake.prj` (in the CRHM SOURCE tree, not in this KI) and every validated basin .prj do. Writing `basin hru_area`
instead leaves Netroute on its default `hru_area = [1] km²` → basinflow comes
out basin-area-fold too small (NSE pinned at −1.0, PBIAS ≈ −100%), and `obs`
never sees `hru_elev` → no lapse-rate elevation banding (all HRUs identical).
`create_prj_file.py` emits these as `Shared` since 2026-07-23; sanity-check any
.prj with `grep 'Shared hru_area'`.

## .obs File Format

This is the form `build_obs.py` writes, and the only one this KI uses:

```
CRHM forcing from cmfd at (29.59, 89.13) 1970-2013     <- exactly ONE description line (dt_020)
t 1 (C)
p 1 (mm)                                               <- precipitation IN THE STEP (ClassObs.cpp:85)
rh 1 (%)
u 1 (m/s)
Qsi 1 (W/m^2)
Qli 1 (W/m^2)
############################################           <- must be there (dt_v001)
1970 1 1 0 0 -17.20 0.000 24.2 1.07 0.00 160.00
```

There is NO air-pressure variable in a CRHM `.obs`: a line `p 1 (kPa)` is read as
precipitation. `ppt (mm/d)` is the DAILY precipitation variable and is only for a
daily-step file; sub-daily amounts go in `p`, unchanged.

## Module Chain Concept

Pre-built chains by landscape type:

| Landscape | Chain | Key Feature |
|-----------|-------|-------------|
| `--basin_type` | Chain | Status |
|-----------|-------|-------------|
| **mountain_reduced** | basin > global > obs > calcsun > intcp > pbsm > albedo > ebsm > netall > crack > evap > Soil > Netroute | VALIDATED |
| **mountain** | the same + Slope_Qsi + walmsley_wind | runs; needs per-HRU slope/aspect and Walmsley terms |
| **prairie_reduced** | basin > global > obs > calcsun > intcp > **pbsmSnobal** > albedo > **SnobalCRHM** > netall > crack > evap > Soil > Netroute | RUNS, NOT a validated pass. Auto-selected for flat, open sites |
| **prairie_ebsm_legacy** | basin > global > obs > calcsun > intcp > pbsm > albedo > ebsm > netall > crack > evap > Soil > Netroute | runs; no mid-winter sublimation sink |
| prairie, forest, mixed, arctic | — | REFUSED by `select_modules.py`: no melt module (prairie) or module names the CLI binary does not register (`CRHMCanopy`, `CRHMCanopyClearing`, `PBSM`, `PrairieInfil`, `REWroute`); they never ran with this binary |

**SnobalCRHM must be paired with `pbsmSnobal`, never plain `pbsm` (dt_v012).**
SnobalCRHM reads `hru_drift`/`hru_subl`, which only `pbsmSnobal` declares; with
`pbsm` the binary segfaults at "0% complete." (exit −11, two-row output, no
message). Parameter lines and overrides on that chain are keyed
`pbsmSnobal fetch / Ht / distrib`; output variables are `pbsmSnobal hru_subl`,
`hru_drift`, `Drift_out`, `cumSubl` and `SnobalCRHM SWE`, `E_s_int`.

## Critical Domain Knowledge

### The #1 Silent Error: Humidity Unit Conversion

The forcing sources give **specific humidity** (kg/kg, values ~0.001-0.02). CRHM expects **relative humidity** (%, values 0-100). If you pass specific humidity directly, CRHM interprets the atmosphere as 0.001-0.02% RH (bone dry). All sublimation goes to zero. SWE accumulates forever. **The model runs to completion with no error.** Always use `build_obs.py` which applies the Tetens formula conversion.

**Detection**: If max(RH) in .obs file < 1.0, the units are wrong.

### Parameter Clamping (Silent)

CRHM clamps parameters to their declared `<min to max>` range WITHOUT warning. You set `fetch=50000` but the model uses `max=10000`. Always run `validate_prj.py` before running CRHM.

### VIC Coupling: Process Ownership

Both VIC and CRHM compute snowmelt, ET, and soil moisture. **Define a process ownership table** before merging outputs. Each process is assigned to exactly one model. Double-counting produces water balance errors >100%.

### Cold Regions Observation Data Quality

Winter weather stations in cold regions (-40C, blizzards, rime icing) frequently fail. Gap-filled data with constant values misrepresents extreme cold events that control frozen soil state. Prefer reanalysis (ERA5, CMFD, MSWX) over gap-filled station data for cold regions.

### Blowing Snow is Landscape-Specific

PBSM is only valid for wind-exposed terrain (prairie, tundra, alpine above treeline). Using it in dense forest produces unrealistic transport. CRHMCanopy handles snow processes in forested landscapes.

## Unit Conversion Table

From the standard forcing series (what `ki_tools_common.load_forcing` returns) to the `.obs`.
`build_obs.py` does all of it; this table is for checking, not for doing by hand.

| Variable | Standard series | CRHM `.obs` | Conversion | Silent if Wrong? |
|----------|-----------------|-------------|------------|------------------|
| Temperature | `temp_c`, C | `t` (C) | None | No |
| Humidity | `shum_kgkg`, kg/kg (specific) | `rh` (%) | `e = q p / (0.622 + 0.378 q)`, `RH = e / es(T) * 100` | **YES** (dt_001) |
| Precipitation | `precip_mm`, mm in the step | `p` (mm in the step) | **None.** Do NOT turn it into mm/d | **YES** (dt_002) |
| Wind | `wind_ms`, m/s | `u` (m/s) | None | No |
| SW radiation | `srad_wm2`, W/m2 | `Qsi` (W/m^2) | None | No |
| LW radiation | `lrad_wm2`, W/m2 | `Qli` (W/m^2) | None | No |
| Pressure | `pres_pa`, Pa | not written | used only inside the humidity conversion | **YES** if written as `p` |

## Error Handling

See `diagnostics/triplets.yaml` for the diagnostic triplets (current count: the KI map at the top of this file) covering:
- **Unit conversion** (dt_001, dt_002, dt_009): humidity, precipitation, VIC-CRHM mismatch
- **Silent errors** (dt_006, dt_010, dt_011, dt_012, dt_016): parameter clamping, double-counting, winter gaps, CRS mismatch, wrong module
- **Format errors** (dt_003, dt_005, dt_013, dt_018): .obs header, parameter count, section delimiters, timestep
- **Runtime errors** (dt_004, dt_007, dt_008, dt_014, dt_017): module deps, paths, crashes, empty output, Boost

**When this section was written, silent errors were 7 of 18 triplets (39%)** -- consistent with the 37% rate across all 15 models in the toolkit.

## Quick Start

```bash
# 1. Build CRHM
bash install_crhm.sh

# 2. Create HRUs
python tools/s1_basin_setup/create_hru_config.py --dem_path dem.tif --landcover_path lc.tif --shapefile_path basin.shp --output_dir out/hru

# 3. Build the weather input straight from the source (basin mean; use --lat --lon for one point)
python tools/s2_observation_data/build_obs.py --source cmfd --basin_shp basin.shp --forcing_dir KISSPATH_DATA/forcing/Data_forcing_03hr_010deg --start_year 2000 --end_year 2010 --output_path out/basin.obs
#    then read out/basin.obs.meta.json: check the yearly precipitation, note forcing_elev_m for derive_parameters.py

# 4. Select modules (prairie example)
python tools/s3_module_selection/select_modules.py --basin_type prairie --output_path out/modules.json

# 5. Create .prj file
python tools/s4_parameter_config/create_prj_file.py --hru_config out/hru/hru_config.json --module_chain out/modules.json --obs_path out/basin.obs --start_date "2000 1 1" --end_date "2010 12 31" --output_path out/basin.prj

# 6. Validate
python tools/s4_parameter_config/validate_prj.py --prj_path out/basin.prj

# 7. Run CRHM
python tools/s5_execution/run_crhm.py --crhm_exe model/crhmcode/crhmcode/build/crhm --prj_path out/basin.prj --output_path out/output.txt

# 8. Parse and plot
python tools/s5_execution/parse_crhm_output.py --output_path out/output.txt --output_format both --output_dir out/parsed
python tools/s5_execution/plot_crhm_results.py --csv_path out/parsed/crhm_results.csv --output_dir out/plots --title "My Basin"
```

## Validation Status

Run results (site, period, scores) are not kept here. They live in the run records
(`test_runs` in hydrocraft.db and each run's own result files).

**Source of truth:** `docs/validation_convention.yaml` for bars and citations.
A metric value is not a verdict unless it is judged against the cited convention for the matching
dag variable and observation shape.

### Rank-1 Discharge Bar

For `basinflow_s` against a point time series, `docs/validation_convention.yaml`
retains NSE as the determining metric.

| Dag variable | Obs shape | Metric | Direction | Bar (convention, cited) |
|--------------|-----------|--------|-----------|--------------------------|
| `basinflow_s` | `point_time_series` | `nse` | maximize | satisfactory >= 0.5, good >= 0.65, very_good >= 0.75 (`me2015`) |
| `basinflow_s` | `point_time_series` | `pbias` | zero_centered | satisfactory <= 25.0%, good <= 15.0%, very_good <= 10.0% absolute bias (`me2015`) |

### SWE Convention Bars

For `SWE`, the cited pass-bands in `docs/validation_convention.yaml` are:

| Dag variable | Obs shape / use | Metric | Direction | Bar (convention, cited) |
|--------------|------------------|--------|-----------|--------------------------|
| `SWE` | point or regional/spatial time series | `nse` | maximize | satisfactory >= 0.5, good >= 0.65, very_good >= 0.75 (`me2015`) |
| `SWE` | time series | `nrmse` | minimize | satisfactory <= 1.0 (`krinner2018`) |
| `SWE` | point snapshot | `pbias` | zero_centered | satisfactory <= 30.0% absolute bias (`fang2013`) |
| `SWE` | spatial snapshot / binary snow-cover comparison | `csi` | maximize | satisfactory >= 0.7 (`hanzer2016`) |

### Other Output Convention Notes

| Dag variable | Convention status |
|--------------|-------------------|
| `Subl` | direct sublimation PBIAS has no cited threshold in the convention; use SWE mass redistribution and streamflow effects as context. |
| `hru_actet` spatial CSI | no cited threshold in the convention; cited ET NSE/PBIAS are context only. |
| `soil_moist` spatial NSE | no cited threshold in the convention for CRHM column-integrated storage against satellite top-layer products. |
| `snowmeltD` PBIAS | no cited threshold in the convention; use SWE ablation timing and runoff consistency as context. |
| `infil_act` PBIAS | no cited threshold in the convention for modelled actual infiltration into soil. |

---

*This knowledge infrastructure package was created using the Knowledge Dissection Toolkit (Zhang et al., Nature, under review).*
*Package: hydrocraft-crhm v1.0.0 | 6 pipeline stages | current tool, stage-doc and triplet counts: the KI map at the top of this file*

---

## Mountain Module Chain

**15 modules**

```
basin → global → obs → calcsun → Slope_Qsi → walmsley_wind → intcp → pbsm → albedo → ebsm → netall → crack → evap → Soil → Netroute
```

| Module | Purpose | Key Parameters |
|--------|---------|---------------|
| basin | Geometry | basin_area, hru_area |
| global | Global radiation | Time_Offset |
| obs | Read forcing | precip_elev_adj (USE 0.05 for mountains!) |
| calcsun | Solar angles | (uses hru_lat) |
| **Slope_Qsi** | Slope radiation | hru_ASL (aspect), hru_GSL (slope) |
| **walmsley_wind** | Topo wind amplification | A=4.0/3.0/0.5, L=500/800/2000 |
| intcp | Canopy interception | (forest HRUs only) |
| pbsm | Blowing snow | fetch, N_S, distrib |
| albedo | Snow albedo decay | Albedo_bare, Albedo_snow |
| ebsm | Energy balance melt | tfactor, nfactor |
| netall | Net radiation | (computed from Qsi, Qli, albedo) |
| crack | Frozen soil infiltration | fallstat, infDays, Major |
| evap | Evapotranspiration | evap_type, Ht |
| Soil | Soil + GW | gw_K, gw_max, soil_gw_K |
| Netroute | Routing | Kstorage, Lag, gwKstorage, gwLag |

### Critical Lessons from Mountain Runs

1. **.obs header**: NO `####` line before variable declarations — causes infinite loop (dt_v001)
2. **pbsm required**: Without it, CRHM segfaults on wildcard SWE search (dt_v002)
3. **NASA POWER hourly precip units CHANGED (dt_v013)**: until about 2026-06 hourly values were a mm/day rate (÷24 was right); since then the API returns mm/hour. The loader now reads the unit from the response and checks the yearly total against the daily product. Never pass `--precip_scale 24`.
4. **Mountain precip scaling**: NASA POWER precipitation can be too low or too high in mountains — check the runoff coefficient before the first run (see "Mountain discharge rules" below)
5. **GW parameters**: gwKstorage=50-80, gwLag=500-1000, gw_K=2-5 for sustained winter baseflow
6. **Wind amplification**: Walmsley A=4.0 for alpine ridges (NASA POWER wind is 3.5x too low)

### Mountain discharge rules (from past runs)

These rules come from past mountain runs scored on discharge (`basinflow_s`).
Run results are not kept here (see the Validation Status section).

**Groundwater store.** The `create_prj_file.py` hardcoded defaults made the
groundwater system dead (`gw_init=0`, `Netroute gwKstorage=0`, `gwLag=0`,
`Soil soil_gw_K≈0.001`, `gw_K≈0.001`): no winter baseflow and an un-attenuated
freshet. If monthly-mean sim discharge in Jan-Mar is ≈ 0 while obs shows steady
winter flow, enable a slow GW reservoir (`Soil soil_gw_K`, `gw_K`, `gw_max`,
`gw_init`, `Netroute gwKstorage`, `gwLag`). Size the store from the observed
baseflow PROFILE, not from runoff depth: near-zero winter flow → small store;
steady winter flow → larger store; fall (Sep-Nov) flow equal to or above the
April shoulder (karst / spring-fed) → large slow store plus long Netroute
`Kstorage` and `Lag`. Feed the GW store with a large `Soil soil_gw_K` (it takes
soil excess first), and set `Soil soil_ssr_runoff=0` so the rest goes to interflow
(`ssr`) instead of surface runoff. That only slows the flow if Netroute
`ssrKstorage`/`ssrLag` are above 0 (default 0). If winter flow is low and lowering `gw_K` does not help,
the store is recharge/capacity-limited: raise `gw_max` + `gw_init`, do not lower
`gw_K`. `gwLag` delays the routing reservoir, not the Soil-module gw drainage
that sets the recession.

**Water balance.** A water-balance FAIL with clean units on a long run is not a
unit error by itself. Check it with `tools/s5_execution/check_water_balance.py`
(dt_021, dt_022). Output `Soil gw`, `Soil Sd`, `Soil soil_rechr` as
Display_Variables so the storage change can be closed.

**obs_elev starts at the forcing elevation.** `obs_elev` MUST be the elevation
the forcing's temperature actually represents — for NASA POWER that is the
reported site elevation, returned in `geometry.coordinates[2]` of any POWER API
response (climatology endpoint is quickest):
```python
import requests; s=requests.Session(); s.trust_env=False
j=s.get("https://power.larc.nasa.gov/api/temporal/climatology/point",
        params={"latitude":LAT,"longitude":LON,"community":"RE",
                "parameters":"T2M","format":"JSON"}).json()
obs_elev = j["geometry"]["coordinates"][2]
```
Do NOT guess obs_elev as a mid-HRU value. CRHM lapses temperature from obs_elev
to each hru_elev; obs_elev too HIGH warms the lower HRUs and melts their snow
early, too LOW delays melt.

**obs_elev as the timing knob (DISCHARGE-SCORED RUNS ONLY).**
- Sim freshet peaks late of obs → raise obs_elev in 50-100 m steps; early →
  lower it. Stop when the sim peak MONTH matches obs.
- Raising obs_elev warms every HRU by the same amount (lapse_rate x change / 100).
  A fat melt tail in the 1-2 months after the obs peak can mean the high HRUs are
  still too cold (raise obs_elev) or the routing storage is too heavy (see
  "Recession shape" below): if moving obs_elev does not shrink the tail without
  moving the peak month, it is routing.
- Over-shooting gives a spurious early-April melt, more ET and negative PBIAS.
  If an April rise appears, step obs_elev down until April matches without the
  peak sliding later.
- Where the best obs_elev sits against the alpine HRU varied between basins;
  sweep it and judge by peak month, post-peak tail and April, not by a fixed
  offset.
- **NEVER apply this knob when the scored variable is SWE or any other mass
  state.** For SWE it raises HRU temperature and deletes snow mass directly. On
  SWE-scored runs obs_elev is FIXED at the forcing-source grid-cell elevation
  that derive_parameters.py computes (see the HARD RULE section below).

**Precipitation volume.** Before the first run, compute the obs runoff depth
(mean Q × 86400 × 365 / area) and the runoff coefficient against the raw
forcing P. A coefficient above ~0.9 is physically impossible for a snowmelt
basin and means the forcing precipitation is too low; a raw coefficient near
0.4-0.6 means the POWER precipitation is about right or too high (CRHM ET can be
lower than real mountain ET). Aim for
P ~ obs runoff + mountain ET + a small storage change. NASA POWER can also be
too high in some basins, so check the PBIAS sign after the first run. Scale with
`obs ClimChng_flag=1` + `ClimChng_precip` (or `build_obs.py --precip_scale`);
PBIAS moves almost linearly with it. Set precipitation for PBIAS first, then
obs_elev for timing, then re-zero PBIAS. A large precipitation scale can hide a
groundwater leak (dt_021).

**ET.** A template .prj with `Shared inhibit_evap=1` suppresses ET and inflates
volume; set it to 0 on every HRU.

**Recession shape.** obs_elev moves the peak TIMING; Netroute `Kstorage` sets
the post-peak RECESSION SHAPE. Set obs_elev for the peak month first. Then, if
the 1-3 months after the peak run persistently HIGH while winter and PBIAS are
fine, lower `Kstorage`; if a broad, late freshet recedes too fast, raise it.

**HRU bands.** Place HRU elevations on the DEM hypsometry (e.g. p80 / p50 / p15
with ~25/50/25% area, or area-equal terciles), not on round guesses.

**Template transfer.** When a new basin's hypsometry, freshet month AND observed
baseflow profile (winter and fall flow) match an earlier well-scored basin, reuse
that whole .prj (obs_elev, GW recipe, routing) and retune only precipitation and
obs_elev, instead of starting from defaults. If the baseflow profile differs, size
the GW store again (see "Groundwater store").

**DEM tiles and outlet.** `ki_tools_common.terrain_ops.delineate_basin` needs a
DEM mosaic that fully covers the basin's UPSTREAM extent, not just the gauge.
Sketch which way the river drains and download one tile PAST the expected
headwater divide. Copernicus GLO-30 tiles fetch keyless from
`https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{Nyy_00_Wxxx_00}_DEM/...tif`.
The HYDAT station lat/lon can sit a cell or two off the mapped channel. If the
delineated area is far too small, tiles are missing; if it overshoots the gauge
area, the snap grabbed a nearby drainage — tighten `snap_distance_m`.

**Limits of point forcing.** Point forcing (NASA POWER) cannot resolve a sharp
observed peak or a local orographic-rain flood; one such event can dominate the
error of a whole period. CRHM's bucket GW empties faster than real karst
storage. Do not tune parameters to chase these.

### NASA POWER cal/val PERIOD TRAP (silent n=0)

`validators/standard_calval.compute_calval_metrics` **hardcodes the 1981-1990
Bengbu periods**. NASA POWER **hourly** forcing only exists **from 2001-01-01**, so
any NASA-POWER-driven cold-region run (the recommended forcing here) has ZERO overlap
with the hardcoded windows and the helper silently returns `n=0, NSE=None` for every
period. This is NOT a model failure — it is a period mismatch. When forcing starts
≥2001, you MUST override: use spinup=first year, then a 5/5 split of the remaining
record (e.g. 2005-2015 → spinup 2005, CAL 2006-2010, VAL 2011-2015) and compute with
the `_nse/_kge/_pbias/_r` helpers directly. Record the override periods in
`period_calibration`/`period_validation`.

### Forcing preflight gap (NASA POWER / CRHM .obs unsupported)

`validators/preflight_forcing.py --source auto` only recognizes cmfd/mswx/era5/fluxnet
— it returns `FAIL: Unable to detect data source` on a built CRHM `.obs` (NASA POWER
origin). For CRHM runs, validate units directly on the `.obs`: `t` in [-50,45] °C,
`max(rh) > 1.0` (the #1 silent humidity bug, see above), `p` ≤ ~50 mm/hr with annual
total physically plausible, `u` ≥ 0 m/s, `Qsi` ≤ ~1100 W/m². `build_obs.py`
already enforces these bounds at write time.

**TOOL BUG FIXED — validate_obs_file.py mislabeled 'p' as pressure and required
'ppt'.** CRHM's obs module (and the canonical `build_obs.py`, and every
validated .obs in outputs/) names precipitation **`p`** (mm). `validate_obs_file.py`
hard-required a `ppt` declaration AND carried `PHYSICAL_BOUNDS["p"]=(30,110)` as
*pressure (kPa)* — so it raised a CRITICAL "precip 'ppt' not declared" error and
flagged ALL 96408 precip values out-of-bounds on a perfectly valid file. Fixed:
`p` now bounds (0,500) as precipitation, pressure renamed to `press`, and the
required-variable check accepts `p` (or legacy `ppt`). Validator now returns 0
errors / 0 warnings on canonical NASA-POWER .obs.

---

## FLAT / OPEN / REGIONAL domains — SWE rules

A FLAT, treeless, **regional** domain scored on **SWE** (the kind of land PBSM
was built for) hits a cluster of gaps that a mountain/discharge run can never
hit. All are fixed in the canonical tools; the notes below are what you need to
KNOW.

**1. `pbsm` never received ANY parameters — the entire blowing-snow
parameterisation was a silent no-op.** `create_prj_file.py`'s `DEFAULT_PARAMS`
is keyed on the CAPITALISED GUI module names (`PBSM`), but every validated chain
uses the lower-case CLASSIC names (`pbsm`). The parameter loop skipped any module
missing from the table, so `fetch`, `Ht` and `distrib` — everything
`derive_parameters.py` computes for blowing snow — were never written, and CRHM
ran on its built-in defaults. Check any older .prj: it declares
`pbsm CRHM 11/20/17` under Modules and carries not one `pbsm <param>` line.
Fixed with a `MODULE_PARAM_ALIAS` (`pbsm` -> `PBSM`). **Consequence: a result
made with an older .prj ran without any pbsm parameters, so re-verify it rather
than assuming it holds.**

**2. HRUs must be ordered by ASCENDING VEGETATION HEIGHT on a blowing-snow
domain.** `Classpbsm.cpp` cascades drift along the HRU list (exposed -> sheltered)
and logs `'vegetation heights not in ascending order'` when the list is not
sorted that way; the drift then deposits on the wrong units. The land-cover
cross-tab emits HRUs in raster-class order (e.g. stubble 0.15 m, forest
15 m, grassland 0.3 m — a violation). Use
`create_hru_config.py --order_by_veg_height`. Source-verified parameter facts:
`fetch` range is **300–10000 m** (not 10), `distrib` is **-10..10** (negative =
"all drift deposited", a mode the old min of 0 made unreachable), and `N_S`/`A_S`
are `decldiagparam`, so emit them only when explicitly set.

**3. Dropping the canopy module on treeless terrain SEGFAULTS CRHM (dt_v006).**
`pbsm`, `albedo`, `ebsm`, `netall` and `crack` all read `net_rain`/`net_snow`,
which ONLY a canopy module declares. "No trees, so drop `intcp`" is the natural
inference on steppe and it core-dumps after the banner with a 70-byte
header-only output file and NO error message. Keep `intcp` — with `Ht` ~0.3 m it
passes precipitation through essentially untouched. `select_modules.py` now fails
closed on such a chain instead of emitting it.

**4. Use `prairie_reduced`, never the legacy `prairie` chain.** The legacy
4-process chain (`PBSM > PrairieInfil > Soil > Netroute`) is UNVALIDATED and has
no energy-balance melt at all — no `albedo`, no `netall`, no `ebsm` — which is
fatal when SWE is the scored variable. Auto-detection routes flat+open
domains (relief < 500 m, open fraction > 50%) to `prairie_reduced`.
**History:** until 2026-07-25
`prairie_reduced` WAS the validated 13-module chain (pbsm + ebsm); that chain is
now called `prairie_ebsm_legacy`. On 2026-07-26 the preset's melt module was switched to
SnobalCRHM with `pbsm` left in place, which segfaults (dt_v012). Since
2026-10-02 the preset is `pbsmSnobal` + `SnobalCRHM`: it runs, but it has no
validated SWE pass yet. `select_modules.py`'s
`MODULE_DB` also gained the nine modules it was missing (`calcsun`, `intcp`,
`pbsm`, `albedo`, `ebsm`, `netall`, `crack`, `evap`, `walmsley_wind`) — before
that, `chain_validation` reported the VALIDATED chain as eight "Unknown module"
ERRORs, i.e. pure noise, and ERRORs were only logged, never enforced.

**5. A REGIONAL domain needs no catchment: `create_hru_config.py --bbox`.**
For a gridded regional-aggregate comparison there is no gauge, so there is no
basin to delineate; the tool previously hard-required a shapefile. `--bbox
minlon,minlat,maxlon,maxlat` builds the rectangle and writes `region.geojson`,
which the observation clip MUST reuse so domain and obs share one boundary. The
HRU COUNT IS SET BY dag.yaml safety.validation_limits, NOT by the terrain: <100
km2 uses 3-5 HRUs, 100-1000 km2 uses 5-15, >1000 km2 uses 10-50. On flat terrain
reach that band by crossing land cover with elevation bands
(`--n_elevation_bands 5 --min_hru_area_frac 0.01`); the bands also carry the
lapse-rate signal that sets melt timing. `--n_elevation_bands 1` is permitted
ONLY for domains under 100 km2. A run that scores below the dag band must record
an explicit, evidence-backed exemption in result.json -- silently
under-discretising a regional domain makes every metric PROVISIONAL.

**6. ALWAYS pass `--landcover_scheme`.** The tool's built-in table is a private
CRHM scheme with AVHRR/UMD bolted onto codes 10–16. Hand it CLCD or GLCFCS30 —
the curated primary China/global products — and every code still resolves, just
to the WRONG surface: CLCD grassland (4) became `deciduous_forest` (15 m canopy,
50 m fetch) and GLCFCS30 grassland (130) fell through to the generic default.
Since `fetch_m` is the master blowing-snow control, an open steppe silently lost
the very physics the domain exists to test. Documented legends now ship for
`crhm`, `avhrr_umd`, `clcd`, `glcfcs30` and `esa_cci`, with a warning on unmapped
codes. Related: `derive_parameters.py`'s pbsm fetch lookup was keyed on names its
own s1 tool never emits (`crop_stubble`, `bare_ground`, `alpine_tundra` were all
absent), so those HRUs fell through to the 300 m MOUNTAIN MINIMUM, on the most
wind-exposed surfaces.

**7. `pbsm distrib` was dead on flat terrain.** `derive_parameters.py` set the
drift redistribution from ELEVATION alone, gated at >200 m of relief BETWEEN
HRUs. On prairie/steppe that leaves every `distrib` at 0 — no inter-HRU transport
at all, so blowing snow could only sublimate in place, never relocate. An
EXPOSURE fallback now runs when the elevation rule finds no sink (open,
short-vegetation source -> sheltered sink, area-weighted, normalised to 1.0). It
applies ONLY in that case, so mountain basins keep identical parameters.

### PRE-RUN SETUP CONTRACT — scored SWE on a flat/open REGIONAL domain

Satisfy ALL FOUR before any SWE number is reported. A run that misses one is a
SETUP failure and its metric is PROVISIONAL, not a model verdict.

**1. HRU count must satisfy the dag band** (see item 5 above): 10-50 HRUs for a
>1000 km2 domain. Cross land cover with `--n_elevation_bands 5`.

**2. MANDATORY SNOW-MASS AUDIT.** SWE is a mass state, so the sinks must be
observable before the state is scored. Emit these SOURCE-VERIFIED variables --
names checked against `Classpbsm.cpp` declvar/declstatdiag and `ClassSoil.cpp`:

    pbsm SWE, pbsm Subl, pbsm cumSubl, pbsm Drift, pbsm cumDrift,
    pbsm cumDriftIn, pbsm snowdepth, Soil Sd,
    obs hru_p, obs hru_snow, obs cumhru_snow

The last three are the audit's DENOMINATOR and dag.yaml:399's remaining closure
compartment: `hru_p` is ClassObs.cpp:101, `hru_snow` is ClassObs.cpp:113 and
`cumhru_snow` is ClassObs.cpp:115 (declstatdiag, cumulative mm). Emitting the
sink without the model's own snowfall leaves the ratio uncomputable FROM THE
RUN, forcing a reconstruction off the raw forcing that cannot see CRHM's own
rain/snow partition or its snow-catch adjustment. Difference the CUMULATIVE
pair (`cumSubl`, `cumhru_snow`) across the accumulation window, so the
`Summary_period: Daily` aggregation cannot distort the ratio.

Then compute cold-season sublimation as a FRACTION OF SNOWFALL and compare it
against dag.yaml safety.warnings: **sublimation is 15-40% of snowfall in
prairie, 30-50% in boreal forest**. Outside that band the run is wrong on
physics no matter what NSE says.

WARNING: `select_modules.py`'s MODULE_DB advertises pbsm outputs `drift_in`,
`drift_out` and `cumDriftOut`. THESE DO NOT EXIST in `Classpbsm.cpp` (the real
names are `Drift`, `cumDrift`, `cumDriftIn`). CRHM silently omits unrecognised
Display_Variable lines, so an audit built from MODULE_DB yields empty columns
and no error. Always verify a variable name in the module source first.

**3. The blowing-snow transport rules are UNVALIDATED.** The exposure-based
`distrib` fallback and the extended fetch lookup (item 7 above) were authored
during one run and have not been tested on their own. Validate them on a domain
with known blowing-snow behaviour before they parameterise a scored run, and
declare their use in result.json.

**4. Energy-balance melt wants HOURLY forcing.** dag.yaml safety.validation_limits
states full energy-balance snowmelt requires hourly forcing; CMFD is 3-hourly and
the KI has never established that 3-hourly is adequate for `ebsm`. Either
disaggregate to hourly, or record an explicit evidenced ruling that it is
acceptable. Do not leave it undeclared.

### PBSM PROCESS-ACTIVITY GATE — `Ht` is an ON/OFF SWITCH, not a roughness

READ THIS BEFORE WRITING ANY PBSM PARAMETER ON A SHALLOW-SNOW OPEN DOMAIN.

**The mechanism (Classpbsm.cpp:529-546).** Each timestep PBSM computes the
vegetation still exposed above the snow:

    E_StubHt = Ht[hh] - Common::DepthofSnow(SWE[hh]);   // line 529
    if (E_StubHt > 0.01) {                              // line 534
      Znod  = sqr(Ustar)/163.3 + 0.5*N_S*E_StubHt*A_S;
      Ustn  = Ustar*sqrt((Beta*Lambda)/(1.0+Beta*Lambda));
      Uten_Prob = (log(10.0/Znod))/KARMAN * min<double>(0.0, Ustar-Ustn);
    } else {
      Uten_Prob = hru_u_;
    }

`Ustn` is ALWAYS <= `Ustar`, so `min(0.0, Ustar-Ustn)` is IDENTICALLY 0 and
**Uten_Prob == 0 whenever the vegetation is exposed by more than 1 cm.**
`ProbabilityThresholdNew` accumulates probability only inside
`while ((Wind <= Uten_Prob) && (Uten_Prob >= 3.0))`, so `Prob == 0`, the
`if (Prob[hh] > 0.001)` block at Classpbsm.cpp:548 never executes, and **Drift
and Subl are exactly zero.** Blowing snow in CRHM 4.02 switches ON only once
snow depth buries the vegetation to within 1 cm. `Ht` is a STEP FUNCTION on the
whole module, not a graded roughness effect. There is no error, no warning, and
SWE simply over-accumulates.

**Seen in practice:** dt_v011 (PBSM almost inert on an open domain: timing right, snow mass too high).

**RULE 1 — `pbsm Ht` is the WINTER EXPOSED vegetation height, NOT the
growing-season canopy height.** The shipped Pomeroy-authored prairie projects are
the reference:

    crhmcode/prj/badlake.prj:51-52    Ht = 0.05  0.25  0.6
    crhmcode/prj/smithcreek.prj:447   Ht = 0.001 0.12 0.4 0.7 0.001 6 1.5 ...
    (both files are in the CRHM SOURCE tree, <crhmcode>/crhmcode/prj/, not in this KI)

Every blowing-snow SOURCE HRU in both is **0.001-0.12 m**. Grazed / dormant
Eurasian steppe belongs in that same 0.02-0.10 m band. 0.3 m is taller than any
source HRU in either validated project and silently disables the module. Do NOT
inherit `veg_height_m` from the land-cover table — that value is correct for
`evap Ht` (a growing-season quantity) and wrong for `pbsm Ht`. Set it from the
grazing / harvest state of the winter surface and RECORD the choice in
result.json.

**RULE 2 — set `pbsm inhibit_bs = 1` on every canopy HRU.**
smithcreek.prj:457-458 writes `inhibit_bs = 0 0 0 0 0 1 0 ...` — the 1 is on
the HRU with Ht = 6 m. The CRHM default is 0 (Classpbsm.cpp:132), so omitting the
line runs prairie blowing-snow physics inside forest, which dag.yaml
safety.validation_limits declares invalid and hazard
`wrong_module_chain_for_landscape` flags as SILENT. Shortening `fetch` to 300 m is
NOT a substitute. The same HRUs must also not be the sole `distrib` sinks: a
source->sink matrix needs a terrain basis, and a lat/lon `--bbox` domain has none
— declare `distrib` UNVALIDATED for `region_bbox` and say so in result.json.

**RULE 3 — do NOT tune `N_S` / `A_S`.** They are `decldiagparam` with defaults
320 (1/m^2) and 0.003 m (Classpbsm.cpp:122-124), identical to the values
badlake.prj:172-183 writes explicitly. They are not why PBSM is inert; `Ht` is.

**RULE 4 — the activity gate is MANDATORY and PRE-SCORE, not advisory.** The
MANDATORY SNOW-MASS AUDIT above tells you to EMIT cumSubl / cumDrift /
cumhru_snow. **Emitting them is not the check.** Before any metric is computed,
area-weight the LAST cumulative value of each by `hru_area/basin_area` and form
`frac_subl = cumSubl_aw / cumhru_snow_aw` (and `frac_drift` likewise), then
REFUSE to emit a score when `frac_subl` falls outside the dag band for the
landscape: **0.15-0.40 prairie/steppe, 0.30-0.50 boreal forest**. A run outside
the band is a SETUP failure: its metric is PROVISIONAL, it may not be reported as
CRHM skill, and it must NEVER be routed to `requires_calibration` — calibration
cannot be the diagnosis while the dominant mass sink is switched off. Report
`frac_subl`, `frac_drift` and the pass/fail in result.json every run.

**RULE 5 — a regional-aggregate SWE score may not be driven by one centroid
cell.** A single-point `basin.obs` with `nobs 1`, `precip_elev_adj = 0` and
`catchadjust = 0` gives every HRU IDENTICAL precipitation whatever its
elevation, on a dag edge (precipitation->SWE) graded HIGH. For `domain_kind = region_bbox`, drive the run
with a region-mean forcing series over the identical polygon, or with `nobs > 1`
(one obs column set per elevation band) and `precip_elev_adj` set from the band
structure. A centroid cell is admissible only for a point/small-catchment case.

**RULE 6 — a failed obs mass-consistency screen constrains the METRIC FAMILY,
not just the aggregation.** When `screen_swe_obs.py` reports
`shallow_snow_regime: true` or `mass_inconsistent_pct` above threshold,
demoting daily to monthly is necessary but NOT sufficient. In that
regime the passive-microwave retrieval uncertainty is comparable to the signal, so
magnitude metrics (NSE, PBIAS, KGE) become **reported-but-not-determining** and
the DETERMINING metrics become pattern/timing: `r`, peak-SWE DOY, snow-season
onset and melt-out date. State which family is determining in result.json before
scoring, or pair the retrieval with an independent in-situ SWE source.

### HARD RULE — scoring CRHM against a SATELLITE SWE product

Passive-microwave SWE (ESA Snow_cci / GlobSnow and relatives) is a *retrieval*,
not a measurement. In shallow-snow regimes it carries error comparable to the
entire signal, and its day-to-day variability is dominated by brightness-
temperature noise rather than by real snow mass. Three obligations follow.

**1. Screen the obs before touching a single parameter.**

    python tools/s2_observation_data/screen_swe_obs.py \
        --obs_csv <regional_mean_swe.csv> \
        --forcing_obs '<workspace>/obs/cmfd_*.obs' \
        --out_json <workspace>/swe_obs_screen.json

The screen tests the OBS against the same forcing the model gets: a snowpack
cannot gain more water in a day than that day's precipitation, and cannot lose
water when Tmax is below melting. If more than 2% of cold-season days violate
that budget, the series is **inadmissible at daily resolution**.

**2. Score at the aggregation the retrieval supports.** When the screen fails,
report monthly-mean NSE/KGE/r/PBIAS plus peak-SWE and snow-season mean, and say
so explicitly in the result.

Aggregation averages out retrieval noise, but it does NOT touch a mass bias. A
bias that stays the same under aggregation is an attribution problem, not a
timing problem.

**3. When SWE is the scored variable, the forcing knobs are LOCKED.** Set
`ClimChng_precip = 1.0` and `obs_elev` = the forcing-source grid-cell elevation
from derive_parameters.py, and leave them there. For a discharge-scored run
those two knobs move TIMING and volume through a long causal chain. For SWE they
write the scored quantity directly — cutting precipitation removes snow mass and
raising obs_elev melts it — so tuning them against SWE is not calibration, it is
fabrication, and it is the 'compensating-errors calibration' hazard dag.yaml
already names. A large residual bias under LOCKED knobs is a REPORTABLE FINDING
(an unresolved forcing-vs-retrieval attribution needing in-situ data), not a
defect to tune away.

Diagnostic that tells you the model is fine and the obs is not: correlate
water-year cold-season snowfall P(T<0) against sim peak SWE and against obs peak
SWE. If the simulated
snowpack tracks its own forcing far better than the retrieval tracks the region's
precipitation, that is the signature of retrieval error, not model error.

### Scoring the run so the number is TRUSTABLE (record contract)

A correct model run whose number cannot be re-derived from its own evidence is
not a result. Three rules, all learned the hard way (dt_v008):

**1. Exactly ONE `all_metrics(..., label="headline")` call, on the held-out
frame, dumped LAST.** The record layer binds the reported metric to a
manifest-certified headline dump; the number you put in `metrics.nse` must come
from that same call. If the protocol says monthly, the headline call takes the
MONTHLY frame — do not report a monthly number and dump a daily series.

**2. Parameter-search evaluations are NOT headline dumps.** Pass
`meta={"headline_candidate": False}` to `all_metrics` for every calibration
trial (`ki_tools_common.metrics.dump_scored_series` reads that key straight out
of `meta` — no scorer change needed). Otherwise every trial of a sweep is a
headline candidate in `manifest.jsonl` and drowns the real one. Under the SWE lock the
sweep does not run at all, so the count should be zero.

**3. Assert the reproduction before writing the result.** Re-read the dumped
headline CSV, recompute NSE with `ki_tools_common.metrics.nse`, and fail the run
if it differs from the reported value. Also assert that exactly one dump
carries the `headline` label and that no `cal_trial` dump is a headline
candidate (dt_v008 lists the steps).

**Two caller traps in the shared validators**, both live in this workflow:

- `preflight_forcing.py` prints `(PASS: 1, WARN: 0, FAIL: 0)` as its clean-run
  summary. Deciding pass/fail with `"FAIL" in stdout` therefore reports
  `all_pass=false` on a fully PASSING preflight and files the summary line
  itself as the failure. Parse the `[FAIL]` / `[WARN]` per-variable tokens and
  the summary counts instead.
- `validate_water_balance`'s `tolerance_mm` (default 50) does not scale with
  `period_days`, but the residual it measures does. A multi-year CRHM run with
  a small residual and no unit-error diagnostic grades FAIL on the
  absolute arm alone — the longer a correct run is, the more certainly it
  "fails". Pass `tolerance_mm=50*n_years` and report both verdicts. Do not edit
  the shared default; it is one copy across every KI.
