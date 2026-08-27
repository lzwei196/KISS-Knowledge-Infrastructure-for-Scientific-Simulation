> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.md` for a matching error pattern
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
> 1. **Check triplets** — `diagnostics/triplets.md` may already cover this error
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
| to run the pipeline stages | `tools/` (11 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (31 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (27 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-26 from the KI's actual contents — 8 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `s1_grid/make_basin_grid_nc.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s1_grid/make_basin_grid_nc.py --help` |
| `s2_forcing/fix_lwd_1979.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s2_forcing/fix_lwd_1979.py --help` |
| `s2_forcing/forcing_1d.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s2_forcing/forcing_1d.py --help` |
| `s2_forcing/forcing_nasa_power.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s2_forcing/forcing_nasa_power.py --help` |
| `s2_forcing/nasa_power_batch_cache.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s2_forcing/nasa_power_batch_cache.py --help` |
| `s2_forcing/process_forcing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s2_forcing/process_forcing.py --help` |
| `s2_forcing/rechunk_mswx.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s2_forcing/rechunk_mswx.py --help` |
| `s3_soil/fill_parameters1.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s3_soil/fill_parameters1.py --help` |
| `s3_soil/fill_parameters2.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s3_soil/fill_parameters2.py --help` |
| `s4_veg/process_vegetation_detailed.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s4_veg/process_vegetation_detailed.py --help` |
| `s5_routing/build_routing_param.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s5_routing/build_routing_param.py --help` |
| `s5_routing/delineate_bengbu.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s5_routing/delineate_bengbu.py --help` |
| `s5_routing/run_routing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s5_routing/run_routing.py --help` |
| `s6_post/compare_runoff_field.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s6_post/compare_runoff_field.py --help` |
| `s6_post/grid_runoff_nc.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/s6_post/grid_runoff_nc.py --help` |
| `tools/calib_run.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help` |
| `tools/calib_run_wangjiaba.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run_wangjiaba.py --help` |
| `tools/calib_run_wjb_flatrain.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run_wjb_flatrain.py --help` |
| `tools/calibration/run_bengbu_ai_batch10.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calibration/run_bengbu_ai_batch10.py --help` |
| `tools/calibration/run_bengbu_ai_calibration.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calibration/run_bengbu_ai_calibration.py --help` |
| `tools/check_data.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/check_data.py --help` |
| `tools/config_paths.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/config_paths.py --help` |
| `tools/plot/plot_calibration_convergence.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/plot/plot_calibration_convergence.py --help` |
| `tools/plot/plot_calibration_validation_comparison.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/plot/plot_calibration_validation_comparison.py --help` |
| `tools/plot/plot_discharge_comparison.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/plot/plot_discharge_comparison.py --help` |
| `tools/run_vic_pipeline_enhanced.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_vic_pipeline_enhanced.py --help` |

*26 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | Variable Infiltration Capacity model |
| Version | VIC-5.1.0 classic driver |
| Language | C |
| License | MIT |
| Repository | https://github.com/UW-Hydro/VIC |
| Citation | VIC-5 (Hamman et al. 2018, GMD; original Liang et al. 1994 JGR formulation) |
| Primary domain | Hydrology / land-surface water and energy balance |
| Spatial mode | 2-D distributed grid, per-cell classic forcing and flux output |

---

## 2. What This Model Does

VIC simulates gridded land-surface water balance and, when configured, energy,
snow, frozen-soil, lake/wetland, and carbon processes. The classic driver emits
per-cell flux/state outputs; basin gauge discharge requires post-hoc routing of
`OUT_RUNOFF + OUT_BASEFLOW` unless the optional lake module is the source of
`OUT_DISCHARGE`.

---

## 3. Input Requirements

Exact shapes live in `docs/format_spec.yaml`, projected from `dag.yaml` and
`diagnostics/triplets.yaml`. Treat that file as the contract for I/O shape,
units, and known traps; regenerate it after dag or triplet changes instead of
hand-editing.

### 3.1 Meteorological Forcing

| Variable | Unit model expects | Source dataset | Source unit | Conversion |
|----------|-------------------|----------------|-------------|------------|
| `PREC` | `mm per forcing step` | CMFD/MSWX/NASA POWER via KI forcing tools | `kg m-2 s-1` for CMFD | `x10800` for 3-hourly forcing; `x86400` for daily totals |
| `AIR_TEMP` | `degC` | CMFD/MSWX/NASA POWER via KI forcing tools | `K` for CMFD | `-273.15` |
| `PRESSURE` | `kPa` | CMFD/MSWX/NASA POWER via KI forcing tools | `Pa` for CMFD | `/1000` |
| `VP` | `kPa` | Derived by KI forcing tools | derived from `shum` + `pres` | derive before writing VIC ASCII forcing |
| `SWDOWN` | `W/m^2` | CMFD/MSWX/NASA POWER via KI forcing tools | `W/m^2` | `x1` |
| `LWDOWN` | `W/m^2` | CMFD/MSWX/NASA POWER via KI forcing tools | `W/m^2` | `x1` |
| `WIND` | `m/s` | CMFD/MSWX/NASA POWER via KI forcing tools | `m/s` | `x1` |

### 3.2 Static Inputs

| Input | Source | Tool that prepares it |
|-------|--------|----------------------|
| Basin grid | Basin shapefile | `s1_grid/make_basin_grid_nc.py` |
| Soil properties | HWSD lookup through `ki_tools_common.soil_utils.lookup_hwsd` | `s3_soil/fill_parameters1.py`, `s3_soil/fill_parameters2.py` |
| Vegetation parameters | KI vegetation processing inputs | `s4_veg/process_vegetation_detailed.py` |
| DEM / routing rasters | DEM plus native-resolution delineation outputs | `ki_tools_common.terrain_ops.delineate_basin`, `s5_routing/build_routing_param.py` |
| Routing parameters | Native-resolution `flow_accum.tif`, `basin.tif`, `dem_filled.tif` | `s5_routing/build_routing_param.py` |

### 3.3 Configuration Files

| File | Format | Notes |
|------|--------|-------|
| Global parameter file | VIC classic text config | Generated by `config_paths.create_global_param()` from `docs/vic_param/global_param_template.txt`; `OUTVAR` order is routing-critical. |
| Soil parameter file | VIC classic ASCII row format | `SOIL_PARAM_COMPLETE.txt` must exist before forcing processing. |
| Vegetation parameter file | VIC classic ASCII format | Produced per basin by the vegetation stage. |
| Routing global file | Lohmann `route_1.0` text config | Produced under `routing_param/`; run through `s5_routing/run_routing.py`. |

---

## 4. Build Instructions

Run the preflight before any execution:

```bash
python preflight_check.py
```

The preflight verifies that the VIC classic binary/package, routing binary, and
required KI data are available. If a model import, compile, or execution step
fails, follow the mandatory execution policy at the top of this file.

---

## 5. Execution

Use the server quickstart and full chain below. In short:

```bash
python preflight_check.py
# export VIC_BASIN_NAME, VIC_BASIN_SHP, VIC_CMFD_DIR, VIC_YEAR_START,
# VIC_YEAR_END, VIC_START_DATE, VIC_END_DATE, VIC_FORCING_PREFIX, and routing vars
# then run s1 through s10 in order.
```

Expected runtime depends on basin size and period. The Harbin reference noted
below used 866 cells; water-balance mode costs about 95 s per simulated year for
that case.

---

## 6. Output Description

Source: `dag.yaml`. If this section and `dag.yaml` ever disagree, `dag.yaml`
wins.

Headline output:

> `OUT_DISCHARGE` -- Routed discharge value emitted only by the lake module; for non-lake cells streamflow is not produced internally. (`m^3/s`)

Other dag outputs:
`OUT_RUNOFF`, `OUT_BASEFLOW`, `OUT_EVAP`, `OUT_SOIL_MOIST`, `OUT_SWE`,
`OUT_SNOW_MELT`, `OUT_SOIL_TEMP`, `OUT_LATENT`, `OUT_SENSIBLE`, `OUT_R_NET`,
`OUT_ALBEDO`, `OUT_ZWT`, `OUT_GPP`, `OUT_LAKE_VOLUME`.

| Output variable (dag `var`) | Rank | Unit | Emitted in | Description |
|-----------------------------|------|------|------------|-------------|
| `OUT_DISCHARGE` | 1 | `m^3/s` | per-cell ASCII flux file | Routed discharge value emitted only by the lake module; for non-lake cells streamflow is not produced internally. |
| `OUT_RUNOFF` | 2 | `mm` | per-cell ASCII flux file; column controlled by `OUTVAR` | Surface runoff generated by the variable infiltration capacity partition (per timestep total). |
| `OUT_BASEFLOW` | 6 | `mm` | per-cell ASCII flux file | Subsurface drainage from the bottom soil layer via the ARNO / non-linear baseflow function. |
| `OUT_EVAP` | 3 | `mm` | per-cell ASCII flux file | Total evapotranspiration (canopy interception + transpiration + bare soil + sublimation, per timestep). |
| `OUT_SOIL_MOIST` | 7 | `mm` | per-cell ASCII flux file, one column per soil layer | Per-layer soil moisture (liquid + ice) integrated over the layer. |
| `OUT_SWE` | 4 | `mm` | per-cell ASCII flux file | Total snow water equivalent of the ground snowpack. |
| `OUT_SNOW_MELT` | 8 | `mm` | per-cell ASCII flux file | Snowmelt flux from the ground snowpack. |
| `OUT_SOIL_TEMP` | 9 | `degC` | per-cell ASCII flux file | Soil temperature per layer (and `OUT_SOIL_TNODE` per thermal node). |
| `OUT_LATENT` | 10 | `W/m^2` | per-cell ASCII flux file, full-energy mode | Surface latent heat flux. |
| `OUT_SENSIBLE` | 11 | `W/m^2` | per-cell ASCII flux file, full-energy mode | Surface sensible heat flux. |
| `OUT_R_NET` | 12 | `W/m^2` | per-cell ASCII flux file | Net all-wave radiation at the surface. |
| `OUT_ALBEDO` | 13 | `fraction` | per-cell ASCII flux file | Surface broadband albedo (snow + canopy + bare soil composite). |
| `OUT_ZWT` | 5 | `cm` | per-cell ASCII flux file | Water table depth below the surface. |
| `OUT_GPP` | 14 | `g C/m^2/day` | per-cell ASCII flux file, CARBON mode | Vegetation gross primary production from the optional CARBON module. |
| `OUT_LAKE_VOLUME` | 15 | `m^3` | per-cell ASCII flux file, LAKES mode | Composite within-cell lake volume (LAKES mode). |

---

## 7. Tool Inventory

| Tool | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `preflight_check.py` | Verify model environment and required data | KI directory | `PREFLIGHT_REPORT=` line |
| `s1_grid/make_basin_grid_nc.py` | Build basin VIC grid | Basin shapefile | `grid_<basin>_025deg.nc` |
| `s3_soil/fill_parameters1.py` | Build soil-parameter frame | Grid and soil sources | `SOIL_PARAM_FINAL.txt` |
| `s3_soil/fill_parameters2.py` | Fill soil parameters | Soil frame and lookup data | `SOIL_PARAM_COMPLETE.txt` |
| `s4_veg/process_vegetation_detailed.py` | Build vegetation parameters | Grid and vegetation sources | `vic_veg_param_final.txt` |
| `s2_forcing/forcing_1d.py` | Clip gridded forcing | CMFD/MSWX/NASA POWER sources and grid | per-month basin NetCDF files |
| `s2_forcing/process_forcing.py` | Write VIC forcing ASCII | Basin NetCDF forcing and soil coordinates | per-cell 7-column forcing files |
| `config_paths.create_global_param()` | Generate global parameter file | Template and environment | `global_param_<basin>.txt` |
| `model/VIC-5.1.0/.../vic_classic.exe` | Run VIC classic | Global parameter file and model-ready inputs | per-cell flux files |
| `s5_routing/build_routing_param.py` | Build Lohmann routing params | Native DEM/delineation rasters and outlet | `direc`, `frac`, `xmask`, `staloc`, `UH.all` |
| `s5_routing/run_routing.py` | Run Lohmann routing wrapper | Routing params and flux files | daily gauge discharge in `m3/s` |

Shared utilities are listed in the KI map. Prefer `ki_tools_common.load_forcing`,
`ki_tools_common.soil_utils`, `ki_tools_common.metrics`, and
`ki_tools_common.validation` over ad-hoc readers.

---

## 8. Unit Conversion Table

This unit table records the pipeline conversions called out by the KI body,
`docs/format_spec.yaml`, and `dag.yaml`.

| Variable | Source unit (verified) | Model / output unit | Factor | Type |
|----------|------------------------|---------------------|--------|------|
| CMFD `prec` -> VIC `PREC` | `kg m-2 s-1` | `mm per forcing step` | `x10800` for 3-hourly forcing | multiplicative |
| CMFD `prec` daily total | `kg m-2 s-1` | `mm/day` | `x86400` | multiplicative |
| CMFD `temp` -> VIC `AIR_TEMP` | `K` | `degC` | `-273.15` | additive |
| CMFD `pres` -> VIC `PRESSURE` | `Pa` | `kPa` | `/1000` | multiplicative |
| CMFD `shum` + `pres` -> VIC `VP` | specific humidity plus pressure | `kPa` | derive vapor pressure before writing forcing | derived |
| Radiation (`SWDOWN`, `LWDOWN`) | `W/m^2` | `W/m^2` | `x1` | identity |
| Wind (`WIND`) | `m/s` | `m/s` | `x1` | identity |
| `OUT_RUNOFF` | VIC output | `mm` | no conversion for per-cell flux files | identity |
| `OUT_BASEFLOW` | VIC output | `mm` | no conversion for per-cell flux files | identity |
| externally routed gauge streamflow | routed `OUT_RUNOFF + OUT_BASEFLOW` | `m^3/s` | handled by `route_1.0` | routing conversion |
| `OUT_DISCHARGE` | VIC output | `m^3/s` | emitted only by optional lake module | identity when present |
| `OUT_EVAP` | VIC output | `mm` | convert separately before comparing to `W/m^2` latent heat | comparison conversion |
| `OUT_LATENT`, `OUT_SENSIBLE`, `OUT_R_NET` | VIC output | `W/m^2` | no conversion for flux output | identity |
| `OUT_SOIL_TEMP` | VIC output | `degC` | no conversion for flux output | identity |
| `OUT_ALBEDO` | VIC output | `fraction` | no conversion for flux output | identity |
| `OUT_ZWT` | VIC output | `cm` | no conversion for flux output | identity |
| `OUT_GPP` | VIC output | `g C/m^2/day` | no conversion for CARBON output | identity |
| `OUT_LAKE_VOLUME` | VIC output | `m^3` | no conversion for LAKES output | identity |

### 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| `OUT_RUNOFF` | positive water leaving the cell surface store, `mm` per cell | treating as gauge `m^3/s` | hydrograph timing and magnitude become invalid without routing |
| `OUT_BASEFLOW` | positive subsurface drainage from bottom soil layer, `mm` per cell | treating as directly observed baseflow | gauge comparison lacks routing and hydrograph separation uncertainty |
| `OUT_DISCHARGE` | `m^3/s`, lake-module routed discharge only | assuming normal non-lake streamflow output | false claim that VIC internally routes river discharge |
| `OUT_EVAP` | positive evapotranspiration total, `mm` | latent heat in `W/m^2` | ET comparisons need unit conversion and closure handling |
| `OUT_LATENT` | surface latent heat flux, `W/m^2` | ET depth unit | wrong magnitude if mixed with `OUT_EVAP` |

---

## 9. Diagnostic Triplets (Top 5)

The full corpus is `diagnostics/triplets.yaml`; check it before debugging.

| # | Error | Diagnosis | Remedy |
|---|-------|-----------|--------|
| 1 | `dt_vic_019`: gauge discharge needed but flux files contain only `OUT_RUNOFF` / `OUT_BASEFLOW`; `OUT_DISCHARGE` is zero or absent | VIC has no internal routing for basin-scale gauge discharge; `OUT_DISCHARGE` is lake-module only | Run Lohmann `route_1.0` through `s5_routing/run_routing.py` after preprocessing fluxes |
| 2 | `dt_vic_020`: routing grid reports nonsensical outlet/connectivity | flow direction grid was built from a coarsened DEM instead of native delineation rasters | Use native `flow_accum.tif`, `basin.tif`, and `dem_filled.tif` through `s5_routing/build_routing_param.py` |
| 3 | `dt_vic_021`: cal/val metrics are NaN or use too few days | observation record has `-99` gaps and the standard split is not fully observed | Profile valid years first and choose a contiguous observed window |
| 4 | `dt_vic_028`: routing travel time is too short even with a correct grid | default velocity can make hydrographs peak too early; routing velocity changes timing, not volume bias | Compare observed lag to `basin_mean_uh_lag`, bisect velocity on calibration timing only, and report unreachable plateaus |
| 5 | `dt_vic_030`: calibration/validation gap looks like overfitting | soil column has not spun up; baseflow/storage trend across the scoring window | inspect 31-Dec storage and annual baseflow; start simulation earlier if still trending |

---

## 10. Coupling Interfaces

| Upstream model/data | Variable exchanged | Unit | Temporal resolution |
|---------------------|-------------------|------|---------------------|
| CMFD/MSWX/NASA POWER forcing | precipitation, temperature, pressure, humidity-derived vapor pressure, radiation, wind | see Section 8 | 3-hourly or daily depending on source and processing |
| HWSD soil lookup | soil hydraulic and thermal parameters | varies | static |
| DEM / terrain preprocessing | basin mask, flow accumulation, filled DEM | raster-native units | static |

| Downstream model/tool | Variable exchanged | Unit | Temporal resolution |
|-----------------------|-------------------|------|---------------------|
| Lohmann `route_1.0` | `OUT_RUNOFF + OUT_BASEFLOW` with `prec` and `evap` columns | VIC flux input in `mm`; routed output in `m^3/s` | daily routing output |
| CaMa-Flood input preparation | gridded runoff aggregate | `mm/day` | daily |
| Validation metrics | routed streamflow, ET, SWE, soil moisture, energy fluxes | variable-specific | daily or observation-native |

---

## 11. Validated Results

Source: `docs/validation_convention.yaml` and the reference-run notes already
present in this KI body. This section states the field bars and does not invent
new achieved scores.

### Reference Basins Recorded In This KI

| Basin | Cells | Period | Routed daily result note |
|-------|-------|--------|--------------------------|
| Bengbu 51080 (Huai, lowland, regulated) | 224 | 1981-90 | routed daily NSE ~0.15; PBIAS +44% |
| Tangnaihai (upper Yellow, alpine) | 251 | cal 2007-11 / val 2012-16 | see `detached/real_case/result.json` |
| Harbin (Songhua, cold/snowmelt) | 866 | cal 1981-85 / val 1986-87 | see `detached/real_case/result.json`; held-out NSE plateau 0.488-0.521 across routing velocity plateau |

### Performance Metrics -- judged against the field's bar, not intuition

| Dag variable | Metric | Direction | Convention bar with citation keys |
|--------------|--------|-----------|-----------------------------------|
| `OUT_DISCHARGE` | `nse` | maximize | very_good >= 0.75 (`moriasi2007`, `moriasi2015`); good >= 0.65 (`moriasi2007`, `moriasi2015`); satisfactory >= 0.5 (`moriasi2007`, `moriasi2015`) |
| `OUT_DISCHARGE` | `pbias` | zero_centered | very_good <= 10 (`moriasi2015`, `moriasi2007`); good <= 15 (`moriasi2015`, `moriasi2007`); satisfactory <= 15 (`moriasi2015`, `moriasi2007`) |
| `OUT_RUNOFF` | `nse` | maximize | very_good >= 0.75 (`moriasi2007`, `moriasi2015`); good >= 0.65 (`moriasi2007`, `moriasi2015`); satisfactory >= 0.5 (`moriasi2007`, `moriasi2015`) |
| `OUT_RUNOFF` | `pbias` | zero_centered | very_good <= 10 (`moriasi2015`, `moriasi2007`); good <= 15 (`moriasi2015`, `moriasi2007`); satisfactory <= 15 (`moriasi2015`, `moriasi2007`) |
| `OUT_EVAP` | `nse` | maximize | good >= 0.6 (`ershadi2013`); satisfactory >= 0.5 (`ershadi2013`); very_good: no cited threshold |

For `pbias`, the zero-centered bars are absolute percent thresholds around
zero. A metric without a cited convention band must be reported as "no cited
threshold"; do not substitute a remembered threshold.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | KI forcing pipeline | Pending per new basin | Validate units with `validators/preflight_forcing.py`. |
| Soil | KI soil pipeline | Pending per new basin | Soil must precede forcing because forcing reads grid coordinates from `SOIL_PARAM_COMPLETE.txt`. |
| Land cover / vegetation | KI vegetation pipeline | Pending per new basin | Root fractions may trigger a benign normalization warning. |
| DEM / routing | Native DEM and KI routing tools | Pending per new basin | Validate max accumulation, outlet cell, and connectivity before scoring. |
| Initial conditions | Soil file/state setup | Pending per new basin | Check spin-up before trusting cal/val gaps. |

---

## 12. Parameter Selection by Region

Use physically informed starting points when no site-specific calibration exists.
Routing velocity is an effective basin residence-time parameter in large flat or
regulated basins; identify it from observed lag on the calibration window only,
not from NSE. For snow-dominated basins, use the frozen-soil-capable template
`docs/vic_param/global_param_template_frozen.txt` only when the required soil
fields and node settings are valid.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
VIC forcing tools are in `s2_forcing/` in this KI:
- `s2_forcing/forcing_1d.py` — Consolidates regional CMFD/MSWX into 1D NetCDF per variable
- `s2_forcing/process_forcing.py` — Generates per-cell VIC ASCII forcing (3-hourly, 7 columns)
- `s2_forcing/forcing_nasa_power.py` — NASA POWER API fallback for non-CMFD/MSWX regions

### Soil properties

**Data Sources**: Use `from ki_tools_common.soil_utils import lookup_hwsd` for soil properties.

**Data Validation Reference**: CMFD units and traps — `data_ki/dataset_index.yaml` +
`data_ki/kdt_dataset_layouts.yaml`. (The old `data_ki/CMFD/SKILL.md` and
`data_ki/HWSD/SKILL.md` paths were removed in KDT 5.0; soil/forcing helpers now
live in `ki_tools_common.soil_utils` / `ki_tools_common.load_forcing`.)

Key CMFD unit facts for this KI: `prec` is `kg m-2 s-1` → ×10800 for mm/3hr
(×86400 for mm/day); `temp` is K; `pres` is Pa → /1000 for kPa;
vapour pressure is derived from `shum` + `pres`. `process_forcing.py` already
does all of this — verify with `validators/preflight_forcing.py` before running.

---

## ⚡ Server quickstart (2026-07-09) — READ THIS BEFORE THE CHINESE SECTIONS BELOW

The Chinese walkthrough further down is the original macOS authoring notes. Its
`/Users/yc/...` and `/Volumes/Expansion2t/...` paths are DEAD, and its advice to
"edit the variables at the top of each script" has been superseded.

**Every stage script now reads its configuration from environment variables**
(defaults reproduce the old hard-coded behaviour). Set these once, then run the
stages unmodified — no in-place editing, no `config_paths.py` regex rewriting:

| variable | meaning |
|---|---|
| `VIC_BASIN_NAME` | basin tag; drives `outputs/<name>/…` and all filenames |
| `VIC_BASIN_SHP` | basin boundary shapefile |
| `VIC_OUT_ROOT` | default `KISSPATH_OUTPUTS` |
| `VIC_CMFD_DIR` | forcing root, e.g. `data/forcing/Data_forcing_03hr_010deg` |
| `VIC_YEAR_START`, `VIC_YEAR_END` | forcing + simulation years (one place, not three) |
| `VIC_START_DATE`, `VIC_END_DATE` | `process_forcing.py` slice |
| `VIC_FORCING_PREFIX` | must equal the `FORCING1` prefix, e.g. `tangnaihai_025deg_` |
| `VIC_GLOBAL_PARAM_TEMPLATE` | global param to clone; defaults to the KI-shipped `docs/vic_param/global_param_template.txt` (dt_vic_024) |
| `VIC_STATION_NAME` | routing station tag, e.g. `HRB`; names `<STA>_direc.txt` etc. |
| `VIC_OUTLET_LON`, `VIC_OUTLET_LAT` | gauge coords — **required** for a new basin (s9 pour point + max-accum assertion) |
| `VIC_DEM` | DEM for delineation, e.g. `data/dem/china_dem_90m/china_dem_90m.tif` |
| `VIC_STREAM_THRESHOLD` | stream threshold in **native DEM cells**; scale with basin size (20k for 10³ km², 200k for 4×10⁵ km²) |
| `VIC_ROUT_VELOCITY` | Lohmann channel celerity, m/s. **Default 1.5 is a Bengbu value — do NOT inherit it.** See "routing travel time" below (dt_vic_028) |
| `VIC_ROUT_DIFF` | Lohmann diffusivity, m²/s. Default 800. Larger values *advance* the peak as well as broaden it |

The last four DEM/outlet variables are read only by `s5_routing/build_routing_param.py`,
and omitting `VIC_OUTLET_LON/LAT` fails there, not at setup time (dt_vic_025).

### The full chain

```
s0  ki_tools_common.terrain_ops.delineate_basin   -> basin.tif + flow_accum.tif -> basin shapefile
s1  s1_grid/make_basin_grid_nc.py                 -> grid_<basin>_025deg.nc
s2  s3_soil/fill_parameters1.py                   -> SOIL_PARAM_FINAL.txt
s3  s3_soil/fill_parameters2.py                   -> SOIL_PARAM_COMPLETE.txt
s4  s4_veg/process_vegetation_detailed.py         -> vic_veg_param_final.txt
s5  s2_forcing/forcing_1d.py                      -> per-month basin NetCDF (resumable)
s6  s2_forcing/process_forcing.py                 -> per-cell ASCII forcing (7 col, 8 steps/day)
s7  config_paths.create_global_param()            -> global_param_<basin>.txt
s8  model/VIC-5.1.0/.../vic_classic.exe -g …      -> daily flux per cell (mm)
s9  s5_routing/build_routing_param.py             -> direc/frac/xmask/staloc/UH.all   ← NEW
s10 s5_routing/run_routing.py                     -> daily discharge (m3/s) at the gauge  ← NEW
      (wraps model/route_1.0/src/rout; use it, don't shell out to the binary by hand)
```

Order matters: `process_forcing.py` reads the grid coordinates out of
`SOIL_PARAM_COMPLETE.txt`, so **soil must precede forcing** (dt_vic_010).

### 🔴 VIC DOES NOT ROUTE — discharge requires step s9 + s10

`dag.yaml` is explicit: `OUT_DISCHARGE` is emitted only by the optional lake
module. VIC's own output is runoff/baseflow **in mm, per cell**. To compare
against a gauge you MUST run the Lohmann `route_1.0` binary. Summing
runoff+baseflow over the basin is not discharge — it has no travel time, so the
hydrograph has no lag and no attenuation (dt_vic_019).

Preprocess each flux file to the 7 columns `rout` expects
(`year month day prec evap runoff baseflow` = `df.iloc[:, [0,1,2,3,18,16,17]]`
for the standard OUTVAR list) into `routing_param/vic_in/fluxes_<LAT>_<LON>`,
then run `rout`. Routing parameters for a NEW basin are built by
`s5_routing/build_routing_param.py`; feed it the native-resolution
`flow_accum.tif` / `basin.tif` / `dem_filled.tif` from `delineate_basin` via
`VIC_FLOW_ACCUM` / `VIC_BASIN_RASTER` / `VIC_FILLED_DEM`. Never let it derive
flow directions from a coarsened DEM (dt_vic_020).

Validate the routing grid before trusting any hydrograph:
* `max_accum × pixel_area` must equal the delineated basin area;
* the arg-max accumulation cell must BE the gauge cell;
* connectivity must be `N/N` — `rout` silently drops disconnected cells.

### 🔴 Also validate the routing TRAVEL TIME — a correct grid is not enough (dt_vic_028)

A routing grid can be perfect and the hydrograph still worthless, because
`VIC_ROUT_VELOCITY` defaults to **1.5 m/s — the value that reproduced Bengbu**
(121,330 km²). Inheriting it at a larger, flatter basin makes the model respond
weeks too early. Two numbers settle it, both from `s5_routing/run_routing.py`:

```python
from s5_routing.run_routing import route, observed_lag_days, basin_mean_uh_lag
sim = route(routing_param_dir, velocity=1.5, diffusivity=800.0)   # ~7 s, 866 cells
print(sim.attrs["uh_lag_days"])                 # what the MODEL's UH_S actually does
print(observed_lag_days(obs_cal, sim_cal))      # what the OBSERVATION says it should do
```

If the observed lag exceeds the UH lag, **identify** velocity by bisecting until the
two agree — on the **calibration window only**. Never fit velocity to NSE.

**First probe `v → 0` (one 7 s call) to learn what the scheme can actually reach.**
`MAKE_UHM` clips each cell's impulse response at `LE*DT = 48 h` and renormalises it, so
once `xmask/velocity > 48 h` the kernel stops changing and `uh_lag` asymptotes to
`mean(UH.all) + mean_path_in_cells × ~1.3 d`. Below that threshold velocity is an **inert
knob** and an optimiser will walk to its lower bound while reporting "improvement". At
哈尔滨 the ceiling is 29.8 d against an observed demand of ~33 d: v = 0.002 and v = 0.15
differ by 2 d of lag and 0.03 of held-out NSE. When the target is unreachable, pin
velocity to the `rout_velocity` `range` lower bound in `calibration.yaml` (0.10 m/s),
report the plateau's NSE spread, and state that the scheme is structurally insufficient.

Two facts that keep being rediscovered the hard way:

* **`NSE ≤ r²`.** Compute zero-lag `r` *before* concluding a bad NSE needs soil
  calibration. At 哈尔滨 the default velocity held `r` at 0.589, so NSE could not
  exceed 0.347 — the target of 0.5 was arithmetically unreachable and no soil
  parameter could have rescued it.
* **Routing conserves mass at every velocity.** `rout` renormalises `UH_S`
  (`unit_hyd_routines.f`), so velocity moves *timing* and can NEVER move PBIAS.
  A volume bias is therefore never evidence that the routing is right, and a
  routing fix will never close a volume bias.

`velocity` in a large flat basin is an **effective basin residence time, not a channel
celerity** — Lohmann's linearised Saint-Venant scheme lumps hillslope, floodplain,
wetland and reservoir storage into `(velocity, diffusivity)`. Where storage dominates,
prefer CaMa-Flood 4.20 (`cama_maps_15min_extracted`), which represents it explicitly.
`rout.f` caps the routed response at `UH_DAY = 96` d and `UH.all` at `KE = 12` d, so
the within-cell UH alone can never supply more than ~12 d of lag.

### 🔴 Check the SPIN-UP before believing any cal/val gap (dt_vic_030)

`fill_parameters1.py` initialises every soil layer at `init_moist = 66.79 mm`
(~10-14% saturation) and the KI column is 1.9 m deep. The standard split gives it ONE
spin-up year. At 哈尔滨 the column needs **5-6 years**: baseflow climbs 22 → 111 mm/yr
and 31-Dec storage 320 → 500 mm across 1980-1987, so the *calibration* window is the
least equilibrated part of the record and PBIAS **grows** as the model equilibrates
(+19.5% → +28.5% → +36.8%). That reads exactly like overfitting and is not.

Before scoring, plot `OUT_SOIL_MOIST_* + OUT_SWE` on 31 Dec of each year and annual
`OUT_BASEFLOW`. If either still trends at `CAL_START`, start the simulation earlier —
CMFD covers 1951-2024 and water-balance mode costs only ~95 s per simulated year for
866 cells.

### 🔴 Profile the observation record BEFORE choosing the simulation period

The KDT standard split (spinup 1980 / cal 1981-85 / val 1986-90) assumes a
continuous record. Chinese gauge files pad gaps with `-99`. Always run
`v = q[q > -90]; v.groupby(v.index.year).size()` first and pick the first
contiguous fully-observed decade, or you will "validate" on zero days
(dt_vic_021). Example: 唐乃亥 has valid daily Q only for
{1985, 1987, 2007-2020, 2022, 2023}.

### Reference runs

| basin | cells | period | routed daily NSE |
|---|---|---|---|
| Bengbu 51080 (Huai, lowland, regulated) | 224 | 1981-90 | ~0.15 (PBIAS +44%) |
| 唐乃亥 Tangnaihai (upper Yellow, alpine) | 251 | cal 2007-11 / val 2012-16 | see `detached/real_case/result.json` |
| 哈尔滨 Harbin (Songhua, cold/snowmelt) | 866 | cal 1981-85 / val 1986-87 | see `detached/real_case/result.json` |

Harbin is the KI's first snow-dominated basin: 384,411 km² above the gauge (398,330 km²
of frac-weighted routed area), mean annual air temperature −5 … +7 °C, and a spring
freshet driven by snowmelt. The observed record is ice-affected in winter and the basin is
partly regulated (Fengman on the Second Songhua, Nierji on the Nen).

**Read this before rerunning Harbin — the 2026-07-10 run overturned three earlier
assumptions:**

1. The dominant error was **never** the soil parameters. It was `VIC_ROUT_VELOCITY = 1.5`
   m/s, giving a 6.2 d basin travel time against an observed 28 d lag. Zero-lag `r` was
   0.589, so NSE was capped at 0.347. Slowing the routing lifts `r` to ~0.90 and the NSE
   ceiling to ~0.80 — **without touching a single soil parameter and without changing
   PBIAS by one part in 10⁴** (dt_vic_028). But note the second half of dt_vic_028:
   `uh_lag` saturates at 29.8 d, the basin demands ~33 d, and velocity is **inert below
   ~0.15 m/s**. Harbin is run at the pool bound v = 0.10 m/s, and held-out NSE varies only
   0.488–0.521 across the entire plateau. Route_1.0 is structurally insufficient here;
   report that rather than optimising inside the plateau.
2. Spin-up of one year is **not enough** here; the deep store is still filling through the
   calibration period, and PBIAS grows +19.5% → +36.8% across the record (dt_vic_030).
3. `FROZEN_SOIL TRUE` was not merely "worth revisiting" — it was **impossible**: the soil
   file carried `bubble = -9999` and `fs_active = 0`, and `NODES` must be ≥ 10 once
   `EXP_TRANS` turns on. Both are fixed (dt_vic_031); the cold-region template is
   `docs/vic_param/global_param_template_frozen.txt`.

What remains after all of that is a **volume** bias (PBIAS ≈ +29% over 1981-87, +37% on
the equilibrated 1986-87 window) that routing physically cannot touch. Budyko (Fu, ω=2.6)
on CMFD `P = 589 mm/yr` and `PET ≈ 750 mm/yr` predicts a natural `Q ≈ 134 mm/yr`; VIC
gives ≈ 150 (trending to ≈ 180 as the store fills) and the gauge records 116. VIC is
modestly wet of Budyko and the gauge modestly dry of it — consistent with CMFD's
undercatch-corrected precipitation *plus* real consumptive use on the Songnen Plain and
reservoir regulation. Report it; do not calibrate it away. NSE at Harbin is **bias-limited,
not timing-limited**: remove the volume bias post hoc and NSE_val ≈ 0.80 = r².

---

<!-- NOTE: Mac development paths below are stale on the server. Use KISSPATH_ROOT/ paths instead. -->

# VIC模型自动化运行 Skill

## 📖 功能说明

本skill用于自动化运行VIC水文模型，从流域shapefile到径流输出的完整流程。支持任意流域，只需提供流域边界shapefile即可。

## 🎯 使用场景

- 新流域VIC模型快速启动
- 标准化VIC参数准备流程
- 自动化VIC运行和后处理

## ⚡ 快速开始

### 前置条件

1. **流域边界文件**: shapefile格式（.shp及配套文件）
2. **气象数据**: CMFD 0.1度3小时数据（位于`data/forcing/Data_forcing_03hr_010deg/`）
3. **Python环境**: 必须使用指定虚拟环境

### 基本用法

```bash
# 🔴 易错点1: 必须先激活正确的Python虚拟环境！
source /Users/yc/Desktop/project/python_env/bin/activate

# 1. 准备流域shapefile
# 🔴 易错点2: shapefile命名可能是两种格式之一：
#    - data/shp/{basin_name}_shp/{basin_name}_clip.shp (如bengbu)
#    - data/shp/{basin_name}_shp/{basin_name}.shp (如wangjiaba)
# 需要在config_paths.py中修改shp_file路径匹配实际文件名

# 2. 修改config_paths.py中的BASIN_NAME变量
cd /Volumes/Expansion2t/hydro-model-workspace/scripts
# 编辑config_paths.py: BASIN_NAME = "your_basin_name"

# 3. 运行配置脚本（必须在虚拟环境中）
# **WARNING**: config_paths.py modifies scripts in-place via regex. When switching basins,
# verify that all scripts have correct paths after running config_paths.py.
# Check for truncated os.path.join() calls.
python config_paths.py

# 4. 手动运行VIC准备和模拟步骤
# 见下方"完整流程"部分
```

---

## 📋 完整流程（推荐手动执行）

### 🔴 重要：执行顺序

**关键顺序**:
```
步骤1(格网) → 步骤2(土壤参数) → 步骤3(植被参数) → 步骤4(气象数据) → 步骤5(配置检查) → 步骤6(运行VIC) → 步骤7(后处理转NC)
```

**顺序原因**:
- `process_forcing.py`需要读取`SOIL_PARAM_COMPLETE.txt`获取格网坐标，**土壤必须在气象之前**
- 植被参数只依赖格网文件，可在土壤之后任意时间执行

### 🔴 重要：正确的路径结构

**所有输出应组织在流域专属目录下**：

```
outputs/{basin_name}/
├── vic_temp/              # VIC中间文件
│   ├── grid/             # 格网文件
│   ├── forcing/          # 气象数据
│   │   ├── forcing_1d/   # 裁剪后的NC文件
│   │   └── forcing_final/# VIC输入forcing文件
│   ├── soil/             # 土壤参数
│   ├── veg/              # 植被参数
│   └── logs/             # 日志
├── vic_result/           # VIC模型输出
└── cama_input/           # 转换后的CaMa输入（可选）
```

### 步骤0: 环境准备

```bash
# 🔴🔴🔴 最重要：激活Python虚拟环境（每次新开终端都要执行）🔴🔴🔴
source /Users/yc/Desktop/project/python_env/bin/activate

# 设置工作目录
cd /Volumes/Expansion2t/hydro-model-workspace

# 设置流域名称（环境变量）
export BASIN_NAME="your_basin_name"
```

### 🔴 易错点汇总（必读）

1. **Python环境**: 每次运行Python脚本前必须执行 `source /Users/yc/Desktop/project/python_env/bin/activate`

2. **shapefile命名**: 检查实际文件名是 `{basin}.shp` 还是 `{basin}_clip.shp`，在config_paths.py中对应修改shp_file路径

3. **时间范围**: 需要在**三个位置**同步修改：
   - `scripts/s2_forcing/forcing_1d.py`: YEAR_START, YEAR_END (第26-27行)
   - `scripts/s2_forcing/process_forcing.py`: START_DATE, END_DATE (第85-86行)
   - 全局参数文件: STARTYEAR, ENDYEAR, FORCEYEAR

4. **forcing_1d.py的GRID_NC_PATH**: config_paths.py**不会**自动更新此路径，需手动修改：
   ```python
   GRID_NC_PATH = Path(r"/Volumes/Expansion2t/hydro-model-workspace/outputs/{basin}/vic_temp/grid/grid_{basin}_025deg.nc")
   ```

5. **全局参数文件**: 运行config_paths.py后**必须手动检查**：
   - FROZEN_SOIL 必须是 `FALSE`（不是路径）
   - LAI_SRC 必须是 `FROM_VEGPARAM`（不带额外路径）
   - FORCING1 前缀必须与实际文件名匹配（通常是 `huai_01dy_025deg_`）

---

## 🌊 CaMa-Flood集成

VIC后处理完成后，如需运行CaMa-Flood汇流模型，请参见 **`cama-flood-integration`** skill。

---

## 📋 VIC完整流程

### 步骤1: 生成流域格网 (0.25°)

```bash
cd scripts/s1_grid
python make_basin_grid_nc.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/grid/grid_${BASIN_NAME}_025deg.nc`

**检查**:
```bash
ls -lh outputs/${BASIN_NAME}/vic_temp/grid/
# 应该看到grid_xxx_025deg.nc文件
```

### 步骤2: 生成土壤参数（先于forcing处理）

**⚠️ 重要顺序**: 必须先生成土壤参数，因为forcing处理脚本需要读取土壤参数文件来获取格网坐标信息。

#### 2.1 生成土壤参数框架

```bash
cd scripts/s3_soil
python fill_parameters1.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/soil/SOIL_PARAM_FINAL.txt`

#### 2.2 插值填充土壤参数

```bash
python fill_parameters2.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt`

### 步骤3: 处理气象数据（依赖土壤参数）

**⚠️ 依赖**: 此步骤必须在土壤参数生成之后执行，因为`process_forcing.py`需要读取`SOIL_PARAM_COMPLETE.txt`来获取准确的格网经纬度坐标。

#### 3.1 裁剪CMFD数据到流域范围

```bash
cd scripts/s2_forcing
python forcing_1d.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/forcing/forcing_1d/*.nc` (96个文件)

**关键点**:
- 此步骤从0.1度CMFD数据裁剪到流域网格
- 自动处理边界格网的NaN值

#### 3.2 生成VIC forcing文件

```bash
python process_forcing.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/forcing/forcing_final/huai_01dy_025deg_*.txt` (每个格点一个文件)

**⚠️ 重要**: 检查路径配置
- `INPUT_DATA_DIR`: 应指向 `forcing_1d/`
- `OUTPUT_FORCING_DIR`: 应指向 `forcing_final/`
- `SOIL_PARAM_FILE`: 应指向 `SOIL_PARAM_COMPLETE.txt` (必须存在)

### 步骤4: 生成植被参数

```bash
cd scripts/s4_veg
python process_vegetation_detailed.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/veg/vic_veg_param_final.txt`

### 步骤5: 配置并检查全局参数文件

```bash
cd scripts
python config_paths.py
```

**输出**: `outputs/${BASIN_NAME}/vic_temp/global_param_${BASIN_NAME}.txt`

**⚠️ 关键配置检查**:

编辑 `outputs/${BASIN_NAME}/vic_temp/global_param_${BASIN_NAME}.txt`，确认：

1. **时间设置**（根据需要调整）:
```
STARTYEAR               2024
STARTMONTH              01
STARTDAY                01
ENDYEAR                 2024
ENDMONTH                12
ENDDAY                  31
```

2. **Forcing路径**（文件名前缀要匹配实际文件）:
```
FORCING1                /path/to/forcing_final/huai_01dy_025deg_
```

3. **时间步长**（必须匹配forcing数据）:
```
MODEL_STEPS_PER_DAY     8
FORCE_STEPS_PER_DAY     8
```

4. **输出路径**（应该在流域专属目录下）:
```
RESULT_DIR              /path/to/outputs/${BASIN_NAME}/vic_result/
```

5. **参数文件路径**（确保所有路径正确）:
```
SOIL                    /path/to/outputs/${BASIN_NAME}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt
VEGPARAM                /path/to/outputs/${BASIN_NAME}/vic_temp/veg/vic_veg_param_final.txt
```

### 步骤6: 运行VIC模型

```bash
# 创建输出目录
mkdir -p outputs/${BASIN_NAME}/vic_result

# 运行VIC
/Volumes/Expansion2t/hydro-model-workspace/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe \
  -g outputs/vic_temp/global_param_${BASIN_NAME}.txt
```

**预期输出**:
- `outputs/${BASIN_NAME}/vic_result/huaihe_fluxes_*.txt` (每个格点一个文件)
- 运行时间: 几秒到几分钟（取决于格点数和模拟时长）

**检查输出**:
```bash
ls outputs/${BASIN_NAME}/vic_result/*.txt | wc -l
# 应该等于格点数
```

### 步骤7: VIC后处理（转换为NetCDF）

**仅当需要CaMa-Flood输入时执行**

```bash
cd scripts/vic_post
python process_${BASIN_NAME}.py
```

**输出**: `outputs/${BASIN_NAME}/cama_input/${BASIN_NAME}_runoff_1d_YYYY.nc`

**⚠️ 路径配置**: 确保脚本中的路径变量正确：
- `INPUT_DIR`: VIC输出目录
- `OUTPUT_DIR`: CaMa输入目录

---

## 🔧 常见问题和解决方案

### ⚠️ 问题0: FROZEN_SOIL参数错误

**错误**: `is neither TRUE nor FALSE`

**原因**: 全局参数文件中FROZEN_SOIL后面跟了路径，而不是布尔值

**解决**:
```bash
# 检查全局参数文件
grep FROZEN_SOIL outputs/${BASIN_NAME}/vic_temp/global_param_${BASIN_NAME}.txt

# 应该显示:
# FROZEN_SOIL             FALSE   # Not simulating frozen soil

# 如果显示路径，手动修改为上述格式
```

**根本解决**:
- 已修复模板文件 `docs/vic_param/global_param_huaihe_cama.txt`
- 重新运行 `python scripts/config_paths.py` 生成新的全局参数文件

### 问题1: Forcing文件找不到

**错误**: `Unable to open File .../forcing_XX.XXXX_XXX.XXXX`

**原因**: 全局参数文件中的FORCING1前缀与实际文件名不匹配

**解决**:
```bash
# 检查实际文件名
ls outputs/${BASIN_NAME}/vic_temp/forcing/forcing_final/ | head -1

# 示例输出: huai_01dy_025deg_31.1250_115.6250
# 则FORCING1应设置为: .../forcing_final/huai_01dy_025deg_
```

### 问题2: 时间步数不足

**错误**: `Not enough records in forcing file`

**原因**: 全局参数文件的模拟时段超出forcing数据范围

**解决**: 确保STARTYEAR/ENDYEAR与forcing数据时间范围一致

### 问题3: 路径混乱

**错误**: 各种"文件不存在"错误

**原因**: 输出文件散落在不同目录（vic_temp vs. ${BASIN_NAME}/vic_temp）

**解决**:
1. 统一使用 `outputs/${BASIN_NAME}/` 作为流域专属根目录
2. 检查所有脚本中的路径配置
3. 必要时手动创建符号链接或移动文件

### 问题4: 植被参数根系分布之和>1

**警告**: `Root zone fractions sum to more than 1`

**原因**: 正常情况，VIC会自动归一化

**解决**: 无需处理，这是警告不是错误

---

## 📊 输出说明

### VIC模型输出文件

**位置**: `outputs/${BASIN_NAME}/vic_result/huaihe_fluxes_LAT_LON.txt`

**格式**: ASCII文本，列分隔

**主要变量**:
- `OUT_PREC`: 降水
- `OUT_RUNOFF`: 地表径流
- `OUT_BASEFLOW`: 基流
- `OUT_EVAP`: 蒸散发
- `OUT_SOIL_MOIST`: 土壤湿度
- 等（见全局参数文件OUTVAR配置）

### NetCDF输出（后处理）

**位置**: `outputs/${BASIN_NAME}/cama_input/${BASIN_NAME}_runoff_1d_YYYY.nc`

**变量**:
- `Runoff`: 总径流 (OUT_RUNOFF + OUT_BASEFLOW)
- 单位: mm/day
- 维度: (time, lat, lon)

---

## 🎓 新流域适配指南

### 1. 准备流域数据

```bash
# 创建流域目录
mkdir -p data/shp/${BASIN_NAME}_shp

# 复制shapefile（确保包含.shp, .shx, .dbf, .prj等文件）
cp /path/to/your/basin.shp data/shp/${BASIN_NAME}_shp/${BASIN_NAME}_clip.shp
# ... 其他配套文件
```

### 2. 修改config_paths.py

编辑 `scripts/config_paths.py`:
```python
# 修改流域名称
BASIN_NAME = "your_basin_name"  # 改为你的流域名

# 其他配置会自动适配
```

### 3. 创建VIC后处理脚本

复制并修改现有脚本:
```bash
cd scripts/vic_post
cp process_bengbu.py process_${BASIN_NAME}.py
```

编辑新脚本，修改以下变量:
```python
# 输入输出路径
INPUT_DIR = f"/path/to/outputs/{BASIN_NAME}/vic_result"
OUTPUT_DIR = f"/path/to/outputs/{BASIN_NAME}/cama_input"

# 网格定义（从shapefile自动获取，或手动设置）
NX = 24        # 东西方向格点数
NY = 16        # 南北方向格点数
WEST = 111.875   # 西边界
EAST = 117.625   # 东边界
NORTH = 34.875  # 北边界
SOUTH = 31.125  # 南边界
GRID_SIZE = 0.25  # 分辨率

# 文件名前缀（根据实际forcing文件名调整）
FILE_PREFIX = "huaihe_fluxes_"
OUTPUT_NC_PREFIX = f"{BASIN_NAME}_runoff_1d_"
```

### 4. 按照"完整流程"执行

从步骤0开始，依次执行所有步骤。

---

## 💡 最佳实践

### 1. 路径管理
- ✅ 使用流域专属目录 `outputs/${BASIN_NAME}/`
- ✅ 保持一致的路径结构
- ❌ 避免硬编码绝对路径

### 2. 配置管理
- ✅ 运行前检查所有路径配置
- ✅ 验证forcing文件名前缀
- ✅ 确认时间范围匹配

### 3. 调试策略
- ✅ 逐步执行，检查每步输出
- ✅ 保存日志文件
- ✅ 使用 `ls -lh` 验证文件生成

### 4. 数据验证
- ✅ 检查格点数是否正确
- ✅ 验证时间序列长度
- ✅ 检查数值范围合理性

---

## 📚 参考资料

- VIC模型文档: https://vic.readthedocs.io/
- CMFD气象数据: http://www.tpdc.ac.cn/
- 本项目README: `/Volumes/Expansion2t/hydro-model-workspace/README.md`

---

## ✨ 版本历史

- **v1.1** (2025-02-01):
  - 修正路径结构说明
  - 明确流程顺序
  - 添加常见问题解决方案
  - 改进新流域适配指南

- **v1.0** (2025-01-31): 初始版本

---

## 📧 维护信息

**Skill路径**: `/Volumes/Expansion2t/hydro-model-workspace/skills/vic-auto-run/`

**核心脚本**: 见 `scripts/` 目录下各子目录

**依赖**:
- VIC 5.0.1+
- Python 3.8+
- 虚拟环境: `/Users/yc/Desktop/project/python_env/`
