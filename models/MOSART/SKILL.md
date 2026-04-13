> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model.
>
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

# MOSART-WM (mosartwmpy) — Knowledge Infrastructure

**Package**: `hydrocraft-mosartwmpy-routing` v1.0.0
**Model**: mosartwmpy (Python translation of MOSART-WM)
**Repository**: https://github.com/IMMM-SFA/mosartwmpy
**Created by**: IMMM-SFA / PNNL (Travis Thurber et al.)
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 20 diagnostic triplets | ~2,500 lines of validated Python
**Validation status**: `infrastructure_complete`

---

## Overview

This knowledge infrastructure enables autonomous river routing and water management simulation using mosartwmpy. The 4 validated tools replace manual data preparation with a Python pipeline that integrates directly with HydroCraft's forcing, land surface, and reservoir infrastructure.

**What MOSART-WM does**: Grid-based river routing and water management model. Simulates:
- Hillslope overland flow (Manning's equation on hillslope surface)
- Subnetwork/tributary channel routing (Manning's equation in tributaries)
- Main channel routing (kinematic wave approximation)
- Reservoir regulation (storage-based release rules)
- ISTARF improved reservoir scheduling (statistical target release functions)
- Irrigation water supply/demand allocation (iterative dam-to-grid supply)
- Water balance tracking (storage, deficit, supply across all grid cells)
- Flood routing (excess storage returned to ocean)

**Key difference from other HydroCraft models**: MOSART-WM operates on a regular lat/lon grid (e.g., NLDAS 1/8°) with a full river network topology. It implements the Basic Model Interface (BMI) for coupling with CLM, VIC, or other land surface models. It routes runoff from hillslopes through tributaries and main channels to ocean outlets, with integrated reservoir operations.

**Three-tier routing**: Hillslope → Subnetwork (tributaries) → Main Channel. Each tier has its own Manning's coefficient, slope, width, and routing time step determined by CFL-like stability criteria.

---

## Installation

### From PyPI

```bash
pip install mosartwmpy
```

### From conda-forge

```bash
conda install -c conda-forge mosartwmpy
```

### From source

```bash
git clone https://github.com/IMMM-SFA/mosartwmpy.git
cd mosartwmpy
pip install -e .
```

### Python requirements

```
Python 3.9 - 3.12
bmipy>=2.0, numba>=0.53.1, numpy>=1.20.3,<2.0
xarray>=0.19.0, netCDF4>=1.5.7, pandas>=1.3.4
dask[complete]>=2021.10.0, pyarrow>=6.0.0
python-benedict>=0.24.3, click>=8.0.1
matplotlib>=3.4.3, rioxarray>=0.8.0, psutil>=5.8.0
regex>=2021.10.23, pathvalidate>=2.5.0, h5netcdf>=0.11.0
pyomo>=6.2, geopandas>=0.10.2
```

### Test data download

```bash
python -m mosartwmpy.download
# Select option 1 for "tutorial" (May 1981 CONUS subset)
# Select option 2 for "sample_input" (1980-1985 full dataset)
# Select option 3 for "validation" (1981-1982 reference results)
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 1 | Runoff forcing | `convert_runoff_forcing.py` | CLM/VIC/Livneh runoff to mosartwmpy NetCDF (mm/s) |
| 2 | Grid preparation | `convert_grid_parameters.py` | Domain grid file with river network topology |
| 3 | Demand preparation | (manual or ABM) | Water demand NetCDF (m3/s totalDemand) |
| 4 | Reservoir setup | `create_grand_parameters` (CLI) | GRanD reservoir parameters + ISTARF coefficients |
| 5 | Configuration | config.yaml | Simulation name, dates, paths, WM toggle |
| 6 | Execution | `run_mosartwmpy.py` | BMI initialize → update_until → finalize |
| 7 | Output parsing | `parse_mosart_output.py` | Extract discharge, storage, supply to CSV |

### Stage Dependencies

```
Stages 1, 2, 3, 4 can run in parallel (independent data prep)
Stage 5 depends on 1-4 (paths must exist)
Stage 6 depends on 5
Stage 7 depends on 6
```

---

## Input Specification

### Grid Domain File (NetCDF)

| Variable | Field Name | Units | Description |
|----------|-----------|-------|-------------|
| Cell ID | `ID` | - | Unique integer identifier |
| Downstream ID | `dnID` | - | ID of downstream cell (-1 for outlet) |
| Flow direction | `fdir` | - | D8 flow direction code |
| Latitude | `lat` | degrees_north | Cell center latitude |
| Longitude | `lon` | degrees_east | Cell center longitude |
| Local drainage area | `area` | m² | Grid cell drainage area |
| Total upstream area (multi) | `areaTotal` | m² | Multi-flow-direction upstream area |
| Total upstream area (single) | `areaTotal2` | m² | Single-flow-direction upstream area |
| Drainage fraction | `frac` | 0-1 | Fraction of cell draining to outlet |
| Land fraction | `frac` | 0-1 | Land fraction of grid cell |
| Drainage density | `gxr` | m⁻¹ | Channel density per unit area |
| Hillslope slope | `hslp` | m/m | Mean topographic slope |
| Hillslope Manning's n | `nh` | s/m^(1/3) | Overland flow roughness |
| Subnetwork slope | `tslp` | m/m | Mean tributary slope |
| Subnetwork width | `twid` | m | Bankfull tributary width |
| Subnetwork Manning's n | `nt` | s/m^(1/3) | Tributary roughness |
| Channel length | `rlen` | m | Main channel length |
| Channel slope | `rslp` | m/m | Main channel slope |
| Channel width | `rwid` | m | Bankfull main channel width |
| Floodplain width | `rwid0` | m | Floodplain width linked to channel |
| Channel depth | `rdep` | m | Bankfull main channel depth |
| Channel Manning's n | `nr` | s/m^(1/3) | Main channel roughness |

### Runoff Forcing File (NetCDF)

| Variable | Field Name | Units | Description |
|----------|-----------|-------|-------------|
| Surface runoff | `QOVER` | mm/s | Surface runoff flux |
| Subsurface runoff | `QDRAI` | mm/s | Subsurface drainage flux |
| Wetland runoff | (optional) | mm/s | Glacier/wetland/lake runoff |
| Time | `time` | datetime | Time coordinate |
| Latitude | `lat` | degrees_north | Grid latitudes |
| Longitude | `lon` | degrees_east | Grid longitudes |

**CRITICAL UNIT TRAP**: Runoff is read as mm/s. Internally converted to m³/s via:
```
Q_m3s = 0.001 × land_fraction × area_m2 × Q_mm_s
```
Then to m/s for hillslope routing:
```
Q_m_s = Q_m3s / area_m2
```

### Demand File (NetCDF)

| Variable | Field Name | Units | Description |
|----------|-----------|-------|-------------|
| Total demand | `totalDemand` | m³/s | Grid cell water demand rate |
| Time | `time` | datetime | Monthly time coordinate |

### Reservoir Files

| File | Format | Key Fields |
|------|--------|------------|
| `reservoirs.nc` | NetCDF | GRAND_ID, GRID_CELL_INDEX, CAP_MCM (million m³), AREA_SKM (km²), DAM_HGT_M |
| `dependency_database.parquet` | Parquet | DEPENDENT_CELL_INDEX, GRAND_ID, RESERVOIR_CELL_INDEX |
| `mean_monthly_reservoir_flow.parquet` | Parquet | GRAND_ID, MONTH_INDEX, MEAN_FLOW (m³/s) |
| `mean_monthly_reservoir_demand.parquet` | Parquet | GRAND_ID, MONTH_INDEX, MEAN_DEMAND (m³/s) |

**CRITICAL UNIT TRAP**: Reservoir storage capacity in input is **million m³** (CAP_MCM). Surface area is **km²** (AREA_SKM). These are converted internally.

---

## Output Specification

### Default Output (NetCDF, monthly files, daily averages)

| Variable | Name in File | Units | Description |
|----------|-------------|-------|-------------|
| Surface runoff | `QSUR_LIQ` | m³/s | Hillslope surface runoff |
| Subsurface runoff | `QSUB_LIQ` | m³/s | Hillslope subsurface runoff |
| Total storage | `STORAGE_LIQ` | m³ | Total routing storage |
| River discharge | `RIVER_DISCHARGE_OVER_LAND_LIQ` | m³/s | Main channel outflow |
| Channel inflow | `channel_inflow` | m³/s | Upstream inflow to grid cell |
| Channel outflow | `channel_outflow` | m³/s | Outflow from grid cell |
| Reservoir storage | `WRM_STORAGE` | m³ | Water stored in reservoir |
| Water supply | `WRM_SUPPLY` | m³/s | Supply delivered to grid cell |
| Water demand | `WRM_DEMAND` | m³/s | Demand requested by grid cell |
| Unmet demand | `WRM_DEFICIT` | m³ | Cumulative unmet demand |

### BMI Output Variables (programmatic access)

| Standard Name | State Variable | Units |
|---------------|---------------|-------|
| `outgoing_water_volume_transport_along_river_channel` | `runoff_land` | m³/s |
| `incoming_water_volume_transport_along_river_channel` | `channel_inflow_upstream` | m³/s |
| `surface_water_amount` | `storage` | m³ |
| `reservoir_water_amount` | `reservoir_storage` | m³ |
| `supply_water_amount` | `grid_cell_supply` | m³ |
| `deficit_water_amount` | `grid_cell_deficit` | m³ |

### BMI Input Variables

| Standard Name | State Variable | Units |
|---------------|---------------|-------|
| `surface_runoff_flux` | `hillslope_surface_runoff` | mm/s |
| `subsurface_runoff_flux` | `hillslope_subsurface_runoff` | mm/s |
| `demand_flux` | `grid_cell_demand_rate` | m³/s |

---

## Unit Trap Table

| Quantity | External Unit | Internal Unit | Conversion | Where |
|----------|--------------|---------------|------------|-------|
| Runoff (input) | mm/s | m³/s → m/s | ×0.001×frac×area, then ÷area | `load_runoff()`, `_prepare()` |
| Runoff (output) | m/s | m³/s | ×area | `_finalize()` |
| Demand | m³/s | m³ (per substep) | ×Δt_subcycle | `_subcycle()` |
| Supply | m³ (accumulated) | m³/s | ÷timestep | `_finalize()` |
| Reservoir capacity | million m³ | m³ | ×1e6 (in grid loading) | `load_reservoirs()` |
| Reservoir area | km² | m² | ×1e6 (in grid loading) | `load_reservoirs()` |
| Reservoir evaporation | mm/s | m³ | ×1e6×Δt×area_km2 | `regulation()` |
| Channel storage | m³ | m³ | direct | internal |
| Hillslope storage | m | m³ | ×area×frac | `_finalize()` |
| Timestep | seconds | seconds | 10800 default (3 hours) | config |
| Subcycle Δt | seconds | seconds | timestep/subcycles | computed |
| Routing Δt | seconds | seconds | subcycle_Δt/routing_iterations | computed |

---

## Configuration Reference (config.yaml)

### Key Parameters

| Parameter | Default | Units | Description |
|-----------|---------|-------|-------------|
| `simulation.timestep` | 10800 | s | Main timestep (3 hours) |
| `simulation.subcycles` | 3 | - | Number of subcycles per timestep |
| `simulation.routing_iterations` | 5 | - | Routing iterations per subcycle |
| `simulation.output_resolution` | 86400 | s | Output averaging window (daily) |
| `simulation.output_file_frequency` | monthly | - | New file frequency |
| `water_management.enabled` | true | - | Toggle reservoir/demand system |
| `water_management.reservoirs.enable_istarf` | true | - | Toggle ISTARF release rules |
| `grid.subdomain` | null | - | List of lat,lon pairs to subset basins |
| `grid.unmask_output` | true | - | Include inactive cells in output |

### Internal Constants (Parameters class)

| Parameter | Value | Units | Purpose |
|-----------|-------|-------|---------|
| `tiny_value` | 1e-14 | - | Numerical floor |
| `radius_earth` | 6.37122e6 | m | Area computation |
| `hillslope_minimum` | 0.005 | m/m | Replace zero hillslope |
| `subnetwork_slope_minimum` | 0.0001 | m/m | Replace zero tributary slope |
| `channel_slope_minimum` | 0.0001 | m/m | Replace zero channel slope |
| `flood_threshold` | 1e36 | m³ | Flood excess threshold |
| `river_depth_minimum` | 1e-4 | m | Minimum river depth |
| `irrigation_extraction_parameter` | 0.1 | m | Minimum depth for extraction |
| `irrigation_extraction_maximum_fraction` | 0.5 | - | Max fraction extractable |
| `reservoir_flow_volume_ratio` | 0.9 | - | Flow volume available to supply |
| `kinematic_wave_parameter` | 1e6 | - | Kinematic wave condition |

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `convert_runoff_forcing` | s1 | `tools/convert_runoff_forcing.py` | ~200 | VIC/CLM/generic runoff to mosartwmpy NetCDF |
| `convert_grid_parameters` | s2 | `tools/convert_grid_parameters.py` | ~220 | Build grid domain NetCDF with river network |
| `run_mosartwmpy` | s6 | `tools/run_mosartwmpy.py` | ~180 | Execute model via BMI with validation |
| `parse_mosart_output` | s7 | `tools/parse_mosart_output.py` | ~200 | Extract time series from output NetCDF to CSV |

---

## Routing Physics Summary

### Hillslope Routing
- Manning's equation: `v = (depth^(2/3)) × (slope^(1/2)) / n`
- Overland flow: `q = -depth × velocity × drainage_density`
- Storage update: `S(t+Δt) = S(t) + Δt × (runoff_surface + overland_flow)`
- Lateral inflow to subnetwork: `(subsurface_runoff - overland_flow) × frac × area`

### Subnetwork (Tributary) Routing
- Same Manning's equation with tributary geometry
- Adaptive sub-timesteps based on CFL condition (phi parameter)
- Discharge: `q = -velocity × cross_section_area`
- Feeds into main channel as lateral flow

### Main Channel Routing
- Kinematic wave approximation
- Condition: `drainage_area / (width × length) ≤ 1e6`
- If kinematic: `outflow = -velocity × cross_section_area`
- If not kinematic: `outflow = -(inflow + lateral_flow)`
- Channel cross-section: rectangular below bankfull, trapezoidal floodplain above

### Reservoir Regulation
- Storage balance: `S(t+Δt) = S(t) + inflow - outflow - evaporation`
- If excess: release all overflow, fill to capacity
- If insufficient: reduce release to match inflow
- ISTARF: statistical target release based on storage level and month

### Water Supply Allocation (Iterative)
1. Compute flow_volume at each dam (90% of channel outflow)
2. Aggregate demand from all dependent grid cells
3. Compute demand_fraction = available / total_demand
4. Three cases: full supply (fraction ≥ 1), prorated (sum ≥ 1), partial
5. Residual flow returned to channel

---

## Execution Quick Start

```python
from mosartwmpy import Model

model = Model()
model.initialize('config.yaml')

# Run full simulation
model.update_until(model.get_end_time())

# Or step one timestep at a time
model.update()

# Access output via BMI
discharge = model.get_value_ptr('outgoing_water_volume_transport_along_river_channel')
storage = model.get_value_ptr('surface_water_amount')
supply = model.get_value_ptr('supply_water_amount')

model.finalize()
```

---

## Validation

```bash
# Download validation data
python -m mosartwmpy.download  # Select option 3

# Run simulation covering 1981-1982
# Then validate with NMAE comparison
python -m mosartwmpy.validate
```

The validation tool computes Normalized Mean Absolute Error (NMAE) for:
- `STORAGE_LIQ` — total routing storage
- `RIVER_DISCHARGE_OVER_LAND_LIQ` — river discharge
- `WRM_STORAGE` — reservoir storage
- `WRM_SUPPLY` — water supply

NMAE should be 0% if code is unmodified from reference.

---

## Common Pitfalls

1. **Runoff unit confusion**: Input is mm/s, but routing works in m/s and m³/s internally
2. **Reservoir capacity units**: Input CAP_MCM is million m³, not m³
3. **Reservoir area units**: Input AREA_SKM is km², not m²
4. **Timestep stability**: If subcycles too few for large basins, CFL violation causes instability
5. **Multi-file paths**: Use `{Y}`, `{M}`, `{D}` placeholders for year/month/day in paths
6. **Numpy version**: Requires numpy<2.0 due to numba compatibility
7. **Grid orientation**: Lat/lon must match between grid, runoff, and demand files exactly
8. **Subdomain coordinates**: Each pair finds the basin containing that point
9. **Demand timing**: Demand is read monthly, padded to nearest past time
10. **Restart files**: Date parsed from filename pattern `YYYY_MM_DD`
