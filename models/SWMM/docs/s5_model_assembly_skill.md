# Model Assembly (INP File Generation) — Skill Document

> **Stage ID**: s5_model_assembly
> **Pipeline order**: 5 of 7
> **Depends on**: s1_subcatchment_delineation, s2_drainage_network, s3_rainfall_forcing (optionally s4_lid_setup)

## Purpose

Model assembly combines all component data (subcatchments, drainage network, rainfall, LID, options) into a single SWMM INP file. The INP file is the complete model definition — it contains every piece of information SWMM needs to run a simulation. A well-assembled INP file with correct options and consistent cross-references is the difference between a successful simulation and hours of debugging.

This stage is where the most critical configuration decision is made: the FLOW_UNITS setting, which determines the entire unit system for ALL inputs and outputs. Getting this wrong is a silent error that invalidates every number in the model.

## Prerequisites

Before starting this stage, verify:

- [ ] Subcatchment delineation complete (S1): subcatchment areas, outlets, imperviousness, infiltration params
- [ ] Drainage network defined (S2): junctions, conduits, outfalls, cross-sections
- [ ] Rainfall forcing prepared (S3): time series files, rain gage definitions
- [ ] LID setup complete (S4, optional): LID controls and usage
- [ ] Decision on FLOW_UNITS: CMS (SI, recommended) or CFS (US Customary)
- [ ] Decision on routing model: DYNWAVE (most accurate), KINWAVE (simpler), or STEADY (simplest)
- [ ] Simulation period defined: start date, end date, report start date
- [ ] Python environment has: swmm-api (recommended for INP parsing/writing)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| Subcatchment data | file | S1 output | CSV with all subcatchment parameters |
| Network data | directory | S2 output | Junctions, conduits, outfalls, cross-sections |
| Rainfall data | directory | S3 output | Time series files and gage configuration |
| LID data | file | S4 output (optional) | LID controls and usage |
| Simulation options | config | User/agent decision | FLOW_UNITS, routing model, timesteps, dates |

## Procedure

### Step 1: Configure Simulation Options

The `[OPTIONS]` section controls the entire simulation. Configure carefully:

```bash
python tools/s5_model_assembly/configure_simulation_options.py \
  --flow_units CMS \
  --infiltration_method HORTON \
  --routing_model DYNWAVE \
  --start_date "01/01/2020" \
  --end_date "12/31/2020" \
  --wet_step 15 \
  --dry_step 3600 \
  --report_step "00:05:00" \
  --allow_ponding YES
```

**FLOW_UNITS (CRITICAL — dt_004)**:
- `CMS` (recommended): All dimensions in meters, areas in hectares, rainfall in mm, flow in m3/s
- `CFS`: All dimensions in feet, areas in acres, rainfall in inches, flow in ft3/s

**INFILTRATION**: Must match the parameter format in `[INFILTRATION]` section:
- `HORTON`: MaxRate, MinRate, Decay, DryTime, MaxInfil
- `GREEN_AMPT`: Suction, Ksat, IMD
- `CURVE_NUMBER`: CN, (Ksat), DryTime

**ROUTING_MODEL**:
- `DYNWAVE` (Dynamic Wave): Full Saint-Venant equations. Handles pressurized flow, backwater, reverse flow, surcharging. Requires smallest timestep (5-30s). Most accurate and most computationally expensive.
- `KINWAVE` (Kinematic Wave): Simplified routing. No backwater, no surcharging, no reverse flow. Cannot handle adverse slopes. Timestep 30-60s. Good for screening-level analysis.
- `STEADY` (Steady-State): No flow routing. Instantaneous downstream translation. Only for very simple systems.

**Timestep settings**:
| Parameter | Description | Dynamic Wave | Kinematic Wave |
|-----------|-------------|-------------|----------------|
| WET_STEP | Wet weather routing timestep | 5-30 seconds | 30-60 seconds |
| DRY_STEP | Dry weather timestep | 3600 seconds | 3600 seconds |
| ROUTING_STEP | Routing computation timestep | = WET_STEP | = WET_STEP |
| REPORT_STEP | Output reporting interval | 5-15 minutes | 5-15 minutes |
| RULE_STEP | Control rule evaluation | = REPORT_STEP | = REPORT_STEP |

**Courant condition for Dynamic Wave (dt_001)**:
```
ROUTING_STEP <= min(conduit_length) / sqrt(g * max_depth)
```
For a network with minimum conduit length 50m and max depth 3m:
```
ROUTING_STEP <= 50 / sqrt(9.81 * 3) = 9.2 seconds
```
Use 5 or 10 seconds. If continuity error > 1%, reduce the timestep.

### Step 2: Assemble the INP File

```bash
python tools/s5_model_assembly/assemble_inp_file.py \
  --subcatchment_data outputs/swmm_run/subcatchments/all_params.csv \
  --network_data_dir outputs/swmm_run/network/ \
  --rainfall_data_dir outputs/swmm_run/rainfall/ \
  --lid_data outputs/swmm_run/lid/lid_all.txt \
  --options '{"FLOW_UNITS": "CMS", "INFILTRATION": "HORTON", "ROUTING_MODEL": "DYNWAVE"}' \
  --output_inp outputs/swmm_run/model.inp
```

The assembler creates INP sections in standard order:

```
[TITLE]                  ← Model description
[OPTIONS]                ← Simulation configuration (FLOW_UNITS, routing, dates)
[EVAPORATION]            ← Evaporation parameters
[RAINGAGES]              ← Rain gage definitions (format, interval, data source)
[SUBCATCHMENTS]          ← Subcatchment properties (gage, outlet, area, %imperv, width, slope)
[SUBAREAS]               ← Surface properties (N-imperv, N-perv, S-imperv, S-perv, routing)
[INFILTRATION]           ← Infiltration parameters (method-dependent)
[LID_CONTROLS]           ← LID type definitions (optional)
[LID_USAGE]              ← LID placement on subcatchments (optional)
[JUNCTIONS]              ← Junction nodes (elev, max_depth, init_depth, surcharge, Aponded)
[OUTFALLS]               ← Outfall nodes (elev, type, data)
[STORAGE]                ← Storage nodes (optional)
[CONDUITS]               ← Pipe/channel links (from, to, length, roughness, offsets)
[PUMPS]                  ← Pump links (optional)
[ORIFICES]               ← Orifice links (optional)
[WEIRS]                  ← Weir links (optional)
[XSECTIONS]              ← Cross-section geometry (shape, dimensions)
[TRANSECTS]              ← Irregular cross-section geometry (optional)
[INFLOWS]                ← External inflow time series (for VIC coupling)
[DWF]                    ← Dry weather flow (for combined sewers)
[CURVES]                 ← Pump/storage/tidal curves (optional)
[TIMESERIES]             ← Time series data (rainfall, boundary conditions, inflows)
[REPORT]                 ← Reporting configuration
[TAGS]                   ← Element tags (optional)
[MAP]                    ← Map extent
[COORDINATES]            ← Node x,y coordinates
[VERTICES]               ← Link intermediate vertices (optional)
[Polygons]               ← Subcatchment polygon vertices (optional)
[SYMBOLS]                ← Rain gage symbol locations (optional)
```

### Step 3: Add External Inflows (for VIC Coupling)

If coupling with VIC, add `[INFLOWS]` section for external inflow at boundary junctions:

```
[INFLOWS]
;Node       Parameter  TimeSeries       Type  Mfactor  Sfactor  Baseline  Pattern
J_boundary  FLOW       VIC_inflow_J1    FLOW  1.0      1.0      0
```

The TIMESERIES `VIC_inflow_J1` must be defined in `[TIMESERIES]` with flow values in the model's FLOW_UNITS (m3/s for CMS).

### Step 4: Add Outfall Boundary Conditions (for CaMa Coupling)

For CaMa-Flood coupling, set outfall type to TIMESERIES:

```
[OUTFALLS]
;Name  Elev  Type        Gated  Data
OF1    8.0   TIMESERIES  NO     CaMa_stage_OF1
```

The TIMESERIES `CaMa_stage_OF1` must be defined with head values in the model's length units (meters for CMS).

### Step 5: Configure Report Section

```
[REPORT]
SUBCATCHMENTS  ALL
NODES          ALL
LINKS          ALL
```

Or specific elements:
```
[REPORT]
SUBCATCHMENTS  S1 S2 S3
NODES          J1 J2 OF1
LINKS          C1 C2
```

### Step 6: Validate the Complete INP File

```bash
python tools/s5_model_assembly/validate_inp_file.py \
  --inp_file outputs/swmm_run/model.inp
```

The validator checks:
1. All subcatchment outlets exist as junctions, outfalls, or subcatchments
2. All conduit from/to nodes exist
3. All rain gage names referenced by subcatchments are defined
4. All TIMESERIES referenced by raingages and outfalls exist
5. All LID control names in LID_USAGE are defined in LID_CONTROLS
6. No duplicate IDs across all sections
7. FLOW_UNITS is set and consistent
8. At least one outfall exists
9. Cross-section shapes are valid SWMM shape names
10. Date format is correct (MM/DD/YYYY)

## Expected Outputs

| Output | Path Pattern | Description |
|--------|-------------|-------------|
| INP file | `{output_dir}/model.inp` | Complete SWMM input file |
| Validation report | (stdout/JSON) | Internal consistency check results |

## Validation Checks

1. **Cross-reference integrity**: Every reference (outlet, node, gage, timeseries, LID) resolves
2. **No duplicates**: Unique IDs across all element types
3. **Unit consistency**: All dimensions match FLOW_UNITS convention
4. **Date validity**: Start < End; dates in MM/DD/YYYY format
5. **Section completeness**: All required sections present
6. **INP parseable**: swmm-api or pyswmm can read the file without errors
7. **Timestep appropriateness**: ROUTING_STEP appropriate for chosen routing model

## Common Pitfalls

**FLOW_UNITS mismatch with inputs (SILENT — dt_004)**: The single most dangerous SWMM error. If FLOW_UNITS=CMS but pipe diameters are in mm (e.g., 600 instead of 0.6), areas in m2 (instead of hectares), or rainfall in inches (instead of mm), SWMM runs without error but every result is wrong. Always verify dimensional consistency.

**INP encoding issues (dt_013)**: The INP file must be ASCII or UTF-8 without BOM. Some text editors add BOM markers or use non-ASCII characters in comments, causing SWMM to fail with cryptic parse errors.

**Missing TIMESERIES for outfall boundary (dt_020)**: If an outfall type is TIMESERIES but the referenced time series is not defined or does not cover the simulation period, SWMM either crashes or uses the last known value for the remainder, producing wrong boundary conditions.

**Dry weather flow missing for combined sewers (dt_012)**: Combined sewer models must have [DWF] entries for sanitary base flow. Without DWF, the model underestimates dry-weather flow and overestimates available pipe capacity.

**Section order**: While SWMM is mostly flexible about section order, some parsers expect [OPTIONS] early in the file. Follow the conventional order listed above.

**Date format**: SWMM uses MM/DD/YYYY (US format), NOT DD/MM/YYYY or YYYY-MM-DD. The wrong format causes a parse error or misinterpreted dates.

## Tools Reference

| Tool ID | Script | Purpose |
|---------|--------|---------|
| `assemble_inp_file` | `tools/s5_model_assembly/assemble_inp_file.py` | Merge all data into INP file |
| `configure_simulation_options` | `tools/s5_model_assembly/configure_simulation_options.py` | Set [OPTIONS] parameters |
| `validate_inp_file` | `tools/s5_model_assembly/validate_inp_file.py` | Cross-check INP internal consistency |
