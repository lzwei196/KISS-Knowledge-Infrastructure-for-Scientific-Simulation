# RZWQM2 Knowledge Infrastructure — Bug Fix Log

**Date**: 2026-03-16
**Context**: End-to-end pipeline test run (Phase 6.3 of Knowledge Dissection Toolkit v1.1)
**Error log**: `diagnostics/error_log.yaml` (12 entries, 2 promoted to triplets)
**Triplets added**: dt_013 (case sensitivity), dt_014 (E-pan/PAR must be 0)
**Workflow**: `workflow/workflow.md` — created from test findings

---

## Bug 1: `particle_density` not defined in standalone call

- **File**: `lib/rzwqm_file.py:1781`
- **Symptom**: `NameError: name 'particle_density' is not defined` when S4 write_soil_properties calls `write_new_soil_physical_properties_to_dat()`
- **Root cause**: Original code relied on `particle_density` as a closure variable from `rzwqm_scenario_mass_generation()`. When the method is called standalone (via tools), the closure doesn't exist.
- **Fix**: Changed to `dict_of_soil_physical_properties[layer].particle_density` — reads from the object, which has the attribute.
- **Status**: Fixed

## Bug 2: Linux filename case sensitivity

- **Files**: `lib/rzwqm_file.py` (constructor), `tools/s7_scenario_assembly/update_ipnames_paths.py`, `tools/s9_result_parsing/parse_layer_output.py`, `diagnostics/triplets.yaml`
- **Symptom**: `FileNotFoundError` for files that exist — e.g., code looks for `RZWQM.dat` but file is `rzwqm.dat`
- **Root cause**: RZWQM2 was developed on Windows (case-insensitive). Template files are lowercase (`rzwqm.dat`), but RZWQM class hardcodes uppercase (`RZWQM.dat`). Mixed conventions throughout.
- **Fix**: Added `_resolve_case()` static method to RZWQM class — tries both cases and picks whichever exists on disk. Applied to `dat_path`, `init_path`, `ipnames_path`, `layer_data`. Updated `update_ipnames_paths` to detect actual filenames. Added diagnostic triplet `dt_013`.
- **Status**: Fixed

## Bug 3a: `fc10_estimate` formula has wrong parenthesization

- **File**: `lib/rzwqm_file.py:1403`
- **Symptom**: Model refuses to run: "SATURATED WATER CONTENT < 1/10 BAR SWC AT LAYER 1". fc10 exceeds ws for ALL soil types.
- **Root cause**: Standalone function computes `((ws-wr)*bp)^psd / 100^psd` — puts `(ws-wr)` inside the exponent. The class method (line 1458) correctly computes `(ws-wr) * bp^psd / 100^psd`. The standalone was a transcription error.
- **Fix**: Changed to `(ws - wr) * (bubbling_pressure / 100.0) ** pore_size_dist + wr` — matches the class method and correct Brooks-Corey equation.
- **Note**: The same bug exists in the original `data_prep_tools/rzwqm_file.py:1403`. The class method version at line 1458 was always correct.
- **Status**: Fixed

## Bug 3b: VIC-derived soil data used instead of atlas

- **File**: `tools/s0_global_data/soil_source_adapter.py`
- **Symptom**: VIC global params give model-derived hydraulic parameters (tiny bubbling pressure, tiny pore size dist) rather than actual soil measurements.
- **Root cause**: Default SOURCE was `vic_global`. VIC parameters are model calibration artifacts, not direct soil atlas measurements. RZWQM2 benefits from more detailed soil hydrology from direct atlas data.
- **Fix**: Changed default to `soilgrids`. Added nodata detection (skip values == -32768 or < -9000).
- **Note**: SoilGrids has gaps in NE China (Jilin returns nodata). Need HWSD or other China database for Chinese sites. Iowa/US works fine.
- **Status**: Partially fixed (need HWSD adapter for China coverage)

## Bug 4: BRK output validation off-by-one

- **File**: `tools/s3_brk_generation/create_breakpoint_file.py:119`
- **Symptom**: S3 output validation fails even though BRK file is correctly generated. Expects calendar code '1' at `lines[18]` but actual header has 19 comment lines + '1' at `lines[19]`.
- **Root cause**: Header comment says "19 lines (18 comment + 1 calendar)" but actual BRK output from `create_breakpoint_file()` writes 19 comment lines + 1 calendar line = 20 total.
- **Fix**: Changed validation to check `lines[19]` and event lines starting at `lines[20]`.
- **Note**: The actual BRK generation in `rzwqm_file.py` was correct — only the tool's output validation had the off-by-one.
- **Status**: Fixed

## Bug 5: ipnames writes lowercase but files are uppercase (or vice versa)

- **File**: `tools/s7_scenario_assembly/update_ipnames_paths.py:113`
- **Symptom**: Binary can't find input files because ipnames.dat references `rzwqm.dat` but file on disk is `RZWQM.dat` (or vice versa).
- **Root cause**: Same as Bug 2 — mixed case conventions. The `update_ipnames_paths` tool hardcoded lowercase, but template files may be either case.
- **Fix**: Tool now detects actual file case on disk before writing paths to ipnames. Covered by Bug 2 fix.
- **Status**: Fixed

## Bug 6: Simulation dates not updated in ipnames.dat

- **File**: `tools/s7_scenario_assembly/update_ipnames_paths.py`
- **Symptom**: Model runs for wrong date range (old template dates 2011-2021 instead of configured 2015-2020), or met data doesn't cover the period, producing empty output.
- **Root cause**: `update_ipnames_paths` only updated file paths (lines 0-7), not the simulation dates (line 8). The original `initialize_scneario_based_on_existing()` in `rzwqm_file.py:973` DOES update dates via `ip[8] = custom_date_format(...)`, but this was not carried over to the tool.
- **Fix**: Added optional `START_DATE` and `END_DATE` parameters to `update_ipnames_paths`. When provided, writes `DD MM YYYY DD MM YYYY` to ipnames line 8.
- **Status**: Fixed

---

## Bug 7: RZINIT.dat truncated — model hits end-of-file

- **File**: `tools/s6_initial_conditions/write_initial_conditions.py`
- **Symptom**: `forrtl: severe (24): end-of-file during read, unit 14, file .../RZINIT.dat` — model crashes after "INITIAL VALUES READ IN"
- **Root cause**: The `write_initial_conditions` tool writes water/temp, chemistry, and nutrient sections based on horizon count. But the Fortran binary expects additional sections or more lines per horizon than the tool provides. Template RZINIT.dat has 149 lines; tool generates only 134.
- **Fix**: Simplified logic to: extend placeholders to match horizon count, then slice. Original had a branch that left `new_list` empty when `len >= len`.
- **Status**: Fixed

---

## Bug 8: S6.5 management write — case sensitivity on RZWQM.dat

- **File**: `tools/s6_management_write/write_management_events.py:269`
- **Symptom**: `RZWQM.dat not found` when template has `rzwqm.dat` (lowercase)
- **Fix**: Added case fallback (try `RZWQM.dat`, fall back to `rzwqm.dat`)
- **Status**: Fixed

## Bug 9: DSSAT crop file not found — RZX path missing trailing slash

- **File**: `tools/s7_scenario_assembly/update_rzx_paths.py:149`
- **Symptom**: ERROR.OUT: `File: MZCER040.CUL Line: 0 Error key: IPVAR` — model can't open cultivar file. Crop doesn't grow. Model exits with code 99 after partial run.
- **Root cause**: The update_rzx_paths tool wrote absolute paths without trailing slashes (`/home/.../DSSAT`). The Fortran binary concatenates this directly with the filename: `DSSATMZCER040.CUL` (no separator). The working Ohio template uses `DSSAT/` (relative, with slash).
- **Fix**: (1) Tool now ensures trailing slash on both path lines. (2) Orchestration passes relative paths (`DSSAT/` and `./`) since the binary runs from the scenario dir as CWD.
- **Domain knowledge**: RZX paths must be relative to the scenario directory (where IPNAMES.DAT lives and where the binary is launched). The Fortran binary does simple string concatenation, not proper path joining.
- **Status**: Fixed

---

## Full End-to-End Run with Real Data (Iowa, 2015-2017)

- **Date**: 2026-03-16
- **Data**: MSWX forcing (real, `KISSPATH_FORCING/`), SoilGrids soil (API), DSSAT maize
- **Hydrology**: Precipitation 71-99 cm/yr (matches Iowa 85-100). ET 65-95 cm/yr. Temperature -28 to +34°C. All physically correct.
- **Crop issue diagnosed and fixed (Bug 10)**: Year 1 planted MAIZE, year 2 SOYBEAN, year 3 WHEAT — model cycled through RZCropSel.rzq entries. Root cause: `write_management_events` used incrementing `ref_num` as crop reference. Fix: use `crop_ref=1` (configurable) for all years.
- **After fix**: All 3 years plant MAIZE.

## Bug 11: Wrong planting density — soybean density used for maize

- **File**: `run_iowa.py` (orchestration)
- **Symptom**: Maize planted at 518,910 seeds/ha — this is actually the SOYBEAN density from the Ohio template.
- **Root cause**: Ohio uses crop_ref=2 (soybean entry) with density 518,910 and crop_ref=1 (maize entry) with density 84,014. We copied the soybean density thinking it was maize.
- **Fix**: Correct maize density is **84,014 seeds/ha** (~34,000 plants/acre, realistic for US corn). Soybean is 518,910.
- **Domain knowledge**: In RZCropSel.rzq, crop_ref=1 maps to the first entry (maize 7000). Planting density must match the crop — maize ~80,000-90,000, soybean ~500,000, wheat ~3,800,000.
- **Status**: Fixed

## Bug 12: E-pan and PAR in .met file must be 0

- **File**: `tools/s2_met_prep/generate_met_file.py:160`
- **Symptom**: Crop dies of water stress despite adequate soil water (74 cm stored). PotRWUP drops to 0. Yield = 0 kg/ha with Ohio calibrated soil.
- **Root cause**: The forcing adapter estimates E-pan and PAR from weather data, and the .met generator writes these non-zero values. When RZWQM2 sees non-zero E-pan/PAR, it uses them directly instead of computing internally. The estimated values override the model's Penman-Monteith ET calculation, producing incorrect water demand that kills the crop.
- **Evidence**: Ohio .met has E-pan=0 and PAR=0 for all days. Setting our values to 0 increased yield from 0 → **6,767 kg/ha** and LAI from 0.11 → **3.07**.
- **Fix**: `generate_met_file.py` now hardcodes E-pan=0 and PAR=0 regardless of CSV input. Comment explains why.
- **Domain knowledge**: RZWQM2 .met columns 7 (E-pan) and 9 (PAR) are labeled "optional, default=0" in the header. They MUST be 0 to let the model compute ET properly. This is a silent error — model runs to completion but produces wrong water balance.
- **Status**: Fixed

## Bug 13: Crop selection lives in rzwqm.dat, not RZCropSel.rzq

- **File**: `tools/s7_scenario_assembly/update_crop_selection.py`
- **Symptom**: Model plants wrong cultivar. RZCropSel.rzq updated to 990001 SPRING but model still uses 990003 WINTER-US.
- **Root cause**: RZWQM2 reads the crop list from **rzwqm.dat** (~line 494), not from RZCropSel.rzq (which is a GUI artifact). The crop entries in rzwqm.dat have format `7002  wheat 990003 WINTER-US`.
- **Fix**: Rewrote `update_crop_selection.py` to update BOTH rzwqm.dat (the real source) and RZCropSel.rzq (keep in sync). Tool now takes crop_code (7000/7001/7002) as input.
- **Domain knowledge**: Crop codes are hardwired: 7000=maize(MZDSSAT.RZX), 7001=soybean(SBDSSAT.RZX), 7002=wheat(WHDSSAT.RZX). The crop_ref in planting events maps to entry position (1→7000, 2→7001, 3→7002).
- **Status**: Fixed

## Bug 14: WHDSSAT.RZX nitrogen routines disabled

- **File**: `tools/s7_scenario_assembly/update_rzx_paths.py`
- **Symptom**: Wheat grows but N uptake is 0, limiting biomass. Ohio template WHDSSAT.RZX had ISWNIT=N (nitrogen off).
- **Root cause**: Template WHDSSAT.RZX simulation control line was `Y  N  Y  N  N  N  N  C` where position 2 (ISWNIT) = N.
- **Fix**: `update_rzx_paths.py` now ensures ISWNIT=Y in all RZX files during path update. Nitrogen should always be on.
- **Status**: Fixed

## HWSD Soil Adapter

- **File**: `tools/s0_global_data/hwsd_soil_adapter.py` (new tool)
- **Data**: HWSD China raster at `KISSPATH_STATIC/HWSD_China_Geo.img`, lookup via `KISSPATH_FORCING/huaihe_raw/soil/HWSD.mdb`
- **Requires**: `mdbtools` system package (apt install mdbtools)
- **Flow**: lat/lon → raster pixel → MU_GLOBAL code → mdb-export HWSD_DATA → sand/clay/BD/OC/pH → texture defaults → 6 RZWQM2 horizons
- **Impact**: Siping maize yield jumped from 1,904 kg/ha (Ohio soil) to **5,908 kg/ha** (HWSD soil). LAI from 2.13 to **4.05**. The soil was the primary limitation.

## Siping Maize with Real HWSD Soil (2012-2017)

- **Date**: 2026-03-17
- **Data**: CMFD forcing + HWSD soil (MU_GLOBAL=11112, loam, sand=38%, clay=23%, BD=1.38)
- **Best yield**: 5,908 kg/ha (2012), 5,350 kg/ha (2017, HI=0.50)
- **Realistic LAI**: 4.05 (typical maize 4-6)
- **Remaining gap**: Years 2013-2015 have low HI (0.27-0.30) due to N stress during grain fill (NStress=0.48 at anthesis). 120 kg N applied at planting leaches before grain fill. Fix: split fertilizer (60 at planting + 60 at V6). Standard NE China practice.
- **Conclusion**: With real soil (HWSD) + real weather (CMFD), the infrastructure produces 60-80% of typical Jilin yields (7,000-9,000 kg/ha) without any calibration. Remaining gap is agronomy (fertilizer timing) and cultivar calibration.

## Bug 15: HWSD backend not integrated into soil_source_adapter dispatcher

- **File**: `tools/s0_global_data/soil_source_adapter.py:566`
- **Symptom**: `source='hwsd'` returns "not yet implemented". Agent falls back to VIC soil.
- **Root cause**: `hwsd_soil_adapter.py` was built as standalone but never wired into the main dispatcher.
- **Fix**: Added HWSD delegation — imports from `hwsd_soil_adapter` and calls the lookup chain.
- **Found by**: Another Claude instance running Hutuo River wheat simulation.
- **Status**: Fixed

## Bug 17: VIC soil converter column mapping off by 2

- **File**: `tools/s0_vic_coupling/vic_soil_converter.py:71-75`
- **Symptom**: "SATURATED WATER CONTENT < 1/3 BAR SWC AT LAYER 1" — fc33=2591, physically impossible
- **Root cause**: bulk_density mapped to [31,32,33] instead of [33,34,35]. Wcr_FRACT mapped to [38,39,40] instead of [40,41,42]. Off by 2 columns in VIC 53-col layout.
- **Fix**: Corrected VIC_COL dict. Verified against actual data: parts[33]=1500 (bulk_density), parts[40]=0.272 (Wcr).
- **Status**: Fixed

## Bug 18: Irrigation timing=4 (ET-deficit) causes IDOI error

- **File**: `tools/s6_management_write/write_management_events.py:232-257`
- **Symptom**: "INPUT INCORRECT FOR IRRIGATION => IDOI" when irrigation enabled
- **Root cause**: Tool used timing=4 (ET-deficit) with MAD fraction 0.50. RZWQM2 tries to parse 0.50 as integer date. All working examples use timing=2 (specific dates).
- **Fix**: Rewrote irrigation to timing=2, type=2 (flood), methodology=1 (fixed amount). Mid-season date auto-calculated.
- **Status**: Fixed

## Bug 19: Empty .sno file in Meteorology/

- **File**: `tools/s7_scenario_assembly/initialize_scenario.py`
- **Symptom**: "end-of-file during read" on .sno file at day 77. File is 0 bytes.
- **Root cause**: initialize_scenario creates empty sno in Meteorology/ but doesn't copy template snow data. The template has akron-updated.sno in scenario dir.
- **Fix**: initialize_scenario.py now copies .sno from scenario dir to Meteorology/{new_name}.sno after initialization.
- **Status**: Fixed

## Bug 20: VIC flux output used as RZWQM2 weather — 90% precipitation loss

- **File**: workflow gap (custom weather CSV generation, not using our tools)
- **Symptom**: Annual precip 76 mm/yr vs actual 693 mm/yr. Crop yields near zero. Silent error — model runs fine.
- **Root cause**: Agent converted VIC flux output (OUT_PREC) to RZWQM2 weather CSV instead of using CMFD via `forcing_source_adapter.py`. VIC output has different variable definitions and the conversion lost 90% of precipitation.
- **Fix**: Updated workflow.md with explicit warning: NEVER use VIC flux as RZWQM2 weather. Always use CMFD/MSWX via forcing_source_adapter. Added to Critical Domain Knowledge section.
- **Domain knowledge**: VIC flux files are model output, not raw forcing. They contain post-processed variables (runoff, baseflow, soil moisture) mixed with forcing echoes (precip, temp). The precipitation values may be partitioned differently or have unit issues when extracted for RZWQM2.
- **Status**: Documented — workflow updated, error recorded

## Cultivar Selection Discovery (not a bug — domain knowledge)

- **Finding**: RZWQM2 cultivar selection chain: RZCropSel.rzq `IB1068` → looks up in MZCER040.CUL → reads params. The rzwqm.dat crop entry is for display only. The actual cultivar ID comes from RZCropSel.rzq.
- **CUL file format**: Fixed-width. ECO# must be at position 24. Misalignment causes silent param read failure.
- **For Chinese cultivars**: Safest approach is to **modify the existing IB1068 line in MZCER040.CUL** with Chinese cultivar params (P1=270, P5=800 for Zhengdan 958) rather than adding a new cultivar ID.
- **Result**: Modifying IB1068 params to Zhengdan 958 values increased yield from 2,443 → **6,882 kg/ha** and extended maturity from DAP 83 → DAP 96.
- **China cultivar database**: `KISSPATH_HOME/DSSAT/Data/Genotype/China/MZCER048_China.CUL` has 10 calibrated Chinese cultivars (HHH summer maize + NE spring maize).

## Bug 16: mass_project_generator key mismatch for met file

- **File**: `tools/s10_mass_generation/mass_project_generator.py:235`
- **Symptom**: KeyError when generating met file via mass generator. Key `output_met_path` doesn't match `output_path`.
- **Fix**: Changed to `output_path` to match `generate_met_file.py` interface.
- **Status**: Fixed

## Yield Assessment

- With SoilGrids texture-default soil + MSWX weather + correct density: **1107-1317 kg/ha** (3 years). Low due to spinup + uncalibrated soil.
- With Ohio calibrated soil + MSWX weather: **0 kg/ha** — Ohio initial conditions don't match Iowa weather timing. Demonstrates that initial conditions are soil+climate specific.
- Ohio template itself: yields ramp from ~1400 to **9722 kg/ha** over 8 years. Spinup is 3-5 years.
- Iowa USDA actual: **12,000-12,700 kg/ha** (2015-2016). Reaching this requires site-specific calibration of soil hydraulic params + initial nutrient pools + possibly cultivar genetic coefficients.
- **Conclusion**: Pipeline delivers all inputs correctly. Yield gap is calibration, not infrastructure.
- **Conclusion**: Infrastructure pipeline is complete. Hydrology is scientifically valid with real data. Crop model needs management/calibration tuning (outside infrastructure scope).

## Previous Run (Iowa, 2015-2020, synthetic weather)

- **Date**: 2026-03-16
- **Site**: Iowa (42.0N, -93.5E), maize, 6 SoilGrids horizons, synthetic weather
- **Result**: Return code 0. 6-year simulation complete. 2.7MB .ana file. Crop grew (PlantGro, Phenology, PLANT4 all populated). All water/carbon/nitrogen/phosphorus outputs generated.
- **Stages**: S0-S9 all passed. Total 9 bugs fixed to reach this point.

---

## Critical Domain Knowledge Discovered

These must go into the workflow.md and diagnostic triplets:

1. **Binary must run from project folder** — RZWQM2 binary uses CWD-relative paths for everything. The subprocess must `cd` into the scenario directory before executing. All paths in ipnames.dat, .RZX files, etc. are relative to CWD.
2. **Each project needs its own binary copy** — When creating a new project, copy the binary (`main_ryzen_patched` on Linux, `RZWQMRelease.exe` on Windows) into the project directory. The binary looks for DSSAT files, config files, and writes outputs relative to its location.
3. **RZX paths must be relative with trailing slashes** — `DSSAT/` not `/absolute/path/to/DSSAT`. The Fortran binary does simple string concatenation (no path joining), so `DSSAT/` + `MZCER040.CUL` = `DSSAT/MZCER040.CUL` (correct), but `DSSAT` + `MZCER040.CUL` = `DSSATMZCER040.CUL` (broken).
4. **Template-first approach** — Copy the entire working template directory, then update only what changes per site. Don't try to generate config files from scratch — RZWQM2 has many sections and the model is sensitive to exact format.
5. **SoilGrids has gaps** — NE China (Jilin) returns nodata. Need HWSD or other atlas for Chinese sites.
6. **Horizon count must be consistent everywhere** — RZWQM.dat (physical, hydraulic, heat, micropore, macropore sections), RZINIT.dat (water, chemistry, nutrients sections), and node discretization all must agree on horizon count. Changing horizons requires updating all sections atomically.

## Result Assessment (Iowa synthetic run)

- **Hydrology**: Water balance runs correctly (precip, infiltration, ET, deep seepage all non-zero and reasonable magnitude)
- **Crop**: Poor — max LAI 0.31 (expect 4-6), grain 1274 kg/ha (expect 8000-12000), crop dies after year 1
- **Root causes of poor crop**: (1) synthetic weather doesn't match Iowa climate well enough, (2) plgen.dat and cntrl.dat from Ohio template may conflict with Iowa maize config, (3) expdata.dat from Ohio template
- **Conclusion**: Infrastructure works end-to-end but needs real weather data (MSWX) and proper per-site config updates for scientifically meaningful results

---

## Full Pipeline Gap Audit (2026-03-16)

### Data Sources

| Source | Tool | Status | Data on this machine? |
|--------|------|--------|----------------------|
| **MSWX** (global 0.1° 3-hourly) | `forcing_source_adapter.py` `_retrieve_mswx()` | Implemented | No — needs `{path}/Tair/Tair_YYYY.nc` etc. |
| **CMFD** (China 0.25° 3-hourly) | `forcing_source_adapter.py` `_retrieve_cmfd()` | Implemented | No NetCDF on disk |
| **ERA5** (global) | `forcing_source_adapter.py` | Stub only ("not yet implemented") | No |
| **SoilGrids** (global 250m) | `soil_source_adapter.py` `_retrieve_soilgrids()` | Working (with nodata fix) | API-based, no local data needed |
| **HWSD** (China raster) | `soil_source_adapter.py` | Stub only ("not yet implemented") | No HWSD data on disk |
| **Crop Calendar** (Sacks global) | `crop_calendar_lookup.py` | Implemented | Needs `KISSPATH_HOME/Crop_model_dataset/` |
| **CROPGRIDS** | `crop_area_lookup.py` | Implemented | Needs external GeoTIFF |
| **NPKGRIDS** | `fertilizer_rate_lookup.py` | Implemented | Needs external GeoTIFF |
| **SPAM 2020** | `irrigation_type_lookup.py` | Implemented | Needs external GeoTIFF |

**Key finding**: MSWX backend is implemented and handles multi-year aggregation. But no forcing data files exist on this machine. Agent needs access to MSWX NetCDF directory.

### Per-Stage Gaps

#### S0: Data Acquisition
- [x] Soil (SoilGrids) — working for US/global (not China)
- [x] Forcing (MSWX) — code ready, needs data files
- [x] Crop selection — working
- [x] Crop calendar — code ready, needs Sacks dataset
- [x] Fertilizer/irrigation lookup — code ready, needs NPKGRIDS/SPAM data
- [ ] **No data availability check** — tools don't verify if datasets exist before attempting retrieval

#### S1: Site Configuration
- [x] write_site_properties — working
- [x] Lat/lon conversion to radians — handled

#### S2: Met Preparation
- [x] generate_met_file — working
- [x] met_quality_check — working

#### S3: BRK Generation
- [x] create_breakpoint_file — working (validation fixed)

#### S4: Soil Properties
- [x] write_soil_properties — working (particle_density fixed)
- [ ] **No physical constraint validation** — fc10 < ws, fc33 < fc10, fc15 < fc33 not checked

#### S5: Node Discretization
- [x] generate_nodes — working

#### S6: Initial Conditions
- [x] write_initial_conditions — working (nutrient write fixed)
- [ ] **Chemistry/nutrient values are placeholders** — not site-specific

#### S6.5: Management Events
- [x] write_management_events — working, writes per-year planting
- [ ] **Cultivar ID not passed downstream** — crop_selector outputs cultivar ID but nothing writes it to RZCropSel.rzq
- [ ] **Winter crop handling** — harvest_doy < plant_doy not properly handled for cross-year crops

#### S7: Scenario Assembly
- [x] update_ipnames_paths — working (dates, case sensitivity fixed)
- [x] update_rzx_paths — working (trailing slash, relative paths fixed)
- [ ] **Binary not copied** — no tool copies main_ryzen/RZWQMRelease.exe into project
- [ ] **RZCropSel.rzq not updated** — cultivar stays at template default
- [ ] **cntrl.dat not updated** — crop model settings from template
- [ ] **expdata.dat not updated** — experimental data from template site
- [ ] **plgen.dat role unclear** — is it input or output? Copied from template as-is

#### S8: Execution
- [x] run_rzwqm2 — working
- [ ] **Should verify binary exists in CWD** — currently just checks the provided path

#### S9: Result Parsing
- [x] parse_ana_output — implemented
- [x] parse_layer_output — implemented
- [ ] **Only 2 variables mapped** — snow and tile_drainage; need full column map

### Priority Fixes for Autonomous Multi-Year Simulation

**CRITICAL (model won't run or gives wrong results for new sites)**:
1. Real forcing data (MSWX) — need data files on machine or download capability
2. Binary copy into project — add to template setup
3. RZCropSel.rzq update — pass cultivar ID from crop_selector
4. cntrl.dat update — at minimum, verify crop model selection matches

**QUALITY (model runs but results may be unrealistic)**:
5. expdata.dat — create a "no observation" template
6. plgen.dat — document its role, verify template is generic enough
7. SNO file — generic snow initialization may be wrong for different climates
8. Chemistry/nutrient initial conditions — use site-specific values from SoilGrids organic carbon

### MSWX Data Access

- **Location**: `KISSPATH_FORCING/` — 7 variables: `Tair, P, Pres, SWd, LWd, wind, spechum`
- **Layout**: `{var}/{prefix}_{YYYY}.nc` (e.g., `Tair/Tair_2015.nc`)
- **Coverage**: 1979-2026, global 0.1° 3-hourly
- **File size**: ~9GB per year per variable
- **Variable names in NC**: `air_temperature, precipitation, downward_shortwave_radiation, wind_speed, surface_pressure, specific_humidity`
- **Units**: Tair in °C (NOT Kelvin like CMFD), P in mm/3h, SWd in W/m², wind in m/s, Pres in Pa, spechum in kg/kg
- **Our adapter match**: Variable mapping in `forcing_source_adapter.py _retrieve_mswx()` matches exactly
- **Performance issue**: 9GB files slow to open with netCDF4 direct indexed reads. HydroCraft at `KISSPATH_ROOT/skills/vic-auto-run/s2_forcing/forcing_1d.py` has optimized MSWX reader with pre-clipping. May need to adopt their approach for speed.
- **HydroCraft MSWX approach**: Renames MSWX vars to CMFD names, converts Tair °C→K and P mm/3h→kg/m²/s for VIC compatibility. For RZWQM2 we DON'T need those conversions (RZWQM2 expects °C and mm).
- **TODO**: Test if adapter produces correct output (currently timing out on 9GB reads). Consider optimizing with xarray sel() or pre-subsetting.

---

## Open Issues (prioritized TODO)

### Issue 1: MSWX forcing retrieval too slow [FIXED]
- **Problem**: 9GB yearly files. Sequential netCDF4 reads took 5+ min per variable. 6-year run = 30+ min.
- **Fix**: Rewrote `_retrieve_mswx()` with `multiprocessing.Pool` — reads all 6 variables per year in parallel. Worker function `_read_mswx_var()` extracts single pixel via netCDF4 indexed read.
- **Performance**: 241s for 1 month (6 parallel file reads). ~4 min/year. 6-year run ~24 min. Disk I/O bound.
- **Verified**: Iowa Jan 2015 — temps -21 to +1.5°C, rain events, RH 44-82%. All physically reasonable.
- **MSWX path**: `KISSPATH_FORCING/` (7 subdirs: Tair, P, Pres, SWd, LWd, wind, spechum, 1979-2026)
- **Status**: Fixed

### Issue 2: Binary not copied into new projects [FIXED]
- **Problem**: Binary must be in the scenario directory (Fortran uses CWD-relative paths). No explicit handling.
- **Fix**: (1) Template-first approach (`shutil.copytree`) already copies binary from template. (2) `initialize_scenario.py` now verifies binary exists after copy and sets executable permission. (3) `run_iowa.py` now references binary from `SCENARIO_DIR` not `TEMPLATE_DIR`.
- **Key insight**: The working template (`linux/`) must contain the binary. `copytree` handles the rest.
- **Status**: Fixed

### Issue 3: RZCropSel.rzq not updated with site-specific cultivar [FIXED]
- **Problem**: `crop_selector.py` outputs cultivar ID but nothing wrote it to `RZCropSel.rzq`.
- **Fix**: Created `tools/s7_scenario_assembly/update_crop_selection.py` — sets primary crop (code 7000) line with crop name, cultivar ID, and description. Format: `7000  maize IB1068 DEKALB 521`.
- **Flow**: crop_selector (S0) → cultivar_id → update_crop_selection (S7) → RZCropSel.rzq
- **Status**: Fixed

### Issue 4: cntrl.dat not updated per site [NOT AN ISSUE]
- **Assessment**: cntrl.dat is output control only — selects which output files to generate (option 7=user-defined), plot variables, and statistics. It does NOT contain site-specific or crop-specific data. The same cntrl.dat works for any site.
- **Status**: No fix needed — template is generic

### Issue 5: expdata.dat from template used for all sites [LOW PRIORITY]
- **Assessment**: Contains observation data (soil moisture, ET, LAI) for model-vs-measurement comparison output (COMP2EXP.OUT). Does NOT affect simulation physics. Template has Akron 1985 data — model runs fine with it for any site, just COMP2EXP.OUT will be meaningless.
- **For calibration**: If user wants to calibrate against observations, they'd provide their own expdata.dat. Not needed for forward simulation.
- **Status**: No fix needed for autonomous runs

### Issue 6: plgen.dat role unclear [RESOLVED — NO FIX NEEDED]
- **Assessment**: Generic plant growth model parameters. Data line is `0` = zero parameterized species, meaning RZWQM2 uses DSSAT crop models instead of built-in generic growth. This is the correct setting for all DSSAT-based simulations. File is required input (ipnames line 5) but template value is universally correct.
- **Status**: No fix needed

### Issue 7: SNO file is generic [QUALITY]
- **Problem**: Same Ohio snow file used for all sites. Wrong initial snow for different climates.
- **Solution**: Generate site-specific `.sno` from climate data, or document that model re-equilibrates snow within first simulation year.

### Issue 8: Chemistry/nutrient initial conditions are placeholders [QUALITY]
- **Problem**: RZINIT.dat chemistry section uses template values. Nutrient pools use generic placeholder values not derived from SoilGrids organic carbon data.
- **Solution**: Use SoilGrids `soc` (soil organic carbon) to derive initial OM pools. pH and CEC could also be sourced from soil databases.

### Issue 9: parse_ana_output only maps 2 variables [FIXED]
- **Problem**: Only `snow` and `tile_drainage` mapped. The .ana has 139 columns.
- **Fix**: Expanded COLUMN_MAP to 40+ variables across hydrology (stored_water, precip, ET, infiltration, runoff, seepage, tile_drainage), nitrogen (uptake, leaching, mineralization, denitrification), crop (biomass, LAI, grain, growth_stage, root_depth), energy/weather (tmin, tmax, radiation, RH), snow/SHAW (snow_depth, SWE, surface_temp), GHG (N2O), and phosphorus. Added UNIT_CONVERSIONS dict for variables needing scaling (tile_drainage cm→mm). Added `col_N` syntax for raw column access.
- **Also**: Rewrote process() to parse .ana directly instead of going through rzwqm_file.py `rzwqm_res_parse()` — works for all variables, not just the 2 hardcoded ones.
- **Status**: Fixed

### Issue 10: SoilGrids China gap [REGIONAL]
- **Problem**: SoilGrids returns nodata for NE China (Jilin). Need HWSD adapter.
- **Solution**: Implement `_retrieve_hwsd()` in soil_source_adapter.py. Needs HWSD raster + lookup table (not on this machine currently).

---

## Workflow.md Requirements (for final authoring)

The workflow.md should document:
1. **Input requirements** — what the user must provide (lat, lon, dates, crop) and what the agent retrieves
2. **Template-first approach** — copy entire working template, then update only what changes
3. **Data flow** — which S0 outputs feed into which downstream tools (JSON schema between stages)
4. **File naming** — case conventions, required files list, what binary expects
5. **RZX relative paths** — Fortran string concatenation requirement
6. **Horizon consistency** — all sections must agree on horizon count
7. **Multi-year management** — planting events per year, fertilizer timing
8. **Per-site config checklist** — every file that needs updating when creating a new site
9. **MSWX data path and performance** — bbox clipping before read
10. **Binary CWD requirement** — binary must be in project dir, all paths relative

---

## Bug 21: `update_crop_selection.py` allows empty cultivar_id

- **Date**: 2026-03-18
- **File**: `tools/s7_scenario_assembly/update_crop_selection.py`
- **Symptom**: rzwqm.dat gets `7000  maize` (no cultivar ID). RZWQM2 falls through to wrong cultivar (e.g., AC0001 TOHONO O'odham instead of IB1068).
- **Root cause**: `cultivar_id` and `cultivar_desc` args were optional with no default. When called without them, the new_line had no cultivar info.
- **Fix**: Added `DEFAULT_CULTIVARS` dict mapping crop codes to sensible defaults (IB1068 for maize, 990002 for soybean, 990003 for wheat). Logs warning to stderr when defaulting.
- **Status**: Fixed

## Bug 22: `update_cultivar.py` only updates DSSAT/ subdirectory CUL file

- **Date**: 2026-03-18
- **File**: `tools/s7_scenario_assembly/update_cultivar.py`
- **Symptom**: RZWQM2 binary reads cultivar params from root `MZCER040.CUL`, not `DSSAT/MZCER040.CUL`. Cultivar override had no effect.
- **Root cause**: Tool only wrote to `DSSAT/*.CUL`. The RZX file specifies `DSSAT/` as genotype path, but the binary also reads root-level CUL files.
- **Fix**: Now discovers and updates BOTH `DSSAT/*.CUL` and root `*.CUL` files.
- **Status**: Fixed

## Bug 23: `_convert_to_040()` ECO# column off-by-one (Fortran fixed-width)

- **Date**: 2026-03-18
- **File**: `tools/s7_scenario_assembly/update_cultivar.py`
- **Symptom**: `MZPHEN` error (Error number 7) when running with overridden cultivar. ECO# lookup fails.
- **Root cause**: VRNAME padded to 16 chars with `.ljust(16)`, but Fortran format needs ECO# at position 24. VRNAME field is actually 17 chars (16 + 1 separator space). ECO# was at position 23 instead of 24.
- **Fix**: Changed `.ljust(16)` → `.ljust(17)` to include trailing separator space.
- **Status**: Fixed
- **Triplet**: dt_021 — "ECO# must start at column 25 (1-indexed). VRNAME field = 16 name chars + 1 separator space = 17 chars total."

## Bug 24: `_convert_to_040()` is maize-only — crashes or produces wrong output for wheat/soybean

- **Date**: 2026-03-18
- **File**: `tools/s7_scenario_assembly/update_cultivar.py`
- **Symptom**: Wheat cultivar override would produce 8-column line (with Height/Biomass) instead of 7-column WHCER040 format. Wrong format specifiers for wheat params. ECO# `DFAULT` not mapped to valid WHCER040 ecotype.
- **Root cause**: Function hardcoded maize-specific: 6 params, `.3f`/`.1f` formats, always appended Height/Biomass.
- **Fix**: Made crop-aware via `CROP_FORMAT_040` dict. Each crop defines: param_count, extra_cols (or None), eco_map (e.g., DFAULT→DSWH02), and custom format lambda.
- **Validation**: Bengbu wheat with CN0121 (YZR Weak Vernal.) → yield jumped from 133 to 3217 kg/ha.
- **Status**: Fixed

## Bug 25: `_read_china_cul()` regex only matches IB####/DFAULT ECO codes

- **Date**: 2026-03-18
- **File**: `tools/s7_scenario_assembly/update_cultivar.py`
- **Symptom**: Soybean cultivars (ECO# SB0001, SB0201, etc.) not parsed from China CUL file.
- **Root cause**: Regex `r'(IB\d{4}|DFAULT)'` only matched maize/wheat ECO# patterns.
- **Fix**: Changed to `r'([A-Z]{2}\d{4}|DFAULT)'` — matches any 2-letter+4-digit ECO# code.
- **Validation**: All 7 soybean cultivars (CN0301-CN0322) now parsed correctly.
- **Status**: Fixed

## Bug 26: `CROP_FORMAT_040['soybean']` had wrong param count (6 vs 15)

- **Date**: 2026-03-18
- **File**: `tools/s7_scenario_assembly/update_cultivar.py`
- **Symptom**: Would produce 6-param line for SBGRO040, but format requires 15 params (CSDL through PODUR).
- **Root cause**: Placeholder definition from initial implementation, never tested.
- **Fix**: Updated to param_count=15, correct format specifiers matching SBGRO040 column widths. Last 3 params of 048 (THRSH, SDPRO, SDLIP) correctly dropped as they live in ECO file for 040.
- **Validation**: Bengbu soybean CN0321 (SC MG V) → 1345 kg/ha mean (reasonable for uncalibrated).
- **Status**: Fixed

## Bug 27: rzwqm_file.py encoding mismatch — file bloats 3× per write cycle

- **Date**: 2026-03-19
- **File**: `lib/rzwqm_file.py` (13 write calls)
- **Symptom**: rzwqm.dat grows from 169KB to 518KB after one modify+write cycle. Special characters (box-drawing in separator lines) triple in size. Subsequent writes compound the bloat exponentially.
- **Root cause**: `dat_data` property reads with `encoding='ISO-8859-1'` (line 1610), but all write functions use `open(self.dat_path, 'w')` which defaults to UTF-8. ISO-8859-1 bytes get re-encoded as multi-byte UTF-8 sequences on each cycle.
- **Fix**: Changed all 13 `open(self.dat_path, 'w')` → `open(self.dat_path, 'w', encoding='ISO-8859-1')`.
- **Impact**: All previous calibration runs (50 runs in v3) were running on a progressively corrupted file. The RZWQM2 Fortran binary tolerated the bloat (ASCII data lines unaffected) but drainage and other mechanisms may have been silently broken by misaligned reads of bloated separator lines.
- **Status**: Fixed
