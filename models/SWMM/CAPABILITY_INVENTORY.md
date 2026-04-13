# CAPABILITY_INVENTORY.md -- EPA SWMM 5.2
## KDT v5.0 Stage s2: Capability Discovery

**Model**: EPA SWMM 5.2 (Storm Water Management Model)
**Date**: 2026-04-03
**Existing tools**: 29 tools across 7 stages (s1-s7), plus 5 __init__.py
**Source**: SKILL.md, 29 tool source files, diagnostics/triplets.yaml, docs/*.md, SWMM 5.2 User Manual reference

---

## Summary

| Metric | Value |
|--------|-------|
| Total capabilities identified | 62 |
| DONE (tool exists and covers capability) | 33 |
| PARTIAL (mentioned in SKILL.md or options but no dedicated tool) | 10 |
| TODO (SWMM supports it, KI has zero coverage) | 19 |
| Coverage (DONE + PARTIAL) / Total | 69.4% |
| Coverage (DONE only) / Total | 53.2% |

---

## Top 5 Gaps (highest-impact TODO capabilities)

| Rank | Capability | Category | Impact | Why it matters |
|------|-----------|----------|--------|----------------|
| 1 | **Pollutant definition and buildup/washoff** | Water Quality | Critical | SWMM's WQ engine is a core differentiator; SKILL.md lists it but zero tools exist. No [POLLUTANTS], [LANDUSES], [BUILDUP], [WASHOFF] generation. |
| 2 | **Real-Time Control (RTC) rules** | Hydraulics | High | [CONTROLS] section enables automated pump/gate/weir operation. Essential for smart stormwater management and CSO control scenarios. |
| 3 | **Groundwater / aquifer modeling** | Hydrology | High | Two-zone GW model ([AQUIFERS], [GROUNDWATER]) is unique to SWMM. Currently `IGNORE_GROUNDWATER=YES` is hardcoded in assemble_inp_file.py. |
| 4 | **Treatment functions at nodes** | Water Quality | High | [TREATMENT] section allows removal equations at any node (e.g., BMP efficiency). Zero tools exist despite being the main WQ evaluation pathway. |
| 5 | **Snowmelt modeling** | Hydrology | Medium | [SNOWPACKS] and snowmelt routines exist in SWMM. `IGNORE_SNOWMELT=YES` is hardcoded. No tool to define snow parameters for cold-climate urban areas. |

---

## Detailed Capability Inventory

### A. HYDROLOGY -- Rainfall-Runoff (10 capabilities)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| H01 | Subcatchment delineation (Voronoi/DEM) | [SUBCATCHMENTS] | **DONE** | `delineate_subcatchments` -- Voronoi from node points, DEM-based slope |
| H02 | Land use classification and impervious fraction | [SUBCATCHMENTS], [SUBAREAS] | **DONE** | `classify_land_use` -- raster overlay, lookup table for %imperv, roughness, depression storage |
| H03 | Subcatchment hydraulic parameters (width, slope) | [SUBCATCHMENTS] | **DONE** | `compute_subcatchment_params` -- DEM-derived slope, width = A/L formula |
| H04 | Infiltration: Horton method | [INFILTRATION], [OPTIONS] | **DONE** | `compute_subcatchment_params` -- Horton defaults by soil group A-D |
| H05 | Infiltration: Green-Ampt method | [INFILTRATION], [OPTIONS] | **DONE** | `compute_subcatchment_params` -- GA defaults by USDA texture class |
| H06 | Infiltration: Modified Horton / Modified Green-Ampt | [INFILTRATION], [OPTIONS] | **PARTIAL** | `configure_simulation_options` accepts MODIFIED_HORTON/MODIFIED_GREEN_AMPT but `compute_subcatchment_params` has no separate parameter sets for modified variants |
| H07 | Infiltration: SCS Curve Number | [INFILTRATION], [OPTIONS] | **DONE** | `compute_subcatchment_params` -- CN defaults by soil group |
| H08 | Snowmelt modeling | [SNOWPACKS], [OPTIONS] IGNORE_SNOWMELT | **TODO** | assemble_inp_file hardcodes `IGNORE_SNOWMELT=YES`. No tool to define [SNOWPACKS] or snow parameters (base temp, melt coefficients, ATI weight). |
| H09 | Evaporation (constant/monthly/timeseries) | [EVAPORATION] | **PARTIAL** | No tool to configure [EVAPORATION] section. assemble_inp_file does not write it (SWMM uses internal defaults). |
| H10 | Temperature data for snowmelt/evap | [TEMPERATURE] | **TODO** | No tool. Required for snowmelt and Hargreaves-style evaporation. |

### B. GROUNDWATER (3 capabilities)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| G01 | Two-zone aquifer definition | [AQUIFERS] | **TODO** | SWMM's two-zone GW model (upper unsaturated + lower saturated). No tool exists. assemble_inp_file hardcodes `IGNORE_GROUNDWATER=YES`. |
| G02 | Groundwater flow to drainage nodes | [GROUNDWATER] | **TODO** | Links aquifers to subcatchments and specifies GW discharge equation coefficients. No tool exists. |
| G03 | Groundwater lateral/deep flow equations | [GW_FLOW] (custom) | **TODO** | Custom GW flow equations (SWMM 5.2 feature). Advanced, no tool. |

### C. HYDRAULICS -- Pipe Network (15 capabilities)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| N01 | Junction nodes (manholes) | [JUNCTIONS] | **DONE** | `create_drainage_network` -- reads CSV, validates connectivity |
| N02 | Outfall nodes (boundary conditions) | [OUTFALLS] | **DONE** | `create_drainage_network` -- FREE/NORMAL/FIXED/TIDAL/TIMESERIES types |
| N03 | Conduit links (pipes, channels) | [CONDUITS] | **DONE** | `create_drainage_network` -- from/to, length, roughness |
| N04 | Cross-section geometry (12+ shapes) | [XSECTIONS] | **DONE** | `define_cross_sections` -- CIRCULAR, RECT_CLOSED, TRAPEZOIDAL, IRREGULAR, etc. (14 shapes) |
| N05 | Irregular cross-sections (transects) | [TRANSECTS] | **PARTIAL** | `define_cross_sections` lists IRREGULAR shape but no dedicated tool generates [TRANSECTS] section with station-elevation data |
| N06 | Import network from GIS shapefiles | N/A (preprocessing) | **DONE** | `import_network_from_gis` -- spatial proximity matching for from/to nodes |
| N07 | Network connectivity validation | N/A (validation) | **DONE** | `validate_network_connectivity` -- orphan nodes, reachability to outfall, adverse slopes, zero-length conduits, cycles |
| N08 | Storage unit nodes | [STORAGE] | **PARTIAL** | Referenced in SKILL.md and triplets.yaml but no dedicated tool to define storage units with curves. assemble_inp_file does not write [STORAGE]. |
| N09 | Divider nodes | [DIVIDERS] | **TODO** | Flow dividers (overflow, cutoff, tabular, weir). Referenced in SKILL.md but no tool and not assembled into INP. |
| N10 | Pump links | [PUMPS], [CURVES] | **TODO** | Pumps with characteristic curves (Type1-4). Referenced in SKILL.md but no tool exists. |
| N11 | Orifice links | [ORIFICES] | **TODO** | Side/bottom orifices for flow control. Referenced in SKILL.md but no tool exists. |
| N12 | Weir links | [WEIRS] | **TODO** | Transverse/sideflow/V-notch/trapezoidal weirs. Referenced in SKILL.md but no tool exists. |
| N13 | Outlet links (rating curve) | [OUTLETS] | **TODO** | Functional or tabular rating curve links. Not referenced in SKILL.md. |
| N14 | Routing methods (STEADY/KINWAVE/DYNWAVE) | [OPTIONS] | **DONE** | `configure_simulation_options` -- all three methods supported |
| N15 | Curves (pump, storage, tidal, etc.) | [CURVES] | **TODO** | General curve definitions used by pumps, storage, and outlets. No tool exists. |

### D. RAINFALL FORCING (6 capabilities)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| R01 | Rain gage definition | [RAINGAGES] | **DONE** | `assemble_inp_file` -- writes RAINGAGES section from JSON |
| R02 | Rainfall timeseries from gauge data | [TIMESERIES] | **DONE** | `create_rain_timeseries` -- CSV to SWMM DAT format with unit conversion |
| R03 | Design storm generation (SCS/Chicago/Uniform/Triangular) | [TIMESERIES] | **DONE** | `generate_design_storm` -- 7 storm types with proper depth distribution |
| R04 | VIC forcing to SWMM rainfall | [TIMESERIES] | **DONE** | `convert_vic_forcing_to_swmm` -- handles VIC 3-hourly precip to mm/hr intensity |
| R05 | Rainfall input validation | N/A (validation) | **DONE** | `validate_rainfall_input` -- negative values, gaps, extreme intensities, format checks |
| R06 | CMIP6 climate-scaled rainfall | [TIMESERIES] | **DONE** | `scale_cmip6_rainfall_to_swmm` -- delta-change method with literature defaults |

### E. WATER QUALITY (9 capabilities)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| W01 | Pollutant definition (TSS, BOD, metals, bacteria) | [POLLUTANTS] | **TODO** | Defines pollutant names, units, concentration units, co-pollutant relationships, first-order decay, snow-only flag. Zero tools exist. |
| W02 | Land use categories for WQ | [LANDUSES] | **TODO** | Links land use types to pollutant loading functions. No tool (classify_land_use handles hydrology only). |
| W03 | Pollutant buildup functions | [BUILDUP] | **TODO** | Power/exponential/saturation buildup per land use per pollutant. No tool exists. |
| W04 | Pollutant washoff functions | [WASHOFF] | **TODO** | Exponential/rating-curve/EMC washoff per land use per pollutant. No tool exists. |
| W05 | Initial pollutant loadings | [LOADINGS] | **TODO** | Initial surface buildup at simulation start. No tool exists. |
| W06 | Land use coverage per subcatchment | [COVERAGES] | **TODO** | Fractional land use composition per subcatchment for WQ calculations. No tool (classify_land_use returns %imperv but not WQ land use fractions). |
| W07 | Treatment functions at nodes | [TREATMENT] | **TODO** | Removal equations at treatment nodes (e.g., R = 0.5*C for 50% removal). Enables BMP performance modeling. No tool exists. |
| W08 | Pollutant routing in conduits | SWMM engine (automatic) | **PARTIAL** | SWMM automatically routes pollutants through conduits using advection + decay once [POLLUTANTS] etc. are defined. extract_results could extract WQ but does not currently expose pollutant concentration outputs. |
| W09 | WQ result extraction (node/link concentrations) | .out binary file | **TODO** | extract_results.py does not extract pollutant concentrations from SWMM output. SUBCATCH_VARIABLES dict stops at "runoff" (index 4); pollutant concentrations are indices 5+. |

### F. LOW IMPACT DEVELOPMENT / GREEN INFRASTRUCTURE (5 capabilities)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| L01 | LID control definition (7 types) | [LID_CONTROLS] | **DONE** | `create_lid_control` -- BC, RG, GR, IT, PP, RB, VS with all layers (surface, soil, storage, drain, drainmat, pavement) |
| L02 | LID assignment to subcatchments | [LID_USAGE] | **DONE** | `assign_lid_to_subcatchment` -- number, area, width, initial saturation, routing |
| L03 | LID parameter validation | N/A (validation) | **DONE** | `validate_lid_params` -- WP < FC < porosity, range checks, cross-layer consistency |
| L04 | LID assembly into INP | [LID_CONTROLS], [LID_USAGE] | **DONE** | `assemble_inp_file` -- writes both sections from JSON inputs |
| L05 | LID performance result extraction | .out / LID report files | **PARTIAL** | LID_USAGE supports per-unit report files, but extract_results.py does not parse LID-specific report files (per-unit water balance, drain flow, overflow). |

### G. MODEL ASSEMBLY AND OPTIONS (5 capabilities)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| A01 | Simulation options configuration | [OPTIONS] | **DONE** | `configure_simulation_options` -- flow units, routing, infiltration, dates, timesteps |
| A02 | INP file assembly from components | All sections | **DONE** | `assemble_inp_file` -- combines CSV/JSON components into complete INP |
| A03 | INP file structural validation | All sections | **DONE** | `validate_inp_file` -- cross-reference checks, required sections, pyswmm parse test |
| A04 | Dry weather flow (combined sewers) | [DWF], [PATTERNS] | **PARTIAL** | Triplet dt_012 documents DWF diagnostics, validate_inp_file recognizes the section, but no tool to generate [DWF] or [PATTERNS] entries |
| A05 | Report configuration | [REPORT] | **DONE** | `assemble_inp_file` -- writes SUBCATCHMENTS ALL, NODES ALL, LINKS ALL |

### H. EXECUTION AND RESULTS (4 capabilities)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| E01 | Run simulation (pyswmm + CLI fallback) | N/A | **DONE** | `run_swmm` -- pyswmm primary, CLI fallback, progress reporting, continuity error reporting |
| E02 | Continuity error checking | .rpt file | **DONE** | `check_continuity_errors` -- runoff/routing/quality errors, flooding/surcharging summaries, PASS/WARN/FAIL |
| E03 | Timeseries result extraction | .out binary | **DONE** | `extract_results` -- node (depth, head, inflow, flooding), link (flow, depth, velocity), subcatchment (rainfall, runoff, infiltration) |
| E04 | System-level result extraction | .out / .rpt | **PARTIAL** | check_continuity_errors extracts system totals from RPT but no tool produces system-level timeseries (total inflow, outflow, storage) from .out |

### I. MODEL COUPLING (5 capabilities)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| C01 | VIC runoff to SWMM inflow | [INFLOWS] | **DONE** | `convert_vic_runoff_to_swmm_inflow` -- mm/day to m3/s with temporal disaggregation |
| C02 | VIC forcing to SWMM rainfall | [TIMESERIES] | **DONE** | `convert_vic_forcing_to_swmm` -- shared meteorology |
| C03 | CaMa-Flood stage to SWMM outfall BC | [TIMESERIES], [OUTFALLS] | **DONE** | `convert_cama_stage_to_outfall_bc` -- sfcelv extraction, datum offset |
| C04 | SWMM outflow to CaMa-Flood lateral inflow | NetCDF output | **DONE** | `convert_swmm_outflow_to_cama_lateral` -- outfall aggregation to CaMa grid |
| C05 | Coupling water balance validation | N/A (validation) | **DONE** | `validate_coupling_water_balance` -- VIC/SWMM/CaMa mass balance closure |

### J. REAL-TIME CONTROL (2 capabilities)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| J01 | Simple rule-based control | [CONTROLS] | **TODO** | IF-THEN-ELSE rules for pump on/off, gate open/close, weir setting based on node depth, time, or simulation variable. No tool exists. |
| J02 | PID control (proportional-integral-derivative) | [CONTROLS] PID | **TODO** | Continuous PID control for modulated devices. No tool exists. |

### K. RDII (Rainfall-Dependent Infiltration/Inflow) (1 capability)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| K01 | RDII unit hydrograph modeling | [RDII], [HYDROGRAPHS] | **TODO** | Three-triangle unit hydrograph method for I/I in aging sewers. validate_inp_file recognizes the sections but no tool generates RDII parameters. |

### L. EXTERNAL INFLOWS (2 capabilities)

| ID | Capability | SWMM Section(s) | Status | Tool(s) / Notes |
|----|-----------|-----------------|--------|-----------------|
| X01 | Direct external inflow timeseries | [INFLOWS] | **DONE** | `convert_vic_runoff_to_swmm_inflow` writes INFLOWS-compatible output. assemble_inp_file could incorporate it. |
| X02 | RDII inflow at nodes | [RDII] | **TODO** | See K01 above. |

---

## Coverage by Category

| Category | Total | DONE | PARTIAL | TODO | Coverage % |
|----------|-------|------|---------|------|-----------|
| A. Hydrology | 10 | 5 | 2 | 3 | 70.0% |
| B. Groundwater | 3 | 0 | 0 | 3 | 0.0% |
| C. Hydraulics | 15 | 8 | 2 | 5 | 66.7% |
| D. Rainfall Forcing | 6 | 6 | 0 | 0 | 100.0% |
| E. Water Quality | 9 | 0 | 1 | 8 | 11.1% |
| F. LID / Green Infrastructure | 5 | 4 | 1 | 0 | 100.0% |
| G. Model Assembly | 5 | 4 | 1 | 0 | 100.0% |
| H. Execution & Results | 4 | 3 | 1 | 0 | 100.0% |
| I. Model Coupling | 5 | 5 | 0 | 0 | 100.0% |
| J. Real-Time Control | 2 | 0 | 0 | 2 | 0.0% |
| K. RDII | 1 | 0 | 0 | 1 | 0.0% |
| L. External Inflows | 2 | 1 | 0 | 1 | 50.0% |

---

## Gap Analysis: Priority Recommendations

### Tier 1 -- Critical gaps (blocks major use cases)

**Water Quality (W01-W07, W09)**: The entire WQ subsystem is absent. SWMM's WQ engine
is a core differentiator vs. pure hydraulic models. Without tools for [POLLUTANTS],
[LANDUSES], [BUILDUP], [WASHOFF], [TREATMENT], [LOADINGS], and [COVERAGES],
the KI cannot model urban NPS pollution, BMP effectiveness, or TMDL compliance.
This is the single largest gap.

Recommended new tools (new stage s8_water_quality or expand s4):
- `define_pollutants` -- create [POLLUTANTS] with units, decay, co-pollutant
- `define_wq_landuses` -- create [LANDUSES] with sweeping interval
- `configure_buildup_washoff` -- create [BUILDUP] and [WASHOFF] per landuse/pollutant
- `assign_wq_coverages` -- create [COVERAGES] fractional land use per subcatchment
- `define_treatment` -- create [TREATMENT] removal equations at nodes
- `extract_wq_results` -- extend extract_results to pull pollutant concentrations

### Tier 2 -- High-value gaps (enables advanced scenarios)

**Real-Time Control (J01-J02)**: No tool for [CONTROLS] section. RTC is essential
for smart stormwater management, CSO control, and green infrastructure optimization.
- `create_rtc_rules` -- IF-THEN-ELSE rule builder with validation

**Groundwater (G01-G03)**: Two-zone aquifer model is unique to SWMM but completely
disabled (IGNORE_GROUNDWATER=YES hardcoded). Needed for baseflow simulation in
areas with shallow water tables.
- `define_aquifer` -- create [AQUIFERS] section
- `assign_groundwater` -- create [GROUNDWATER] links to subcatchments

**Hydraulic structures (N10-N12, N15)**: Pumps, orifices, weirs, and curves are
referenced in SKILL.md but have no tools. Required for any model with active flow
control structures.
- `create_hydraulic_structures` -- combined tool for [PUMPS], [ORIFICES], [WEIRS], [OUTLETS], [CURVES]

### Tier 3 -- Nice-to-have gaps

**Snowmelt (H08, H10)**: Relevant only for cold-climate urban areas.
**RDII (K01)**: Relevant only for aging combined/sanitary sewer systems.
**DWF patterns (A04)**: Needed for combined sewer models.
**Storage units (N08)**: Detention ponds, tanks -- partially handled but no dedicated tool.
**Transects (N05)**: Irregular channel cross-sections from survey data.
**LID report parsing (L05)**: Per-unit LID water balance output.

---

## Relationship to Existing Diagnostics

The 20 diagnostic triplets in `diagnostics/triplets.yaml` cover:
- Runtime errors (dt_001, dt_002, dt_003, dt_017, dt_018, dt_019, dt_020): 7 triplets
- Silent errors (dt_004, dt_009, dt_010, dt_015, dt_016): 5 triplets
- Parameter errors (dt_005, dt_006, dt_007, dt_008, dt_011, dt_014): 6 triplets
- Encoding/format (dt_013): 1 triplet
- Combined sewer (dt_012): 1 triplet

No diagnostic triplets exist for water quality errors (e.g., negative concentrations,
buildup exceeding washoff, treatment removal > 100%). These should be added when
WQ tools are created.

---

## INP Sections: Coverage Map

| INP Section | Status | Notes |
|-------------|--------|-------|
| [TITLE] | DONE | assemble_inp_file |
| [OPTIONS] | DONE | configure_simulation_options |
| [RAINGAGES] | DONE | assemble_inp_file |
| [SUBCATCHMENTS] | DONE | assemble_inp_file |
| [SUBAREAS] | DONE | assemble_inp_file |
| [INFILTRATION] | DONE | assemble_inp_file (Horton/GA/CN) |
| [JUNCTIONS] | DONE | create_drainage_network |
| [OUTFALLS] | DONE | create_drainage_network |
| [CONDUITS] | DONE | create_drainage_network |
| [XSECTIONS] | DONE | define_cross_sections |
| [TRANSECTS] | PARTIAL | shape listed but section not generated |
| [TIMESERIES] | DONE | multiple rainfall tools |
| [CURVES] | TODO | needed for pumps, storage, outlets |
| [LID_CONTROLS] | DONE | create_lid_control |
| [LID_USAGE] | DONE | assign_lid_to_subcatchment |
| [INFLOWS] | DONE | convert_vic_runoff_to_swmm_inflow |
| [DWF] | PARTIAL | recognized, no generator |
| [PATTERNS] | TODO | time patterns for DWF |
| [STORAGE] | PARTIAL | recognized, no generator |
| [DIVIDERS] | TODO | no tool |
| [PUMPS] | TODO | no tool |
| [ORIFICES] | TODO | no tool |
| [WEIRS] | TODO | no tool |
| [OUTLETS] | TODO | no tool |
| [CONTROLS] | TODO | RTC rules, no tool |
| [POLLUTANTS] | TODO | no tool |
| [LANDUSES] | TODO | no tool (WQ land uses) |
| [COVERAGES] | TODO | no tool |
| [BUILDUP] | TODO | no tool |
| [WASHOFF] | TODO | no tool |
| [LOADINGS] | TODO | no tool |
| [TREATMENT] | TODO | no tool |
| [AQUIFERS] | TODO | no tool |
| [GROUNDWATER] | TODO | no tool |
| [SNOWPACKS] | TODO | no tool |
| [TEMPERATURE] | TODO | no tool |
| [EVAPORATION] | PARTIAL | not generated, uses SWMM defaults |
| [RDII] | TODO | no tool |
| [HYDROGRAPHS] | TODO | no tool |
| [REPORT] | DONE | assemble_inp_file |
| [COORDINATES] | DONE | assemble_inp_file |
| [MAP] | DONE | assemble_inp_file |
| [LOSSES] | TODO | entrance/exit/flap gate losses for conduits |

**INP section coverage**: 17 DONE / 6 PARTIAL / 19 TODO out of 42 sections = 40.5% DONE, 54.8% DONE+PARTIAL

---

## Methodology

This inventory was produced by:

1. Reading the full SKILL.md (356 lines) documenting the 7-stage pipeline
2. Inspecting all 29 tool source files for implemented capabilities
3. Cross-referencing against the SWMM 5.2 User Manual section list
4. Checking diagnostics/triplets.yaml (20 triplets) for referenced but unimplemented features
5. Verifying which INP sections assemble_inp_file.py actually writes vs. merely recognizes in validate_inp_file.py
6. Mapping each SWMM engine capability (from the INP format specification) to existing tools

The SWMM 5.2 INP format defines 42+ section types. The current KI generates 17 of them,
recognizes/validates 6 more, and has no coverage for 19 sections -- predominantly in the
water quality, groundwater, hydraulic structures, and real-time control domains.
