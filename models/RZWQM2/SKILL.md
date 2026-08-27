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
| to run the pipeline stages | `tools/` (38 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (10 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (29 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (18 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/s0_global_data/crop_selector.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_global_data/crop_selector.py --help` |
| `tools/s0_global_data/elevation_source_adapter.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_global_data/elevation_source_adapter.py --help` |
| `tools/s0_global_data/forcing_source_adapter.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_global_data/forcing_source_adapter.py --help` |
| `tools/s0_global_data/hwsd_soil_adapter.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_global_data/hwsd_soil_adapter.py --help` |
| `tools/s0_global_data/site_csv_validator.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_global_data/site_csv_validator.py --help` |
| `tools/s0_global_data/soil_source_adapter.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_global_data/soil_source_adapter.py --help` |
| `tools/s0_management_data/crop_area_lookup.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_management_data/crop_area_lookup.py --help` |
| `tools/s0_management_data/crop_calendar_lookup.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_management_data/crop_calendar_lookup.py --help` |
| `tools/s0_management_data/crop_name_harmonizer.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_management_data/crop_name_harmonizer.py --help` |
| `tools/s0_management_data/fertilizer_rate_lookup.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_management_data/fertilizer_rate_lookup.py --help` |
| `tools/s0_management_data/irrigation_type_lookup.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_management_data/irrigation_type_lookup.py --help` |
| `tools/s0_vic_coupling/vic_forcing_converter.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_vic_coupling/vic_forcing_converter.py --help` |
| `tools/s0_vic_coupling/vic_soil_converter.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s0_vic_coupling/vic_soil_converter.py --help` |
| `tools/s10_calibration/modify_soil_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s10_calibration/modify_soil_params.py --help` |
| `tools/s10_calibration/parse_rzwqm2_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s10_calibration/parse_rzwqm2_output.py --help` |
| `tools/s10_calibration/rzwqm2_calibrate.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s10_calibration/rzwqm2_calibrate.py --help` |
| `tools/s10_mass_generation/mass_project_generator.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s10_mass_generation/mass_project_generator.py --help` |
| `tools/s1_site_config/write_site_properties.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_site_config/write_site_properties.py --help` |
| `tools/s2_met_prep/generate_met_file.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_met_prep/generate_met_file.py --help` |
| `tools/s2_met_prep/met_quality_check.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_met_prep/met_quality_check.py --help` |
| `tools/s2_met_prep/power_cache_to_rzwqm2.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_met_prep/power_cache_to_rzwqm2.py --help` |
| `tools/s3_brk_generation/create_breakpoint_file.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_brk_generation/create_breakpoint_file.py --help` |
| `tools/s4_soil_setup/pedotransfer_hydraulic.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_soil_setup/pedotransfer_hydraulic.py --help` |
| `tools/s4_soil_setup/soil_texture_classification.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_soil_setup/soil_texture_classification.py --help` |
| `tools/s4_soil_setup/write_soil_properties.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_soil_setup/write_soil_properties.py --help` |
| `tools/s5_node_discretization/generate_nodes.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_node_discretization/generate_nodes.py --help` |
| `tools/s6_initial_conditions/write_initial_conditions.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_initial_conditions/write_initial_conditions.py --help` |
| `tools/s6_management_write/write_management_events.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_management_write/write_management_events.py --help` |
| `tools/s7_scenario_assembly/initialize_scenario.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_scenario_assembly/initialize_scenario.py --help` |
| `tools/s7_scenario_assembly/update_crop_selection.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_scenario_assembly/update_crop_selection.py --help` |
| `tools/s7_scenario_assembly/update_cultivar.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_scenario_assembly/update_cultivar.py --help` |
| `tools/s7_scenario_assembly/update_ipnames_paths.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_scenario_assembly/update_ipnames_paths.py --help` |
| `tools/s7_scenario_assembly/update_rzx_paths.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_scenario_assembly/update_rzx_paths.py --help` |
| `tools/s8_execution/run_rzwqm2.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s8_execution/run_rzwqm2.py --help` |
| `tools/s9_result_parsing/parse_ana_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9_result_parsing/parse_ana_output.py --help` |
| `tools/s9_result_parsing/parse_layer_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s9_result_parsing/parse_layer_output.py --help` |

*36 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

## ⚠️ Canonical Template — ALWAYS COPY FIRST

**RZWQM2 projects must ALWAYS be created by copying the canonical template, then updating parameters.**
Never attempt to generate RZWQM2 input files (rzwqm.dat, cntrl.dat, plgen.dat, etc.) from scratch —
the Fortran fixed-format files have dozens of interdependent sections that are impossible to
generate correctly without a validated starting point.

### Template location

```
KISSPATH_HOME/RZWQM2/RZWQM2/template_bengbu/
```

This is a clean, validated Bengbu wheat project with:
- All 8 required input files (cntrl.dat, rzwqm.dat, rzinit.dat, plgen.dat, .met, .brk, .sno, .ana path)
- DSSAT crop databases for maize, wheat, and soybean (.CUL, .ECO, .SPE + RZX files)
- Pre-patched Linux binary (`main_ryzen_patched`) with correct ELF interpreter
- Output files removed (clean state for new runs)

### How to create a new project

```bash
# 1. Copy the entire template
python tools/s7_scenario_assembly/initialize_scenario.py \
    /path/to/new_project  bengbu_wheat  <new_site_name> \
    <start_date>  <end_date>

# 2. Update site-specific parameters (S1-S6 tools):
#    - S1: lat/lon/elevation in rzwqm.dat
#    - S2: generate new .met file
#    - S3: generate new .brk file
#    - S4: update soil properties in rzwqm.dat
#    - S5: update node discretization
#    - S6: update initial conditions in rzinit.dat
#    - S7: update IPNAMES.DAT paths and crop selection

# 3. Run
python tools/s8_execution/run_rzwqm2.py  <scenario_dir>  <binary_path>
```

**For mass/batch runs**, use `tools/s10_mass_generation/mass_project_generator.py` which
automates this entire copy-then-update pipeline for a CSV of sites.

### Binary path

```
KISSPATH_HOME/RZWQM2/RZWQM2/linux/main_ryzen_patched
```

The binary is also copied into each scenario directory by the template. Either path works.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
RZWQM2 forcing tools in this KI:
- `tools/s0_global_data/forcing_source_adapter.py` — Multi-source forcing adapter (CMFD/MSWX/NASA POWER)
- `tools/s0_vic_coupling/vic_forcing_converter.py` — Converts VIC forcing to RZWQM2 met format
- `tools/s2_met_prep/generate_met_file.py` — Generates RZWQM2 .MET meteorological input file
- `tools/s2_met_prep/power_cache_to_rzwqm2.py` — Converts NASA POWER cache to RZWQM2 format
- `tools/s2_met_prep/met_quality_check.py` — QC validation of met data

### Soil properties

- `tools/s0_vic_coupling/vic_soil_converter.py` — Converts VIC soil parameters to RZWQM2 format

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.

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

## 6. Output Description

**Source of truth**: `dag.yaml`. The dag is the model identity for outputs; if this section ever disagrees with `dag.yaml`, the dag wins and this section is the bug.

**Headline output**: `crop_yield` — Crop grain yield from the embedded DSSAT crop module. (`kg/ha`)

| Output variable (dag `var`) | Unit | Description / status |
|-----------------------------|------|----------------------|
| `crop_yield` | `kg/ha` | Crop grain yield from the embedded DSSAT crop module. This is the dag's rank-1 variable and the headline variable this model is judged by. |
| `soil_water_storage` | See `dag.yaml` | Other dag output. |
| `tile_drainage` | See `dag.yaml` | Other dag output. |
| `evapotranspiration` | See `dag.yaml` | Other dag output. |
| `no3_leaching` | See `dag.yaml` | Other dag output. |
| `soil_nitrate` | See `dag.yaml` | Other dag output. |
| `soil_temperature` | See `dag.yaml` | Other dag output. |
| `snow_depth` | See `dag.yaml` | Other dag output. |
| `pesticide_loss` | See `dag.yaml` | Other dag output. |

## 8. Unit Conversion Table

**Source of truth**: the stage tools, `docs/format_spec.yaml`, and the unit traps recorded in this KI. Verify units before execution; these conversions prevent silent but scientifically invalid runs.

| Variable / file | Source unit | Model or analysis unit | Conversion |
|-----------------|-------------|------------------------|------------|
| `crop_yield` output | RZWQM2/DSSAT output | `kg/ha` | No conversion stated in extracted dag facts. |
| Latitude / longitude in `rzwqm.dat` | degrees | radians | `rad = deg * pi / 180` |
| Breakpoint rainfall `.brk` | `.met` precipitation in `mm` | inches | divide by `25.4` |
| Tile drainage in `.ana` | `cm` | `mm` for post-processing | multiply by `10` |
| VIC `ksat` columns 12-14 | `mm/day` | `cm/hr` | divide by `240` |
| VIC `expt` columns 9-11 | dimensionless | pore-size distribution | `2 / expt` |
| VIC `bulk_density` columns 33-35 | `kg/m3` | porosity `cm3/cm3` | `1 - bd/2650` |
| VIC `Wcr_FRACT` columns 40-42 | fraction | `fc33` volumetric | `Wcr * ws` |
| VIC `Wpwp_FRACT` columns 43-45 | fraction | `fc15` volumetric | `Wpwp * ws` |
| VIC layer depth columns 22-24 | `m` | `cm` | multiply by `100` |
| VIC forcing temperature | `K` | `C` | subtract `273.15` |
| VIC forcing radiation | `W/m2` | `MJ/m2/day` | multiply by `0.0864` |
| VIC forcing wind | `m/s` | `km/day` | multiply by `86.4` |
| VIC forcing E-pan | estimated ET0 | E-pan estimate | `0.7 * Hargreaves ET0` |
| VIC forcing PAR | shortwave radiation | PAR estimate | `0.48 * shortwave radiation` |

## 11. Validated Results

**Source of truth**: `docs/validation_convention.yaml`. A metric value without the field's pass-band is not a verdict. The convention wins over remembered thresholds.

The dag's rank-1 output is `crop_yield`. No convention bar for `crop_yield` is stated in the extracted convention facts supplied for this upgrade, so do not substitute crop-yield thresholds from memory.

### Performance Metrics -- judged against the field's bar

| Dag variable | Metric | Direction | Convention bar, cited |
|--------------|--------|-----------|------------------------|
| `soil_water_storage` | `r2` | maximize | very_good `0.8` (`ma2012`, `cheng2022`, `craft2018`); good `0.7` (`ma2012`, `cheng2022`, `craft2018`); satisfactory `0.5` (`ma2012`, `cheng2022`, `craft2018`) |
| `soil_water_storage` | `pbias` | zero_centered | very_good `6.0` (`ma2012`, `cheng2022`); good `15.0` (`ma2012`, `cheng2022`); satisfactory `15.0` (`ma2012`, `cheng2022`) |
| `tile_drainage` | `nse` | maximize | very_good `0.75` (`craft2018`); good `0.65` (`craft2018`); satisfactory `0.5` (`craft2018`) |
| `tile_drainage` | `pbias` | zero_centered | very_good `10.0` (`craft2018`); good `15.0` (`craft2018`); satisfactory `25.0` (`craft2018`) |
| `evapotranspiration` | `nrmse` | minimize | very_good `10.0` (`umair2017`); good `20.0` (`umair2017`); satisfactory `30.0` (`umair2017`) |
| `evapotranspiration` | `ioa` | maximize | very_good no cited threshold (`cheng2022`); good `0.7` (`cheng2022`); satisfactory `0.7` (`cheng2022`) |

No achieved calibration, validation, or full-period metric values are stated in these extracted KI facts. When a run is evaluated, compute metrics with the validated parsing/calibration tools and compare them to the cited convention bars above.

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
S0  VIC-RZWQM2 Coupling           (optional: convert VIC params to RZWQM2)
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
| S0 | soil_source_adapter | `tools/s0_global_data/soil_source_adapter.py` | Retrieve soil from VIC/SoilGrids/gSSURGO/HWSD |
| S0 | forcing_source_adapter | `tools/s0_global_data/forcing_source_adapter.py` | Retrieve forcing from CMFD/ERA5/VIC/CSV |
| S0 | crop_selector | `tools/s0_global_data/crop_selector.py` | Map crop names to DSSAT files (41 crops) |
| S0 | elevation_source_adapter | `tools/s0_global_data/elevation_source_adapter.py` | Retrieve elevation from CMFD/SRTM/manual |
| S0 | vic_soil_converter | `tools/s0_vic_coupling/vic_soil_converter.py` | Convert VIC soil params to RZWQM2 format |
| S0 | vic_forcing_converter | `tools/s0_vic_coupling/vic_forcing_converter.py` | Convert VIC forcing to RZWQM2 met CSV |
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
| `vic_global` | Global 0.25° | VIC 53-col params (ksat, expt, bulk_density, Wcr, Wpwp) | Provide path to `global_soil_param_new.txt` |
| `soilgrids` | Global 250m | Sand/silt/clay, bulk density, SOC at 6 depths | No local data — calls ISRIC REST API |
| `gssurgo` | US (all states) | Full SSURGO soil profiles | Provide state code + geodatabase path |
| `canada_shapefile` | Canada | Soil layers from provincial shapefiles | Provide .shp/.dbf paths |
| `hwsd` | China (raster) | HWSD soil type + lookup table | Provide path to HWSD .img file |

### Forcing Sources

| Source | Coverage | Resolution | How to use |
|--------|----------|------------|------------|
| `cmfd` | China | 0.25°, 3-hourly | Provide path to CMFD NetCDF directory |
| `era5_api` | Global | 0.25°, hourly | Requires `cdsapi` package + CDS API key |
| `vic_forcing` | Basin-specific | Grid-cell text files | Provide path to VIC forcing directory |
| `csv` | User-provided | Daily | Provide CSV with date,tmin,tmax,wind,radiation,epan,rh,par,rain |

### Crop Selection

The `crop_selector` maps common names to DSSAT file prefixes for 41 crops including maize, wheat, soybean, rice, barley, cotton, potato, alfalfa, and more. It can also map VIC AVHRR vegetation classes (1-15) to appropriate crop types.

**crop_ref mapping**: In RZCropSel.rzq, maize=1, soybean=2, wheat=3. When calling write_management_events, set crop_ref to match the desired crop (default is 1=maize).

---

## VIC-RZWQM2 Coupling (S0)

When working with HydroCraft (VIC-routing), use the coupling tools to bridge VIC and RZWQM2 parameter spaces.

### Soil Parameter Bridge

The `vic_soil_converter` reads VIC's 53-column soil parameter file and converts to RZWQM2 format:

| VIC Parameter | VIC Unit | RZWQM2 Parameter | RZWQM2 Unit | Conversion |
|---------------|----------|-------------------|-------------|------------|
| ksat (cols 12-14) | mm/day | ksat | cm/hr | divide by 240 |
| expt (cols 9-11) | dimensionless | pore_size_dist | dimensionless | 2 / expt |
| bulk_density (cols 33-35) | kg/m3 | ws (porosity) | cm3/cm3 | 1 - bd/2650 |
| Wcr_FRACT (cols 40-42) | fraction | fc33 | volumetric | Wcr * ws |
| Wpwp_FRACT (cols 43-45) | fraction | fc15 | volumetric | Wpwp * ws |
| depth (cols 22-24) | m | depth | cm | multiply by 100 |

Missing parameters (bubbling_pressure, wr, N2, C2) are derived via RZWQM2 pedotransfer functions.

### Forcing Bridge

The `vic_forcing_converter` converts VIC forcing files (text or CMFD NetCDF) to RZWQM2 daily format:
- Temperature: K → C (subtract 273.15), split into Tmin/Tmax
- Radiation: W/m2 → MJ/m2/day (multiply by 0.0864)
- Wind: m/s → km/day (multiply by 86.4)
- Humidity: specific humidity → RH% (via saturation vapor pressure)
- E-pan: estimated as 0.7 * Hargreaves ET0
- PAR: estimated as 0.48 * shortwave radiation

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

Optional columns: `elevation, slope, soil_source, forcing_source, soil_source_path, forcing_source_path, state_code, vic_grid_id`

### Usage

```
mass_project_generator.py <sites.csv> <project_path> <template_scenario> \
    [soil_source] [forcing_source] [soil_path] [forcing_path] [dssat_path] [vic_mode]
```

The generator clones the template scenario for each site, then runs the full pipeline (S1-S7): site config, met file, breakpoint rainfall, soil properties, node discretization, initial conditions, and path updates.

VIC coupling mode options:
- `none` — use soil/forcing adapters directly
- `soil_only` — soil from VIC params, forcing from adapter
- `forcing_only` — soil from adapter, forcing from VIC
- `full` — both soil and forcing from VIC

---

## Attribution

This knowledge infrastructure implements the knowledge dissection methodology described in:

> Zhang, J., et al. "Knowledge infrastructure enables autonomous AI operation of process-based Earth system models." Nature (under review).

---

## Crop Calendar Reference (China)

| Region | Latitude | Winter Wheat | Summer Maize | Rice |
|--------|----------|-------------|-------------|------|
| Northeast | >40°N | — | May-Sep | — |
| North China | 35-40°N | Oct-Jun | Jun-Sep | — |
| Huang-Huai | 32-35°N | Oct-Jun | Jun-Oct | — |
| Yangtze | 28-32°N | Nov-May | — | Apr-Oct |
| South | <28°N | — | — | Mar-Jul, Jul-Nov |

**Data sources on server:**
- GGCMI Crop Calendar: `KISSPATH_HOME/Crop_model_dataset/GGCMI_phase3_crop_calendar/`
- China Phenology GeoTIFF: `KISSPATH_HOME/Crop_model_dataset/8313530/`
- SPAM crop distribution: `KISSPATH_HOME/Crop_model_dataset/dataverse_files/`
