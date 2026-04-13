# HydroCraft Model Coupling — Skill Document

> **Stage ID**: s7_model_coupling
> **Pipeline order**: 7 of 7
> **Depends on**: s6_execution (and VIC/CaMa-Flood simulations from HydroCraft)

## Purpose

SWMM models urban drainage at the neighborhood-to-city scale (0.01-100 km2). HydroCraft's VIC and CaMa-Flood models operate at watershed scale (100-1,000,000 km2). Coupling these models enables integrated rural-urban flood modeling: rural watershed runoff entering urban areas, urban drainage discharging to rivers, and river flooding backwater-flooding urban outfalls.

This stage implements four coupling pathways between SWMM and HydroCraft:

1. **VIC to SWMM Inflow**: Rural surface runoff entering the urban drainage network
2. **CaMa-Flood to SWMM Outfall BC**: River stage controlling drainage outfall boundary conditions
3. **SWMM to CaMa-Flood Lateral**: Urban drainage discharge entering river channels
4. **VIC Forcing to SWMM Rainfall**: Shared meteorological forcing for consistency

All couplings involve unit conversions and datum transformations that are SILENT ERROR sources — flow magnitudes wrong by orders of magnitude or water levels with wrong datum produce physically plausible but incorrect results with no error messages.

## Prerequisites

Before starting this stage, verify:

- [ ] VIC simulation completed for the watershed containing the urban study area
- [ ] CaMa-Flood simulation completed (if river boundary conditions are needed)
- [ ] SWMM model built and validated (S1-S5 complete)
- [ ] SWMM FLOW_UNITS is known (CMS or CFS)
- [ ] VIC grid resolution and cell areas are known
- [ ] Datum relationship between SWMM local datum and CaMa-Flood global datum is known
- [ ] Temporal resolution compatibility: VIC daily, CaMa-Flood daily or sub-daily, SWMM seconds-to-minutes
- [ ] Python environment has: xarray, netCDF4, numpy, pandas

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| VIC flux output | directory | VIC simulation | Daily runoff + baseflow per grid cell |
| VIC grid NC | file | VIC setup | Grid cell coordinates and areas |
| CaMa-Flood output | directory | CaMa simulation | River stage (sfcelv) time series |
| SWMM INP/OUT/RPT | files | SWMM simulation | Model and results files |
| Coupling mapping | config | User definition | Which VIC cells map to which SWMM nodes |
| Datum offset | number | Survey/DEM | Elevation offset between CaMa and SWMM datums |

## Procedure

### Step 1: VIC Runoff to SWMM Junction Inflow

This coupling represents rural watershed runoff entering the urban drainage system. VIC grid cells adjacent to or surrounding the urban area produce surface runoff and baseflow that becomes external inflow at SWMM junction nodes.

**Unit conversion (CRITICAL — dt_010)**:

VIC outputs runoff in mm/day per grid cell. SWMM expects flow in m3/s (CMS) or ft3/s (CFS):

```
For CMS:
Q(m3/s) = runoff(mm/day) * cell_area(m2) / (1000 * 86400)
         = runoff(mm/day) * cell_area(m2) / 86400000

For CFS:
Q(ft3/s) = Q(m3/s) * 35.3147
```

Example: VIC cell with runoff = 5 mm/day, cell area = 6.25e8 m2 (0.25-degree at 30N):
```
Q = 5 * 6.25e8 / 86400000 = 36.2 m3/s
```

**Common unit errors**:
- Forgetting /1000 (mm to m): flow is 1000x too large
- Forgetting /86400 (day to seconds): flow is 86400x too large
- Using grid cell area in km2 instead of m2: flow is 1e6x too small

```bash
python tools/s7_model_coupling/convert_vic_runoff_to_swmm_inflow.py \
  --vic_result_dir outputs/vic_run/vic_result \
  --vic_grid_nc outputs/vic_run/vic_temp/grid/basin_grid.nc \
  --mapping_config '[{"vic_cell": "31.125_121.375", "junction": "J_boundary_1"}]' \
  --start_date 2020-01-01 \
  --end_date 2020-12-31 \
  --flow_units CMS \
  --output_dir outputs/swmm_run/coupling/
```

**Temporal disaggregation**: VIC produces daily values. SWMM may run at 5-minute timestep. The tool disaggregates daily values to sub-daily using either:
- Uniform distribution (simple: spread daily value evenly)
- SCS temporal distribution (more realistic: daily pattern following SCS curve)
- Hourly VIC forcing (if VIC was run with hourly output, NASA POWER)

**Spatial mapping**: Each VIC grid cell maps to one or more SWMM junction nodes. Multiple VIC cells can contribute to the same junction (summed) or one VIC cell can be split among multiple junctions (area-weighted).

The output includes an `[INFLOWS]` section ready to paste into the INP file:
```
[INFLOWS]
;;Node          Constituent  Time Series              Type    Mfactor Sfactor Baseline Pattern
J_boundary_1    FLOW         VIC_inflow_Jboundary1    FLOW    1.0     1.0     0
```

### Step 2: CaMa-Flood Stage to SWMM Outfall Boundary Condition

This coupling represents the receiving river's water level affecting the drainage outfall. During floods, high river stage prevents drainage discharge (backwater effect), causing urban flooding from the downstream end.

**Datum alignment (CRITICAL — dt_015)**:

CaMa-Flood outputs water surface elevation (sfcelv) in meters above mean sea level (global datum). SWMM uses a local datum that may differ from MSL. The datum offset must be known and applied:

```
SWMM_stage = CaMa_sfcelv - datum_offset
```

Where `datum_offset` = CaMa_datum_elevation - SWMM_datum_elevation at the outfall location.

If the datum offset is wrong, the boundary condition is shifted vertically. This produces physically plausible results (water does flow, outfalls do work) but the backwater effects are at the wrong level — flooding may be triggered too early or too late. There is NO error message. This is one of the most insidious coupling errors.

To determine datum offset:
1. Compare DEM elevation at the outfall with the junction invert elevation in SWMM
2. If SWMM was built with elevations relative to MSL, offset = 0
3. If SWMM uses an arbitrary local datum (common in municipal models), measure the difference

```bash
python tools/s7_model_coupling/convert_cama_stage_to_outfall_bc.py \
  --cama_output_dir model/cmf_v420_pkg/out/basin_run \
  --cama_grid_cell "[31.23, 121.47]" \
  --outfall_id OF1 \
  --datum_offset_m 0.0 \
  --start_year 2020 --end_year 2020 \
  --output_file outputs/swmm_run/coupling/outfall_bc_OF1.dat
```

Update the INP file to use this boundary condition:
```
[OUTFALLS]
;;Name  Elevation  Type        Gated  RouteTo  Data
OF1     8.0        TIMESERIES  NO     *        CaMa_stage_OF1
```

**Temporal interpolation**: CaMa-Flood produces daily output. SWMM reads boundary conditions at each routing timestep. SWMM linearly interpolates between time series data points. For rapidly rising rivers, daily CaMa output may miss the peak stage — consider running CaMa with sub-daily output (1-hour) for flood events.

### Step 3: SWMM Outfall Discharge to CaMa-Flood Lateral Inflow

This coupling represents urban drainage discharge entering the river channel. SWMM outfall discharge becomes CaMa-Flood lateral inflow at the grid cell containing the outfall.

```bash
python tools/s7_model_coupling/convert_swmm_outflow_to_cama_lateral.py \
  --swmm_out_file outputs/swmm_run/model.out \
  --outfall_ids '["OF1", "OF2"]' \
  --cama_grid_cells '{"OF1": [31.23, 121.47], "OF2": [31.25, 121.50]}' \
  --flow_units CMS \
  --cama_timestep daily \
  --output_dir outputs/swmm_run/coupling/
```

**Unit conversion**: SWMM flow is in FLOW_UNITS. CaMa-Flood expects m3/s. If FLOW_UNITS=CMS, no conversion needed. If FLOW_UNITS=CFS, multiply by 0.0283168 to convert to m3/s.

**Temporal aggregation**: SWMM produces results at REPORT_STEP intervals (typically 5 minutes). CaMa-Flood uses daily or hourly timesteps. Aggregate SWMM discharge to CaMa timestep by averaging.

**Spatial mapping**: Each SWMM outfall maps to one CaMa-Flood grid cell. Multiple outfalls can contribute to the same CaMa cell (summed).

### Step 4: Validate Coupling Water Balance

```bash
python tools/s7_model_coupling/validate_coupling_water_balance.py \
  --vic_result_dir outputs/vic_run/vic_result \
  --swmm_rpt_file outputs/swmm_run/model.rpt \
  --swmm_inflow_files '["outputs/swmm_run/coupling/inflow_Jboundary1.dat"]' \
  --cama_lateral_file outputs/swmm_run/coupling/swmm_lateral_inflow.nc \
  --vic_grid_nc outputs/vic_run/vic_temp/grid/basin_grid.nc
```

Water balance checks:
1. **VIC-to-SWMM**: Total VIC runoff volume for mapped cells = total SWMM external inflow volume (within 1%)
2. **SWMM internal**: Total inflow (rainfall + external) = total outflow + storage change + evaporation + continuity error
3. **SWMM-to-CaMa**: Total SWMM outfall discharge volume = total CaMa lateral inflow volume (within 1%)
4. **End-to-end**: No mass creation or destruction at coupling interfaces

## Expected Outputs

| Output | Path Pattern | Description |
|--------|-------------|-------------|
| SWMM inflow time series | `{coupling_dir}/inflow_*.dat` | VIC runoff as SWMM external inflow |
| SWMM INP INFLOWS section | `{coupling_dir}/inflows_section.txt` | Ready-to-paste INP section |
| Outfall BC time series | `{coupling_dir}/outfall_bc_*.dat` | CaMa stage as SWMM boundary |
| CaMa lateral inflow NC | `{coupling_dir}/swmm_lateral_inflow.nc` | SWMM discharge for CaMa |
| Water balance report | (stdout/JSON) | Volume comparison at interfaces |

## Validation Checks

1. **Volume conservation at VIC-SWMM interface**: < 1% error
2. **Volume conservation at SWMM-CaMa interface**: < 1% error
3. **Datum offset physically reasonable**: Typically 0-20 meters, consistent with DEM comparison
4. **Flow magnitudes reasonable**: SWMM inflows should be consistent with VIC runoff rates
5. **No negative flows**: All external inflows >= 0
6. **Temporal coverage**: All time series cover the simulation period
7. **Unit consistency**: Flows in correct FLOW_UNITS, stages in correct length units

## Common Pitfalls

**VIC-to-SWMM unit conversion error (SILENT — dt_010)**: The most common coupling error. Missing the /1000 (mm to m) or /86400 (day to seconds) factor produces flows that are 3-5 orders of magnitude wrong. Validate by comparing the VIC runoff volume (mm * area) against the SWMM inflow volume (m3/s * time).

**CaMa-SWMM datum mismatch (SILENT — dt_015)**: If SWMM uses a local datum (common in US municipal models), the CaMa MSL-referenced stage must be adjusted. A 2-meter datum offset error means SWMM sees river stage as 2m higher or lower than reality. During flood events, this means the difference between flooding and no flooding.

**Temporal resolution mismatch**: VIC daily, CaMa daily, SWMM 5-minute. When disaggregating daily VIC to 5-minute SWMM, the temporal pattern within the day matters. Uniform disaggregation (Q_5min = Q_daily / 288) smooths out the runoff peak. For flood applications, consider running VIC with hourly output and using the diurnal pattern for disaggregation.

**Spatial misalignment**: VIC and CaMa operate on different grids (VIC: 0.1-0.25 degree; CaMa: 0.25 degree / 15 arc-minutes). The SWMM domain is typically 1-100 km2 within a single VIC/CaMa cell. Ensure the correct VIC/CaMa cell is selected for coupling.

**Circular coupling without iteration**: In a fully coupled system, SWMM discharge affects CaMa river stage, which affects SWMM outfall BC, which affects SWMM discharge. One-way coupling (VIC/CaMa -> SWMM) is sufficient for most applications. Two-way coupling (iterative SWMM <-> CaMa) is needed only when SWMM discharge is a significant fraction of river flow at the outfall. For large rivers receiving small urban drainage, one-way coupling is fine.

**Missing VIC cells in mapping**: If the mapping_config omits VIC cells that contribute flow to the urban boundary, the SWMM model receives less external inflow than it should. The model runs fine but underestimates flooding. Always verify that the VIC cells mapped to SWMM boundary nodes fully represent the upstream contributing area.

## Tools Reference

| Tool ID | Script | Purpose |
|---------|--------|---------|
| `convert_vic_runoff_to_swmm_inflow` | `tools/s7_model_coupling/convert_vic_runoff_to_swmm_inflow.py` | VIC runoff to SWMM junction inflow |
| `convert_cama_stage_to_outfall_bc` | `tools/s7_model_coupling/convert_cama_stage_to_outfall_bc.py` | CaMa stage to SWMM outfall BC |
| `convert_swmm_outflow_to_cama_lateral` | `tools/s7_model_coupling/convert_swmm_outflow_to_cama_lateral.py` | SWMM outflow to CaMa lateral inflow |
| `validate_coupling_water_balance` | `tools/s7_model_coupling/validate_coupling_water_balance.py` | Verify water balance at coupling interfaces |
