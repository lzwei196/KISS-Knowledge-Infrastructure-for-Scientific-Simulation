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

---

# RZWQM2 Knowledge Infrastructure

**A skill for autonomous operation of RZWQM2 (Root Zone Water Quality Model 2, USDA-ARS).**

Built using the Knowledge Dissection Toolkit v1.0. Developed by the Jianyun Zhang Research Group, Hohai University.

---

## Overview

You are operating RZWQM2, a process-based model for simulating water movement, nutrient transport, and crop growth in agricultural fields. This knowledge infrastructure gives you everything needed to set up, run, and diagnose RZWQM2 simulations autonomously.

The infrastructure has three layers plus a workflow document:

| Layer | Location | How to use it |
|-------|----------|---------------|
| **Workflow** | `workflow/workflow.md` | **Read first** — the end-to-end orchestration guide |
| **Validated tools** | `tools/` | **CALL** these scripts — NEVER write custom scripts that duplicate their function |
| **Skill documents** | `docs/` | **Read** and follow step-by-step |
| **Diagnostic triplets** | `diagnostics/triplets.yaml` | **Look up** errors by symptom (22 triplets) |
| **Error log** | `diagnostics/error_log.yaml` | **Append** new errors found during runs |

The pipeline definition and tool registry are in `knowledge_infrastructure.yaml`.

---

## Before You Begin

1. **Read `knowledge_infrastructure.yaml`** to understand the full pipeline: 12 stages, their dependencies, tools, milestones, and validation checks.
2. **Identify which stage(s) the user needs.** You do not always need to run the full pipeline. If the user already has met files, skip S2/S3. If they have a configured scenario, go straight to S8.
3. **Check the platform.** RZWQM2 runs as a Fortran binary: `RZWQMRelease.exe` on Windows, `main_ryzen` on Linux (x86-64 with AVX2). On Linux, you may need to patch the ELF interpreter (see dt_012).

---

## The Pipeline

Execute stages in order. Each stage has a skill document, validated tools, and milestones.

```
S0  Global Data Acquisition        (soil/forcing/crop from pluggable sources)
S1  Site/Grid Configuration        docs/s1_site_config_skill.md
S2  Meteorological Data Prep       docs/s2_met_prep_skill.md
S3  Breakpoint Rainfall            docs/s3_brk_generation_skill.md
S4  Soil Properties                docs/s4_soil_setup_skill.md
S5  Node Discretization            docs/s5_node_discretization_skill.md
S6  Initial Conditions             docs/s6_initial_conditions_skill.md
S7  Scenario Assembly              docs/s7_scenario_assembly_skill.md
S8  Model Execution                docs/s8_execution_skill.md
S9  Result Parsing                 docs/s9_result_parsing_skill.md
S10 Mass Project Generation        (CSV of sites → N complete scenarios)
```

**Dependencies:**
- S0 has no dependencies (data acquisition is the entry point)
- S3 depends on S2 (needs .met file)
- S4 depends on S1
- S5 depends on S4
- S6 depends on S4
- S7 depends on S2, S3, S4, S5, S6 (all inputs must exist)
- S8 depends on S7
- S9 depends on S8
- S10 depends on S0 (orchestrates S1-S7 for each site)

---

## How to Operate

### For each stage:

1. **Read the skill document** (`docs/sN_*_skill.md`). It contains the exact procedure, inputs, expected outputs, validation checks, and common pitfalls.
2. **Call the validated tools** listed for that stage. Tool scripts are in `tools/`. Each tool has defined inputs, preconditions, and postconditions — check them.
3. **Verify the milestone** before proceeding to the next stage. Milestones are defined in `knowledge_infrastructure.yaml` under each stage.

### When something fails:

1. **Match the symptom** against `diagnostics/triplets.yaml`. Each triplet has: symptom (what you observe), diagnosis (root cause), and remedy (exact fix).
2. **Check the failure domain** — the 22 triplets cover: path resolution, parameter format, unit conversion, runtime errors, silent errors, and environment issues.
3. **Silent errors are the most dangerous.** The model runs to completion but produces wrong results. Key silent errors:
   - dt_004: BRK precipitation in mm instead of inches (drainage 25x too high)
   - dt_008: Wrong soil texture from whitespace mismatch
   - dt_009: Lat/lon in degrees instead of radians (wrong ET and radiation)
   - dt_010: Tile drainage in cm not converted to mm (values 10x too low)

---

## Tools Reference

| Stage | Tool | Script | Purpose |
|-------|------|--------|---------|
| S0 | site_csv_validator | `tools/s0_global_data/site_csv_validator.py` | Validate input CSV of sites for mass generation |
| S0 | soil_source_adapter | `tools/s0_global_data/soil_source_adapter.py` | Retrieve soil from SoilGrids/gSSURGO/Canada/HWSD |
| S0 | forcing_source_adapter | `tools/s0_global_data/forcing_source_adapter.py` | Retrieve forcing from CMFD/MSWX/ERA5/CSV |
| S0 | crop_selector | `tools/s0_global_data/crop_selector.py` | Map crop names to DSSAT files (41 crops) |
| S0 | elevation_source_adapter | `tools/s0_global_data/elevation_source_adapter.py` | Retrieve elevation from CMFD/SRTM/manual |
| S1 | write_site_properties | `tools/s1_site_config/write_site_properties.py` | Write lat/lon/elevation/slope to RZWQM.dat |
| S2 | generate_met_file | `tools/s2_met_prep/generate_met_file.py` | Create .met file from CSV weather data |
| S2 | met_quality_check | `tools/s2_met_prep/met_quality_check.py` | Validate/fix Tmin>Tmax and RH bounds |
| S3 | create_breakpoint_file | `tools/s3_brk_generation/create_breakpoint_file.py` | Convert daily precip to .brk format (mm→inches) |
| S4 | soil_texture_classification | `tools/s4_soil_setup/soil_texture_classification.py` | USDA texture triangle classification |
| S4 | pedotransfer_hydraulic | `tools/s4_soil_setup/pedotransfer_hydraulic.py` | Estimate Brooks-Corey params from texture |
| S4 | write_soil_properties | `tools/s4_soil_setup/write_soil_properties.py` | Write all soil sections to RZWQM.dat atomically |
| S5 | generate_nodes | `tools/s5_node_discretization/generate_nodes.py` | Generate computational nodes via nlayer_gen |
| S6 | write_initial_conditions | `tools/s6_initial_conditions/write_initial_conditions.py` | Write water/temp/chemistry/nutrients to RZINIT.dat |
| S7 | initialize_scenario | `tools/s7_scenario_assembly/initialize_scenario.py` | Create scenario directory from template |
| S7 | update_ipnames_paths | `tools/s7_scenario_assembly/update_ipnames_paths.py` | Fix file paths in ipnames.dat |
| S7 | update_rzx_paths | `tools/s7_scenario_assembly/update_rzx_paths.py` | Fix DSSAT database paths in .RZX files |
| S7 | update_crop_selection | `tools/s7_scenario_assembly/update_crop_selection.py` | Update crop cultivar ID in rzwqm.dat + RZCropSel.rzq (defaults if empty) |
| S7 | update_cultivar | `tools/s7_scenario_assembly/update_cultivar.py` | Overwrite .CUL with China cultivar params (crop-aware: maize/wheat/soybean) |
| S8 | run_rzwqm2 | `tools/s8_execution/run_rzwqm2.py` | Execute RZWQM2 binary from scenario dir |
| S9 | parse_ana_output | `tools/s9_result_parsing/parse_ana_output.py` | Extract variables from .ana daily output |
| S9 | parse_layer_output | `tools/s9_result_parsing/parse_layer_output.py` | Extract depth-resolved data from Layer.plt |
| S10 | mass_project_generator | `tools/s10_mass_generation/mass_project_generator.py` | CSV of sites → N complete RZWQM2 scenarios |
| S10 | modify_soil_params | `tools/s10_calibration/modify_soil_params.py` | Modify 6 soil/drain params in rzwqm.dat (Ksat, ws, fc33, lateral_ksat, drain_spacing, field_sat) |
| S10 | parse_rzwqm2_output | `tools/s10_calibration/parse_rzwqm2_output.py` | Extract yield/SM/ET from .ana, compute NSE/RMSE/PBIAS vs observations |
| S10 | rzwqm2_calibrate | `tools/s10_calibration/rzwqm2_calibrate.py` | Automated calibration: LHS/Sobol + agent-guided batches (6 params, 10 runs/batch) |

**Rules for tools:**
- **ALWAYS use the validated tools** for every pipeline step. Do not write custom scripts that duplicate what a tool already does. Every tool has been tested end-to-end and handles unit conversions, edge cases, and silent error prevention.
- Call them with the documented inputs. Do not modify the scripts.
- Check preconditions before calling. Check postconditions after.
- If a tool exits with code 1 (input error), 2 (processing error), or 3 (output error), read the error message and consult the diagnostic triplets.
- **For batch/multi-site runs**: Call the tool in a loop, once per site. Do NOT write a custom batch script that reimplements the tool's logic.

---

## Critical Domain Knowledge

These are the non-obvious facts that cause silent failures if missed:

1. **Latitude and longitude must be in RADIANS**, not degrees. Convert: `rad = deg * pi / 180`.
2. **Breakpoint rainfall (.brk) uses INCHES.** The .met file uses mm. Divide by 25.4.
3. **Tile drainage in .ana output is in CENTIMETERS.** Multiply by 10 for mm.
4. **RZWQM.dat soil sections must all have the same horizon count.** Physical, hydraulic (3 lines per horizon), micropore, and macropore sections must be consistent.
5. **ipnames.dat is the master control file.** All 8 file paths (lines 0-7) must point to existing files. Line 8 has the simulation dates in `DD MM YYYY DD MM YYYY` format.
6. **On Linux, patch the binary interpreter:** `patchelf --set-interpreter /lib64/ld-linux-x86-64.so.2 main_ryzen`
7. **The binary needs AVX2.** It will not run on ARM (Apple Silicon via Rosetta) or older x86 CPUs without AVX2.
8. **RZWQM2 reads .CUL files from BOTH scenario root AND DSSAT/ subdirectory** — cultivar updates must target both locations (dt_022).
9. **Fortran fixed-width: ECO# must start at column 25 (1-indexed).** VRNAME field = 16 name + 1 space = 17 chars (dt_023).
10. **rzwqm_file.py encoding: reads ISO-8859-1, ALL writes must use encoding='ISO-8859-1'.** Default UTF-8 writes bloat file 3× per cycle (Bug 27).
11. **Tile drainage needs 5 params: drain flag + perched_WT=1 + bottom_BC=3(constant flux) + lateral_ksat>1.0 + geometry.** Just enabling the flag produces zero drainage.
12. **field_sat (field saturation fraction) controls constant-flux BC water influx.** 1.0=maximum, 0.80-0.85 typical for calibrated tile-drained clay.

---

## Global Data Sources (S0)

The S0 stage provides pluggable data retrieval for any location worldwide. Each adapter outputs a normalized format that the downstream pipeline consumes without knowing the data source.

### Soil Sources

| Source | Coverage | Data | How to use |
|--------|----------|------|------------|
| `soilgrids` | Global 250m | Sand/silt/clay, bulk density, SOC at 6 depths | No local data — calls ISRIC REST API |
| `gssurgo` | US (all states) | Full SSURGO soil profiles | Provide state code + geodatabase path |
| `canada_shapefile` | Canada | Soil layers from provincial shapefiles | Provide .shp/.dbf paths |
| `hwsd` | China (raster) | HWSD soil type + lookup table | Provide path to HWSD .img file |

### Forcing Sources

| Source | Coverage | Resolution | How to use |
|--------|----------|------------|------------|
| `cmfd` | China | 0.25°, 3-hourly | Provide path to CMFD NetCDF directory |
| `era5_api` | Global | 0.25°, hourly | Requires `cdsapi` package + CDS API key |
| `mswx` | Global | 0.1°, 3-hourly | Provide path to the MSWX store |
| `csv` | User-provided | Daily | Provide CSV with date,tmin,tmax,wind,radiation,epan,rh,par,rain |

### Crop Selection

The `crop_selector` maps common names to DSSAT file prefixes for 41 crops including maize, wheat, soybean, rice, barley, cotton, potato, alfalfa, and more. It can also map land-cover classes (AVHRR 1-15) to crop types.

---

## Mass Project Generation (S10)

Generate multiple RZWQM2 scenarios from a single CSV file.

### Input CSV Format

```csv
site_id,lat,lon,start_date,end_date,crop_name
site_001,40.5,-80.2,2011-01-01,2021-12-31,maize
site_002,32.1,114.6,2015-01-01,2020-12-31,wheat
site_003,50.7,-97.5,2011-01-01,2021-12-31,soybean
```

Optional columns: `elevation, slope, soil_source, forcing_source, soil_source_path, forcing_source_path, state_code, warmup_years`

### Usage

```
mass_project_generator.py <sites.csv> <project_path> <template_scenario> \
    [soil_source] [forcing_source] [forcing_path]
```

The generator clones the template scenario for each site, then runs the full pipeline (S1-S7): site config, met file, breakpoint rainfall, soil properties, node discretization, initial conditions, and path updates.

Soil and forcing always come straight from the source adapters (no VIC soil or VIC forcing files).

---

## Attribution

This knowledge infrastructure implements the knowledge dissection methodology described in:

> Zhang, J., et al. "Knowledge infrastructure enables autonomous AI operation of process-based Earth system models." Nature (under review).
