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
| to run the pipeline stages | `tools/` (35 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (7 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (24 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (24 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/run_city_swmm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_city_swmm.py --help` |
| `tools/s1_subcatchment_delineation/classify_land_use.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_subcatchment_delineation/classify_land_use.py --help` |
| `tools/s1_subcatchment_delineation/compute_subcatchment_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_subcatchment_delineation/compute_subcatchment_params.py --help` |
| `tools/s1_subcatchment_delineation/delineate_subcatchments.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_subcatchment_delineation/delineate_subcatchments.py --help` |
| `tools/s1_subcatchment_delineation/validate_subcatchments.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s1_subcatchment_delineation/validate_subcatchments.py --help` |
| `tools/s2_drainage_network/create_drainage_network.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_drainage_network/create_drainage_network.py --help` |
| `tools/s2_drainage_network/define_cross_sections.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_drainage_network/define_cross_sections.py --help` |
| `tools/s2_drainage_network/import_network_from_gis.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_drainage_network/import_network_from_gis.py --help` |
| `tools/s2_drainage_network/validate_network_connectivity.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s2_drainage_network/validate_network_connectivity.py --help` |
| `tools/s3_rainfall_forcing/convert_vic_forcing_to_swmm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_rainfall_forcing/convert_vic_forcing_to_swmm.py --help` |
| `tools/s3_rainfall_forcing/create_rain_timeseries.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_rainfall_forcing/create_rain_timeseries.py --help` |
| `tools/s3_rainfall_forcing/generate_design_storm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_rainfall_forcing/generate_design_storm.py --help` |
| `tools/s3_rainfall_forcing/scale_cmip6_rainfall_to_swmm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_rainfall_forcing/scale_cmip6_rainfall_to_swmm.py --help` |
| `tools/s3_rainfall_forcing/validate_rainfall_input.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s3_rainfall_forcing/validate_rainfall_input.py --help` |
| `tools/s4_lid_setup/assign_lid_to_subcatchment.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_lid_setup/assign_lid_to_subcatchment.py --help` |
| `tools/s4_lid_setup/create_lid_control.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_lid_setup/create_lid_control.py --help` |
| `tools/s4_lid_setup/validate_lid_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s4_lid_setup/validate_lid_params.py --help` |
| `tools/s5_model_assembly/assemble_inp_file.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_model_assembly/assemble_inp_file.py --help` |
| `tools/s5_model_assembly/configure_simulation_options.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_model_assembly/configure_simulation_options.py --help` |
| `tools/s5_model_assembly/validate_inp_file.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s5_model_assembly/validate_inp_file.py --help` |
| `tools/s6_execution/check_continuity_errors.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_execution/check_continuity_errors.py --help` |
| `tools/s6_execution/extract_results.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_execution/extract_results.py --help` |
| `tools/s6_execution/run_swmm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s6_execution/run_swmm.py --help` |
| `tools/s7_model_coupling/convert_cama_stage_to_outfall_bc.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_model_coupling/convert_cama_stage_to_outfall_bc.py --help` |
| `tools/s7_model_coupling/convert_swmm_outflow_to_cama_lateral.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_model_coupling/convert_swmm_outflow_to_cama_lateral.py --help` |
| `tools/s7_model_coupling/convert_vic_runoff_to_swmm_inflow.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_model_coupling/convert_vic_runoff_to_swmm_inflow.py --help` |
| `tools/s7_model_coupling/validate_coupling_water_balance.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/s7_model_coupling/validate_coupling_water_balance.py --help` |

*27 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
Then convert to SWMM rainfall format using this KI's tool: `tools/s3_rainfall_forcing/convert_vic_forcing_to_swmm.py`

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.

---

# EPA SWMM 5.2 Knowledge Infrastructure — Agent Entry Point

**Model**: EPA SWMM 5.2 (Storm Water Management Model)
**Developer**: US Environmental Protection Agency / Computational Hydraulics International (CHI)
**Engine**: C library (open source), accessed via pyswmm (Python) or swmm-toolkit
**Domain**: Urban stormwater drainage, pipe network hydraulics, green infrastructure (LID), urban flood modeling
**Repository**: https://github.com/USEPA/SWMM (C engine), https://github.com/pyswmm/pyswmm (Python API)
**Documentation**: https://www.epa.gov/water-research/storm-water-management-model-swmm

---

## What This Infrastructure Enables

Autonomous operation of EPA SWMM 5.2 for urban-scale simulation of:

- **Urban Hydrology**: Rainfall-runoff from subcatchments with impervious/pervious surfaces, infiltration (Horton, Green-Ampt, SCS CN), depression storage, evaporation, snowmelt
- **Pipe Network Hydraulics**: Steady-state, kinematic wave, or full dynamic wave routing through pipes, open channels, pumps, orifices, weirs, storage units
- **Water Quality**: Buildup-washoff of pollutants (TSS, BOD, metals, bacteria), first-order decay, co-pollutant relationships
- **Low Impact Development (LID)**: Bioretention, green roofs, permeable pavement, rain barrels, infiltration trenches, vegetative swales — performance modeling for green infrastructure design
- **Urban Flooding**: Node flooding volumes, surcharging, ponding, backwater effects from receiving water bodies

SWMM is the world's most widely used urban drainage model, with 50+ years of development. Version 5.2 uses a C engine with text-based INP files for input and binary OUT files for results.

---

## Installation

SWMM requires NO compilation. The C engine is distributed as a shared library through pip packages:

```bash
pip install pyswmm          # Python API + SWMM engine (recommended)
pip install swmm-toolkit     # Low-level C library bindings
pip install swmm-api         # INP file parser/writer (for programmatic INP manipulation)
```

**pyswmm** is the primary interface. It bundles the SWMM 5.2 C engine and provides a Pythonic API for running simulations, accessing results during runtime, and reading binary output files. No separate compilation or executable is needed.

**swmm-api** is a pure-Python INP file parser/writer. It can read, modify, and write INP files without running SWMM. Useful for programmatic model setup and batch parameter modification.

Verify installation:
```python
from pyswmm import Simulation
print("pyswmm ready")
```

---

## INP File Format

The SWMM INP file is a plain-text file with bracketed section headers. Each section contains tabular data (space-delimited, one record per line). Comments start with `;`. Key sections:

### Required Sections

| Section | Description |
|---------|-------------|
| `[TITLE]` | Model description |
| `[OPTIONS]` | Simulation options (FLOW_UNITS, INFILTRATION, ROUTING_MODEL, dates, timesteps) |
| `[RAINGAGES]` | Rain gage definitions (format, interval, data source) |
| `[SUBCATCHMENTS]` | Subcatchment properties (rain gage, outlet, area, %imperv, width, slope) |
| `[SUBAREAS]` | Subcatchment surface properties (N-imperv, N-perv, S-imperv, S-perv, routing) |
| `[INFILTRATION]` | Infiltration parameters per subcatchment (method-dependent) |
| `[JUNCTIONS]` | Junction nodes (invert elevation, max depth, ponded area) |
| `[OUTFALLS]` | Outfall nodes (elevation, boundary type) |
| `[CONDUITS]` | Pipe/channel links (from-node, to-node, length, roughness, offsets) |
| `[XSECTIONS]` | Cross-section geometry per conduit (shape, dimensions) |
| `[TIMESERIES]` | Time series data (rainfall, boundary conditions) |

### Optional Sections

| Section | Description |
|---------|-------------|
| `[LID_CONTROLS]` | LID type definitions (bioretention, green roof, etc.) |
| `[LID_USAGE]` | LID placement on subcatchments |
| `[INFLOWS]` | External inflow time series at nodes (for VIC coupling) |
| `[DWF]` | Dry weather flow at nodes (for combined sewers) |
| `[DIVIDERS]` | Flow divider nodes |
| `[STORAGE]` | Storage unit nodes |
| `[PUMPS]` | Pump links |
| `[ORIFICES]` | Orifice links |
| `[WEIRS]` | Weir links |
| `[CURVES]` | Pump curves, storage curves, tidal curves |
| `[TRANSECTS]` | Irregular cross-section geometry |
| `[REPORT]` | Output reporting configuration |
| `[COORDINATES]` | Node x,y coordinates for visualization |
| `[POLYGONS]` | Subcatchment polygon vertices |

### Example INP Snippet

```
[TITLE]
Urban drainage model — downtown district

[OPTIONS]
FLOW_UNITS           CMS
INFILTRATION         HORTON
ROUTING_MODEL        DYNWAVE
START_DATE           01/01/2020
END_DATE             12/31/2020
REPORT_START_DATE    01/01/2020
WET_STEP             00:00:15
DRY_STEP             01:00:00
ROUTING_STEP         00:00:15
REPORT_STEP          00:05:00
ALLOW_PONDING        YES

[RAINGAGES]
;Name    Format   Interval  SCF  Source
RG1      INTENSITY  0:05    1.0  TIMESERIES  rainfall_2020

[SUBCATCHMENTS]
;Name   RainGage  Outlet  Area   %Imperv  Width  Slope  CurbLen
S1      RG1       J1      2.5    65       150    0.5    0

[JUNCTIONS]
;Name   Elev   MaxDepth  InitDepth  SurDepth  Aponded
J1      10.0   3.0       0          0         1000
J2      9.5    3.0       0          0         1000

[OUTFALLS]
;Name   Elev   Type
OF1     8.0    FREE

[CONDUITS]
;Name   From  To   Length  Roughness  InOffset  OutOffset
C1      J1    J2   200     0.013      0         0
C2      J2    OF1  150     0.013      0         0

[XSECTIONS]
;Link   Shape     Geom1  Geom2  Geom3  Geom4  Barrels
C1      CIRCULAR  0.6    0      0      0      1
C2      CIRCULAR  0.8    0      0      0      1
```

---

## Pipeline Overview (7 Stages)

| Stage | Name | Key Tools | Skill Document |
|-------|------|-----------|----------------|
| S1 | Subcatchment Delineation | `delineate_subcatchments`, `classify_land_use`, `compute_subcatchment_params`, `validate_subcatchments` | `docs/s1_subcatchment_delineation_skill.md` |
| S2 | Drainage Network | `create_drainage_network`, `import_network_from_gis`, `define_cross_sections`, `validate_network_connectivity` | `docs/s2_drainage_network_skill.md` |
| S3 | Rainfall Forcing | `create_rain_timeseries`, `convert_vic_forcing_to_swmm`, `generate_design_storm`, `validate_rainfall_input` | `docs/s3_rainfall_forcing_skill.md` |
| S4 | LID Setup | `create_lid_control`, `assign_lid_to_subcatchment`, `validate_lid_params` | `docs/s4_lid_setup_skill.md` |
| S5 | Model Assembly | `assemble_inp_file`, `configure_simulation_options`, `validate_inp_file` | `docs/s5_model_assembly_skill.md` |
| S6 | Execution | `run_swmm`, `extract_results`, `check_continuity_errors` | `docs/s6_execution_skill.md` |
| S7 | Model Coupling | `convert_vic_runoff_to_swmm_inflow`, `convert_cama_stage_to_outfall_bc`, `convert_swmm_outflow_to_cama_lateral`, `validate_coupling_water_balance` | `docs/s7_model_coupling_skill.md` |

**Dependency graph**: S1, S2, S3 can run in parallel; S4 depends on S1; S5 depends on S1+S2+S3 (and optionally S4); S6 depends on S5; S7 depends on S6.

---

## Template-Aligned KI Sections (2026-08-18)

The sections below align this entry point with the current 12-section KI template while preserving the SWMM-specific operating notes that follow. Exact machine-readable contracts remain in `docs/format_spec.yaml`, `dag.yaml`, `diagnostics/triplets.yaml`, and `docs/validation_convention.yaml`.

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | EPA SWMM 5.2 (Storm Water Management Model) |
| Version | SWMM 5.2.x engine via pyswmm / swmm-toolkit |
| Language | C engine with Python bindings |
| License | Public-Domain |
| Repository | https://github.com/USEPA/Stormwater-Management-Model |
| Primary domain | Urban stormwater hydrology and drainage-network hydraulics |
| Spatial mode | Distributed-stream urban subcatchments and drainage network |

## 2. What This Model Does

SWMM simulates rainfall-runoff generation from urban subcatchments, infiltration losses, optional groundwater and LID controls, drainage-network hydraulic routing, water quality transport, and node flooding. The active KI runs the real SWMM 5.2 engine through pyswmm or swmm-toolkit; do not replace it with a simplified runoff equation.

## 3. Input Requirements

Exact input shapes live in `docs/format_spec.yaml`, projected from `dag.yaml` and `diagnostics/triplets.yaml`. Use that file as the contract and the stage docs as the procedure.

### 3.1 Meteorological Forcing

| Variable | Unit model expects | Source dataset | Source unit | Conversion |
|----------|-------------------|----------------|------------|------------|
| Precipitation / rainfall | `mm/hr` intensity or `mm/interval` volume for CMS; `in/hr` or `in` for CFS | CMFD / MSWX / NASA POWER or user gage data | Dataset-specific | Convert with `tools/s3_rainfall_forcing/convert_vic_forcing_to_swmm.py`; the `[RAINGAGES]` `FORMAT` must match intensity vs volume. |
| Air temperature | `deg C/F` | User series or forcing dataset | Dataset-specific | Required for snowmelt / Hargreaves workflows; see `docs/format_spec.yaml`. |
| Evaporation | `mm/day` SI or `in/day` US | User series or Hargreaves-derived | Dataset-specific | SWMM expects actual evaporation. |
| Wind speed | `km/hr` SI or `mph` US | User series or forcing dataset | Dataset-specific | Used for snowmelt refinement when configured. |

### 3.2 Static Inputs

| Input | Source | Tool that prepares it |
|-------|--------|----------------------|
| Subcatchment geometry and parameters | GIS / DEM / land cover / user drainage design | `tools/s1_subcatchment_delineation/` |
| Drainage nodes, links, cross sections | GIS network or user drainage design | `tools/s2_drainage_network/` |
| LID controls and placement | Design specifications / scenario inputs | `tools/s4_lid_setup/` |
| Model INP assembly | Stage outputs plus simulation options | `tools/s5_model_assembly/` |

### 3.3 Configuration Files

| File | Format | Notes |
|------|--------|-------|
| SWMM model input | `.inp` text with bracketed sections | `[OPTIONS]`, `[RAINGAGES]`, `[SUBCATCHMENTS]`, `[JUNCTIONS]`, `[CONDUITS]`, `[XSECTIONS]`, and optional LID / inflow / quality sections. |
| SWMM binary output | `.out` binary | Read with pyswmm / swmm-toolkit extraction tools. |
| SWMM report | `.rpt` text | Continuity errors and summaries are parsed by execution diagnostics. |

## 4. Build Instructions

SWMM requires no local compilation in this KI. Install the packaged bindings:

```bash
pip install pyswmm swmm-toolkit swmm-api
python preflight_check.py
```

Known build issue: if the model fails to import or execute, follow the mandatory execution policy and check `diagnostics/triplets.yaml` before debugging.

## 5. Execution

Use the stage tools rather than ad hoc scripts:

```bash
python preflight_check.py
python tools/s5_model_assembly/validate_inp_file.py --help
python tools/s6_execution/run_swmm.py --help
python tools/s6_execution/extract_results.py --help
python tools/s6_execution/check_continuity_errors.py --help
```

Expected runtime depends on network size, routing timestep, and reporting cadence. Dynamic-wave runs with short conduits require smaller routing timesteps and therefore longer runtime.

## 6. Output Description

**Source: `dag.yaml`. If this section ever disagrees with `dag.yaml`, the dag wins.**

Headline output, the dag's `validation_rank: 1` variable:

> `subcatchment_runoff` -- Surface runoff flow rate generated by a subcatchment. (`m3/s (CMS) or cfs (US)`)

| Output variable (dag `var`) | Rank | Emitted in | Unit | Description |
|-----------------------------|------|------------|------|-------------|
| `subcatchment_runoff` | 1 | `.out (SubcatchResult RUNOFF) and .rpt` | `m3/s (CMS) or cfs (US)` | Surface runoff flow rate generated by a subcatchment. |
| `node_depth_head` | 2 | `.out (NodeResult DEPTH/HEAD)` | `m (CMS) or ft (US)` | Water depth above invert and hydraulic head at a node (junction, storage, outfall). |
| `node_flooding` | 3 | `.out (NodeResult FLOOD) and .rpt node flooding summary` | `flow m3/s; volume m3` | Surface-water overflow rate and total surface floodwater volume at a drainage-network node when capacity is exceeded. |
| `link_flow` | 4 | `.out (LinkResult FLOW) and .rpt outfall loading summary` | `m3/s (CMS) or cfs (US)` | Stormwater flow rate through a drainage-network conduit/link; outfall discharge equals total inflow at the outfall node. |
| `link_depth_velocity` | 5 | `.out (LinkResult DEPTH/velocity)` | `depth m; velocity m/s; capacity fraction` | Stormwater flow depth, velocity, and fraction-of-full capacity in a drainage-network conduit. |
| `subcatchment_infiltration` | 6 | `.out (SubcatchResult INFILTRATION)` | `mm/hr` | Infiltration rate into pervious soil per subcatchment. |
| `groundwater_outflow` | 7 | `.out (SubcatchResult / SystemAttribute GW_INFLOW)` | `flow m3/s; table elev m` | Groundwater table elevation and lateral groundwater outflow per subcatchment. |
| `pollutant_concentration_load` | 8 | `.out (pollutant per element) and .rpt` | `mass/volume; mass` | Pollutant concentration and washoff load at subcatchments, nodes, and links. |
| `continuity_error` | 9 | `.rpt continuity tables` | `percent` | Surface-runoff water and drainage-network water flow-routing continuity errors; primary internal mass-balance/numerical-stability diagnostic. |

## 7. Tool Inventory

| Stage | Tool directory | Purpose |
|-------|----------------|---------|
| S1 | `tools/s1_subcatchment_delineation/` | Delineate and validate subcatchments and surface parameters. |
| S2 | `tools/s2_drainage_network/` | Create or import drainage network geometry and cross sections. |
| S3 | `tools/s3_rainfall_forcing/` | Build rainfall time series and convert forcing into SWMM format. |
| S4 | `tools/s4_lid_setup/` | Create and assign LID controls. |
| S5 | `tools/s5_model_assembly/` | Assemble and validate SWMM INP files. |
| S6 | `tools/s6_execution/` | Run SWMM, extract outputs, and check continuity errors. |
| S7 | `tools/s7_model_coupling/` | Convert VIC and CaMa-Flood exchanges for coupled workflows. |

## 8. Unit Conversion Table

| Variable | Source unit (verified) | Model unit | Factor | Type |
|----------|------------------------|------------|--------|------|
| VIC runoff to SWMM inflow | `mm/day` per grid cell | `m3/s` for CMS | `cell_area / 86400000` | multiplicative |
| CMS pipe dimensions | `m` | `m` | `1` | multiplicative |
| CMS subcatchment area | `ha` | `ha` | `1` | multiplicative |
| CMS rainfall intensity | `mm/hr` | `mm/hr` | `1` | multiplicative |
| CMS rainfall volume | `mm/interval` | `mm/interval` | `1` | multiplicative |
| CFS pipe dimensions | `ft` | `ft` | `1` | multiplicative |
| CFS subcatchment area | `acre` | `acre` | `1` | multiplicative |
| CFS rainfall intensity | `in/hr` | `in/hr` | `1` | multiplicative |
| CFS rainfall volume | `in/interval` | `in/interval` | `1` | multiplicative |

### 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|-------------------|-----------------|
| `subcatchment_runoff` | Flow rate generated by a subcatchment; `m3/s (CMS) or cfs (US)` | Depth-rate runoff from land-surface models | Magnitude and water-balance errors when comparing or coupling. |
| `subcatchment_infiltration` | Infiltration rate into pervious soil; `mm/hr` | Accumulated infiltration per reporting interval | Event totals and losses are miscomputed. |
| `node_depth_head` | Water depth/head above node invert/reference; `m (CMS) or ft (US)` | Absolute water-surface elevation without datum alignment | Stage validation is biased by datum mismatch. |
| `link_flow` | Conduit/link flow in SWMM flow units; `m3/s (CMS) or cfs (US)` | Grid-cell runoff depth or lateral inflow volume | Outfall discharge and coupling volumes are wrong. |
| `continuity_error` | Percent mass-balance error from `.rpt` continuity tables | Performance metric against observations | Numerical stability can be mistaken for skill. |

Output unit verification checklist:

- Read the run's `[OPTIONS] FLOW_UNITS` before interpreting any length, area, rainfall, or flow.
- Check whether rainfall is configured as `INTENSITY`, `VOLUME`, or `CUMULATIVE`.
- Compare `.rpt` continuity errors before judging observational metrics.
- For stage/depth observations, verify datum alignment against node invert and sensor reference.

## 9. Diagnostic Triplets (Top 5)

The full corpus stays in `diagnostics/triplets.yaml`; these are the first triplets to check for common SWMM failures.

| # | Error | Diagnosis | Remedy |
|---|-------|-----------|--------|
| 1 | `dt_001`: high routing continuity error above 5% | Routing timestep is too large for dynamic wave transitions. | Reduce `ROUTING_STEP` and `WET_STEP`, then re-run and verify continuity. |
| 2 | `dt_003`: node flooding with water loss | `ALLOW_PONDING=NO` or `Aponded=0` removes flooded-node water from the system. | Set `ALLOW_PONDING=YES` and define ponded area where flooding can occur. |
| 3 | `dt_004`: flow magnitudes, velocities, or depths wrong by orders of magnitude | `FLOW_UNITS` does not match dimensions, areas, rainfall, or elevations. | Validate every dimensional input against the selected unit system. |
| 4 | `dt_009`: runoff volume wrong by factor of N | Rain-gage `FORMAT` does not match rainfall encoding. | Correct `INTENSITY` vs `VOLUME` and regenerate rainfall input. |
| 5 | `dt_010`: VIC-SWMM inflow magnitude wrong | `mm/day` per grid cell was converted incorrectly to SWMM flow units. | Apply `Q = runoff_vic * cell_area / 86400000` for CMS and validate total volumes. |

## 10. Coupling Interfaces

| Upstream model | Variable exchanged | Unit | Temporal resolution |
|----------------|-------------------|------|---------------------|
| VIC | Surface runoff / baseflow converted to SWMM inflow | `m3/s` for CMS after conversion from `mm/day` | Source/run dependent |
| VIC | Meteorological forcing reused as SWMM rainfall | `mm/hr` intensity or `mm/interval` volume | Source/run dependent |
| CaMa-Flood | River stage at SWMM outfalls | `m (CMS) or ft (US)` | Source/run dependent |

| Downstream model | Variable exchanged | Unit | Temporal resolution |
|------------------|-------------------|------|---------------------|
| CaMa-Flood | SWMM outfall discharge as lateral inflow | `m3/s (CMS) or cfs (US)` before downstream conversion | SWMM report/extraction cadence |

## 11. Validated Results

No achieved calibration, validation, or full-period metric values are stated in the sourced KI files summarized here. Treat run skill as pending until an actual SWMM run is compared against observations with the conventions below.

### Performance Metrics - judged against the field's bar, not intuition

**Source: `docs/validation_convention.yaml`. Every stated band below carries its citation key. A null convention band must be written as "no cited threshold"; do not substitute a guess.**

| Dag variable | Metric | Direction | Convention bar, cited | Achieved |
|--------------|--------|-----------|-----------------------|----------|
| `subcatchment_runoff` | `nse` | maximize | satisfactory `0.50` (moriasi2015, moriasi2007); good `0.70` (moriasi2015, moriasi2007); very_good `0.80` (moriasi2015, moriasi2007) | pending |
| `subcatchment_runoff` | `pbias` | zero_centered | satisfactory `15.0` (moriasi2015); good `10.0` (moriasi2015); very_good `5.0` (moriasi2015) | pending |
| `node_depth_head` | `r` | maximize | satisfactory `0.77` (moriasi2015); good `0.84` (moriasi2015); very_good `0.89` (moriasi2015) | pending |
| `node_depth_head` | `pbias` | zero_centered | satisfactory `25.0` (moriasi2015); good `15.0` (moriasi2015); very_good `10.0` (moriasi2015) | pending |

For zero-centered `pbias`, judge absolute bias against the cited band magnitude. For `subcatchment_runoff`, validation is against `nse` and `pbias` for directly observed or outlet-inferred runoff/flow; direct per-subcatchment runoff observations are rare.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | Pipeline / user forcing | Pending until run-specific validation | Use `docs/format_spec.yaml` and S3 tools. |
| Subcatchment geometry | Pipeline / GIS inputs | Pending until run-specific validation | Use S1 validation before model assembly. |
| Drainage network | Pipeline / GIS inputs | Pending until run-specific validation | Use S2 validation and continuity checks. |
| LID controls | Scenario / design inputs | Pending until run-specific validation | Use S4 validation where LID is active. |
| Boundary conditions | VIC / CaMa-Flood / user series | Pending until run-specific validation | Verify units and datum before execution. |

## 12. Parameter Selection by Region

Use physically informed starting points from SWMM documentation, local drainage design records, soils, land cover, and the stage docs; treat them as initial values, not calibration results. Region-specific values are not hard-coded in this entry point because the selected basin, drainage network, and observation target determine defensible parameter ranges.

---

## Critical Domain Knowledge

### 1. FLOW_UNITS Determines the ENTIRE Unit System (SILENT ERROR)

The `FLOW_UNITS` option in `[OPTIONS]` is the single most important setting in SWMM. It determines the unit system for ALL inputs and outputs:

| FLOW_UNITS | System | Pipe dimensions | Depth | Area | Rainfall | Flow |
|-----------|--------|-----------------|-------|------|----------|------|
| CFS | US Customary | feet | feet | acres | inches | ft3/s |
| GPM | US Customary | feet | feet | acres | inches | gal/min |
| MGD | US Customary | feet | feet | acres | inches | 10^6 gal/day |
| CMS | SI Metric | meters | meters | hectares | mm | m3/s |
| LPS | SI Metric | meters | meters | hectares | mm | L/s |
| MLD | SI Metric | meters | meters | hectares | mm | 10^6 L/day |

**If you set FLOW_UNITS=CMS but enter pipe diameters in millimeters instead of meters, SWMM treats a 600mm pipe as 600 meters in diameter.** The simulation will run without error but results are completely wrong. There is NO warning. Always verify dimensional consistency.

### 2. Routing Timestep Must Satisfy Courant Condition (Dynamic Wave)

For DYNWAVE routing, the routing timestep must satisfy:

```
dt <= dx / sqrt(g * h_max)
```

Where `dx` is the shortest conduit length, `g` = 9.81 m/s2, and `h_max` is the maximum expected depth. For typical urban drainage:
- 100m conduit, 3m max depth: dt <= 100 / sqrt(9.81 * 3) = 18.4s
- 50m conduit, 2m max depth: dt <= 50 / sqrt(9.81 * 2) = 11.3s

**Rule of thumb**: Start with WET_STEP = ROUTING_STEP = 15s for dynamic wave. Reduce to 5-10s if continuity errors exceed 1%. For kinematic wave, 30-60s is usually sufficient.

### 3. Rainfall FORMAT: INTENSITY vs VOLUME (SILENT ERROR)

The `[RAINGAGES]` FORMAT field must match how the rainfall data is recorded:
- **INTENSITY**: values represent instantaneous rainfall rate (mm/hr or in/hr)
- **VOLUME**: values represent total depth over the recording interval (mm or in per interval)

**If FORMAT=INTENSITY but data is actually volume (mm/interval), runoff will be multiplied by the number of intervals per hour.** For 5-minute data recorded as mm/5min, setting FORMAT=INTENSITY treats each value as mm/hr, producing 12x the actual rainfall. This is a SILENT ERROR — SWMM runs fine, but peak flows are wildly wrong.

**Always verify**: Check the raw data documentation. If a 5-min interval shows 2.5 for a heavy storm, is it 2.5 mm in 5 minutes (VOLUME) or 2.5 mm/hr rate during that 5 minutes (INTENSITY)? Most automated gauges record VOLUME.

### 4. Subcatchment Width Calculation

Subcatchment width is NOT an arbitrary parameter. It represents the characteristic width of overland flow:

```
Width = Area / longest_overland_flow_path
```

Setting width too large (e.g., width = sqrt(area)) produces artificially fast runoff response (too-peaked hydrograph). Setting width too small produces delayed, attenuated runoff.

For rectangular subcatchments, width is literally the shorter dimension. For irregular shapes, use Area divided by the longest flow path from the hydraulically most remote point to the outlet.

### 5. ALLOW_PONDING for Continuous Simulations

When a junction node floods (water depth exceeds max_depth), SWMM's default behavior is to lose the excess water (it disappears from the system). Setting `ALLOW_PONDING=YES` with a non-zero `Aponded` (ponded area in junction definition) lets water pond on the surface and re-enter the system when capacity becomes available.

**Always set ALLOW_PONDING=YES for continuous simulations**. Without it, flooding events cause permanent water loss, producing negative routing continuity errors.

### 6. VIC-SWMM Coupling: Unit Conversion

VIC outputs runoff in mm/day per grid cell. SWMM expects inflow in flow units (m3/s for CMS):

```
Q_swmm (m3/s) = runoff_vic (mm/day) * cell_area (m2) / (1000 * 86400)
                = runoff_vic * cell_area / 86400000
```

Where `cell_area` is the VIC grid cell area in m2. For a 0.25-degree cell at 30N latitude, area is approximately 600 km2 = 6e8 m2.

**This conversion is a SILENT ERROR source**: if you forget the /1000 (mm to m), flows are 1000x too large. If you forget the /86400 (day to seconds), flows are 86400x too large. Always validate by comparing total volumes.

---

## Quick-Start Example Workflow

```python
# 1. Install dependencies
# pip install pyswmm swmm-api

# 2. Create a minimal INP file (use tools or write manually)
from tools.s5_model_assembly.assemble_inp_file import assemble_inp
assemble_inp(
    subcatchment_data="outputs/run/subcatchments.csv",
    network_data_dir="outputs/run/network/",
    rainfall_data_dir="outputs/run/rainfall/",
    options={"FLOW_UNITS": "CMS", "INFILTRATION": "HORTON", "ROUTING_MODEL": "DYNWAVE"},
    output_inp="outputs/run/model.inp"
)

# 3. Validate the INP file
from tools.s5_model_assembly.validate_inp_file import validate
report = validate("outputs/run/model.inp")
assert report["errors"] == 0

# 4. Run simulation
from pyswmm import Simulation
with Simulation("outputs/run/model.inp") as sim:
    for step in sim:
        pass  # SWMM runs step by step

# 5. Check continuity errors
from tools.s6_execution.check_continuity_errors import check
errors = check("outputs/run/model.rpt")
print(f"Runoff error: {errors['runoff_pct']:.2f}%")
print(f"Routing error: {errors['routing_pct']:.2f}%")

# 6. Extract results
from tools.s6_execution.extract_results import extract
extract(
    out_file="outputs/run/model.out",
    extract_config={"nodes": ["OF1"], "system": True},
    output_dir="outputs/run/results/"
)
```

---

## Common Errors Reference

| ID | Error | Severity | Stage | Root Cause |
|----|-------|----------|-------|------------|
| dt_001 | High routing continuity error (>5%) | degraded | S6 | Routing timestep too large for dynamic wave |
| dt_002 | Unstable oscillating flow | fatal | S6 | Adverse conduit slopes with dynamic wave |
| dt_003 | Node flooding with water loss | degraded | S6 | ALLOW_PONDING=NO (default) |
| dt_004 | Wrong flow magnitudes (orders of magnitude off) | silent | S5 | FLOW_UNITS CFS/CMS mismatch with input dimensions |
| dt_005 | Subcatchment not draining | fatal | S1 | Outlet references non-existent node |
| dt_006 | Wrong infiltration behavior | degraded | S1 | Infiltration params don't match chosen method |
| dt_007 | Simulation crash on conduit | fatal | S2 | Zero-length conduit |
| dt_008 | Water disappears from system | fatal | S2 | No outfall defined |
| dt_009 | Runoff volume wrong by factor of N | silent | S3 | Rainfall INTENSITY vs VOLUME format mismatch |
| dt_010 | VIC-SWMM inflow magnitude wrong | silent | S7 | mm/day to m3/s conversion error |
| dt_011 | LID has no infiltration | degraded | S4 | Soil WP > FC or FC > porosity |
| dt_015 | CaMa-SWMM backwater wrong | silent | S7 | Datum mismatch between models |
| dt_016 | Hydrograph too peaked | silent | S1 | Subcatchment width too large |

Full diagnostic triplets: `diagnostics/triplets.yaml`

---

## HydroCraft Integration Points

SWMM integrates with HydroCraft's VIC and CaMa-Flood models through four coupling pathways:

### 1. VIC Surface Runoff to SWMM Inflow (Rural-to-Urban)
VIC grid cells surrounding the urban area produce surface runoff and baseflow. These are converted to external inflow time series at SWMM junction nodes representing the urban boundary. Use `convert_vic_runoff_to_swmm_inflow`.

### 2. VIC Forcing to SWMM Rainfall (Shared Meteorology)
Reuse VIC's meteorological forcing (CMFD, MSWX, or NASA POWER) as SWMM rainfall input for consistent precipitation across the rural-urban interface. Use `convert_vic_forcing_to_swmm`.

### 3. CaMa-Flood Stage to SWMM Outfall BC (River Backwater)
CaMa-Flood's river water surface elevation is used as a time-varying boundary condition at SWMM outfalls. This captures backwater effects when the receiving river floods, preventing drainage discharge and causing urban flooding. Use `convert_cama_stage_to_outfall_bc`.

### 4. SWMM Outflow to CaMa-Flood Lateral Inflow (Urban-to-River)
SWMM outfall discharge is converted to CaMa-Flood lateral inflow, representing urban drainage contributions to the river system. Use `convert_swmm_outflow_to_cama_lateral`.

### Coupling Sequence

For a fully coupled simulation:
1. Run VIC (watershed hydrology) -- produces runoff + forcing
2. Run CaMa-Flood (river routing) -- produces river stage at urban outfalls
3. Convert VIC runoff + forcing to SWMM inputs
4. Convert CaMa stage to SWMM outfall boundary conditions
5. Run SWMM (urban drainage) -- produces outfall discharge
6. (Optional) Feed SWMM outfall discharge back to CaMa-Flood as lateral inflow for a second iteration

For one-way coupling (simpler, usually sufficient):
1. Run VIC + CaMa-Flood for the watershed
2. Convert outputs to SWMM boundary conditions
3. Run SWMM standalone with external inputs

---

## File Organization

```
knowledge_infrastructure/
  knowledge_infrastructure.yaml    # Package manifest
  SKILL.md                         # This file (agent entry point)
  tools/
    s1_subcatchment_delineation/    # 4 tools
    s2_drainage_network/            # 4 tools
    s3_rainfall_forcing/            # 4 tools
    s4_lid_setup/                   # 3 tools
    s5_model_assembly/              # 3 tools
    s6_execution/                   # 3 tools
    s7_model_coupling/              # 4 tools
  docs/
    s1_subcatchment_delineation_skill.md
    s2_drainage_network_skill.md
    s3_rainfall_forcing_skill.md
    s4_lid_setup_skill.md
    s5_model_assembly_skill.md
    s6_execution_skill.md
    s7_model_coupling_skill.md
    model_couplings.yaml
  diagnostics/
    triplets.yaml                   # 20 diagnostic triplets
  workflow/
    workflow.md                     # Pipeline summary
```
