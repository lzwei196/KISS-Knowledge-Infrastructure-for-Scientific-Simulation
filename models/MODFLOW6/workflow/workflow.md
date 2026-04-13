# MODFLOW 6 Workflow

## Pipeline Overview

MODFLOW 6 is the USGS standard for 3D finite-difference groundwater flow modeling. This workflow builds a complete simulation using FloPy as the Python interface and the mf6 Fortran binary as the solver.

### Stage Dependency Graph

```
S1 Installation
  |
  v
S2 Grid/Discretization (DIS)
  |
  +--> S3 Layer Properties (NPF, STO)
  |       |
  +--> S4 Boundary Conditions (CHD, WEL, RCH, DRN, RIV, EVT)
          |
          v
        S5 Stress Periods & IC (TDIS, IC)
          |
          v
        S6 Solver (IMS)
          |
          v
        S7 Execution (write + run mf6)
          |
          v
        S8 Output Extraction (heads, budget)
          |
          v
        S9 Postprocessing & Visualization
```

### Stage Summary

| # | Stage | Skill Document | Tools | Key Output |
|---|-------|---------------|-------|------------|
| 1 | Installation | `s1_installation_skill.md` | `verify_mf6_installation` | mf6 binary on PATH, FloPy importable |
| 2 | Grid & Discretization | `s2_grid_discretization_skill.md` | `create_grid_from_basin`, `build_dis_package` | DIS package with NLAY/NROW/NCOL/IDOMAIN |
| 3 | Layer Properties | `s3_layer_properties_skill.md` | `build_npf_package`, `build_sto_package` | NPF (K, ICELLTYPE) + STO (Ss, Sy) |
| 4 | Boundary Conditions | `s4_boundary_conditions_skill.md` | `build_chd/rch/riv/drn/wel_package` | Stress packages |
| 5 | Stress Periods & IC | `s5_stress_periods_skill.md` | `build_tdis/ic_package`, `assign_transient_stress` | TDIS + IC + transient data |
| 6 | Solver | `s6_solver_skill.md` | `build_ims_package` | IMS with convergence criteria |
| 7 | Execution | `s7_execution_skill.md` | `write_and_run_simulation` | mfsim.lst, .hds, .cbc |
| 8 | Output Extraction | `s8_output_extraction_skill.md` | `extract_heads`, `extract_budget` | Head arrays, budget terms |
| 9 | Postprocessing | `s9_postprocessing_skill.md` | `plot_head_map`, `plot_water_budget`, `export_to_netcdf` | PNG plots, NetCDF for coupling |

### Parallelism

- **S3 and S4 can run in parallel** (both depend only on S2)
- **S5 depends on both S3 and S4** (needs layer properties and boundary conditions to be defined)
- All other stages are sequential

### Diagnostic Triplets Coverage

| Failure Domain | Triplet IDs | Stages Affected |
|---------------|-------------|-----------------|
| Runtime | dt_mf6_001, dt_mf6_002, dt_mf6_009 | S6, S7 |
| Silent Error | dt_mf6_003, dt_mf6_008, dt_mf6_010, dt_mf6_014, dt_mf6_015 | S3, S4, S8 |
| Unit Conversion | dt_mf6_004, dt_mf6_013 | S4 |
| Parameter Format | dt_mf6_005, dt_mf6_006 | S2, S8 |
| Environment | dt_mf6_007 | S1 |
| Path Resolution | dt_mf6_012 | S7 |
| Dependency Mismatch | dt_mf6_011, dt_mf6_013 | S4, S5 |

## MODFLOW 6 File Structure

A complete simulation workspace contains:

```
workspace/
  mfsim.nam           # Simulation name file (lists models, solutions, TDIS)
  gwf.nam             # GWF model name file (lists packages)
  gwf.tdis            # Temporal discretization
  gwf.ims             # Iterative model solution
  gwf.dis             # Structured discretization
  gwf.npf             # Node property flow (K)
  gwf.sto             # Storage (Ss, Sy) — transient only
  gwf.ic              # Initial conditions
  gwf.oc              # Output control
  gwf.chd             # Constant head — if used
  gwf.wel             # Wells — if used
  gwf.rch             # Recharge — if used
  gwf.drn             # Drains — if used
  gwf.riv             # Rivers — if used
  gwf.evt             # Evapotranspiration — if used
  gwf.hds             # Binary head output (created by mf6)
  gwf.cbc             # Binary cell budget output (created by mf6)
  mfsim.lst           # Simulation listing file (created by mf6)
  gwf.lst             # Model listing file (created by mf6)
```

## MODFLOW 6 Block/Keyword Input Syntax

All MODFLOW 6 input files use the same block structure:

```
# Comments start with #
BEGIN OPTIONS
  LENGTH_UNITS  meters
  PRINT_INPUT
  PRINT_FLOWS
  SAVE_FLOWS
END OPTIONS

BEGIN DIMENSIONS
  NLAY  3
  NROW  50
  NCOL  100
END DIMENSIONS

BEGIN GRIDDATA
  DELR
    CONSTANT  100.0
  DELC
    CONSTANT  100.0
  TOP
    CONSTANT  50.0
  BOTM  LAYERED
    CONSTANT  40.0
    CONSTANT  10.0
    CONSTANT  -50.0
  IDOMAIN  LAYERED
    INTERNAL  FACTOR  1  IPRN  0
      1 1 1 0 0 ...
END GRIDDATA
```

Key syntax rules:
- Blocks are delimited by `BEGIN <BLOCKNAME>` and `END <BLOCKNAME>`
- Keywords are case-insensitive
- `CONSTANT <value>` sets all cells in a layer to the same value
- `INTERNAL FACTOR <factor>` precedes inline array data
- `OPEN/CLOSE <filename>` reads array from external file
- `LAYERED` indicates data provided per-layer
- Stress period data blocks: `BEGIN PERIOD <n>` ... `END PERIOD`

## HydroCraft Integration Points

### Coupling 1: VIC -> MODFLOW (Recharge)
VIC computes deep percolation (baseflow_out, mm/day) for each grid cell. This becomes MODFLOW RCH input after:
1. Spatial regridding from VIC grid to MODFLOW grid
2. Unit conversion: mm/day / 1000 = m/day
3. Temporal aggregation: VIC daily -> MODFLOW stress period

### Coupling 2: MODFLOW -> Routing (Baseflow)
MODFLOW DRN package computes groundwater discharge to drains/streams. This drain flux (m3/day) is added to routing model input as baseflow component.

### Coupling 3: CaMa-Flood -> MODFLOW (River Stage)
CaMa-Flood computes river surface elevation (sfcelv, m). This is used as the stage in MODFLOW RIV package cells to drive groundwater-surface water exchange.

### Coupling 4: MODFLOW -> VIC (Water Table Feedback)
MODFLOW water table depth can modify VIC soil moisture capacity. When the water table is shallow, it reduces available soil storage and increases runoff. This requires iterative coupling.

---

*Generated by the Knowledge Dissection Toolkit v1.0*
