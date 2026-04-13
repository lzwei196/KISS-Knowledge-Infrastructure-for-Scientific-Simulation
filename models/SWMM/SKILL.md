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
