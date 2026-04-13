# EPA SWMM 5.2 — Pipeline Workflow Summary

## Overview

The SWMM knowledge infrastructure defines a 7-stage pipeline for autonomous urban stormwater drainage modeling, from subcatchment delineation through coupled rural-urban flood simulation.

## Pipeline Stages

```
S1 (Subcatchments) ─┐
                     ├──► S5 (Model Assembly) ──► S6 (Execution) ──► S7 (Coupling)
S2 (Network) ───────┤                                                    │
                     │                                                    │
S3 (Rainfall) ──────┘                                                    │
                                                                         │
S4 (LID Setup) ─── depends on S1 ──► feeds into S5                      │
                                                                         │
                                                         ┌───────────────┘
                                                         │
                                                    VIC/CaMa-Flood
                                                    (HydroCraft)
```

### Stage Dependencies

| Stage | Depends On | Can Parallel With |
|-------|-----------|-------------------|
| S1: Subcatchment Delineation | none | S2, S3 |
| S2: Drainage Network | none | S1, S3 |
| S3: Rainfall Forcing | none | S1, S2 |
| S4: LID Setup | S1 | S2, S3 |
| S5: Model Assembly | S1, S2, S3, (S4) | none |
| S6: Execution | S5 | none |
| S7: Model Coupling | S6 + VIC/CaMa | none |

### Stage Details

#### S1: Subcatchment Delineation (4 tools)
- Delineate subcatchments from DEM, GIS parcels, or Thiessen polygons
- Classify land use and compute percent impervious
- Compute width (Area / flow_path_length), slope, depression storage
- Assign infiltration parameters (Horton, Green-Ampt, or SCS CN)
- Validate all subcatchments have valid outlets

**Key output**: Subcatchment parameters (area, %imperv, width, slope, infiltration, outlet)

#### S2: Drainage Network (4 tools)
- Define junctions (manholes) with invert elevations and max depths
- Define conduits (pipes) with cross-sections, roughness, lengths
- Define outfalls with boundary conditions (FREE, NORMAL, FIXED, TIMESERIES)
- Import from GIS if available
- Validate connectivity (every node reaches an outfall)

**Key output**: Network definition (junctions, conduits, outfalls, cross-sections)

#### S3: Rainfall Forcing (4 tools)
- Create rainfall time series from gauge data, VIC forcing, or design storms
- Define rain gages with FORMAT (INTENSITY or VOLUME) and INTERVAL
- Assign rain gages to subcatchments
- Validate FORMAT/INTERVAL match data convention

**Key output**: Rainfall time series and gage configuration

#### S4: LID Setup (3 tools, optional)
- Define LID control types (bioretention, green roof, permeable pavement, etc.)
- Assign LID controls to subcatchments with area and routing
- Validate physical consistency (WP < FC < porosity, area constraints)

**Key output**: LID control definitions and usage assignments

#### S5: Model Assembly (3 tools)
- Configure simulation options (FLOW_UNITS, routing model, timesteps, dates)
- Assemble all components into a complete INP file
- Validate internal consistency (cross-references, units, completeness)

**Key output**: Complete, validated SWMM INP file

#### S6: Execution (3 tools)
- Run SWMM simulation via pyswmm
- Check continuity errors (< 5% for runoff, < 1% for routing with DYNWAVE)
- Extract results (node flooding, conduit flow, outfall discharge, subcatchment runoff)

**Key output**: Simulation results (RPT, OUT files, extracted CSVs)

#### S7: Model Coupling (4 tools, optional)
- VIC runoff → SWMM junction inflow (mm/day → m3/s conversion)
- CaMa-Flood stage → SWMM outfall boundary (datum alignment)
- SWMM outflow → CaMa-Flood lateral inflow (temporal aggregation)
- Validate coupled water balance at all interfaces

**Key output**: Coupled simulation with consistent rural-urban hydrology

## Critical Warnings

1. **FLOW_UNITS determines everything** — CFS vs CMS controls ALL input/output units. Mismatch is SILENT.
2. **Rainfall FORMAT must match data** — INTENSITY vs VOLUME mismatch produces wrong runoff by a factor of N. SILENT.
3. **Width = Area / flow_path** — NOT sqrt(Area). Wrong width produces wrong hydrograph shape. SILENT.
4. **VIC unit conversion** — mm/day to m3/s requires /86400000. Missing factor = wrong by orders of magnitude. SILENT.
5. **CaMa datum offset** — Must align SWMM local datum with CaMa MSL datum. Wrong offset = wrong backwater. SILENT.

## Diagnostic Triplets

20 triplets covering runtime, parameter, silent error, and coupling failure modes. See `diagnostics/triplets.yaml`.

## Tools Inventory

| Stage | Tools | Total |
|-------|-------|-------|
| S1 | delineate_subcatchments, classify_land_use, compute_subcatchment_params, validate_subcatchments | 4 |
| S2 | create_drainage_network, import_network_from_gis, define_cross_sections, validate_network_connectivity | 4 |
| S3 | create_rain_timeseries, convert_vic_forcing_to_swmm, generate_design_storm, validate_rainfall_input | 4 |
| S4 | create_lid_control, assign_lid_to_subcatchment, validate_lid_params | 3 |
| S5 | assemble_inp_file, configure_simulation_options, validate_inp_file | 3 |
| S6 | run_swmm, extract_results, check_continuity_errors | 3 |
| S7 | convert_vic_runoff_to_swmm_inflow, convert_cama_stage_to_outfall_bc, convert_swmm_outflow_to_cama_lateral, validate_coupling_water_balance | 4 |
| **Total** | | **25** |
