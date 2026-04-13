# S5: Input Deck Assembly

## Purpose

Assemble all components (grid, materials, BCs, initial conditions, output
settings) into a complete PFLOTRAN input deck (.in file). This stage validates
cross-references between blocks and ensures physical consistency.

## Inputs

| Input | Format | Source |
|---|---|---|
| Grid specification | PFLOTRAN blocks | s1_grid_generation |
| Material properties | JSON + blocks | s2_material_properties |
| Boundary conditions | PFLOTRAN blocks + datasets | s3_forcing_boundary |
| Initial conditions | Manual / computed | s4_initial_conditions |
| Output configuration | User specification | Manual |

## Outputs

| Output | Format | Used By |
|---|---|---|
| Complete input deck | `.in` file | s6_execution |
| Configuration log | JSON | Diagnostics |

## Procedure

### Step 1: Define Simulation Type

```
SIMULATION
  SIMULATION_TYPE SUBSURFACE
  PROCESS_MODELS
    SUBSURFACE_FLOW flow
      MODE RICHARDS          ! or GENERAL, TH
      OPTIONS
        ! STEADY_STATE       ! uncomment for steady-state
      /
    /
  /
END
```

Available modes:
- `RICHARDS`: Variably saturated single-phase (most common for groundwater)
- `GENERAL`: Multiphase (water + gas), phase transitions
- `TH`: Coupled thermal-hydrologic

### Step 2: Assemble Blocks in Order

PFLOTRAN input decks follow this conventional order:

1. `SIMULATION` — simulation type and process models
2. `SUBSURFACE` — begin subsurface block
3. `GRID` — mesh definition
4. `FLUID_PROPERTY` — water properties
5. `MATERIAL_PROPERTY` — for each material
6. `CHARACTERISTIC_CURVES` — for each curve set
7. `OUTPUT` — what to write, when, format
8. `TIME` — simulation time control
9. `REGION` — named spatial regions
10. `OBSERVATION` — monitoring points (optional)
11. `FLOW_CONDITION` — flow boundary/initial conditions
12. `TRANSPORT_CONDITION` — solute conditions (if reactive)
13. `INITIAL_CONDITION` — assign flow/transport IC to region
14. `BOUNDARY_CONDITION` — assign flow/transport BC to region
15. `SOURCE_SINK` — wells (optional)
16. `STRATA` — assign materials to regions
17. `END_SUBSURFACE`

### Step 3: Time Control

```
TIME
  FINAL_TIME 10.d0 y
  INITIAL_TIMESTEP_SIZE 1.d-3 y
  MAXIMUM_TIMESTEP_SIZE 0.1 y
END
```

**TRAP dt_010**: If FINAL_TIME uses the wrong unit keyword, the simulation
length is wrong by orders of magnitude. Always use the unit suffix (`s`, `h`,
`d`, `y`).

### Step 4: Output Configuration

```
OUTPUT
  TIMES y 0.25 0.5 1.0 2.0 5.0 10.0
  FORMAT HDF5
  VELOCITY_AT_CENTER
  VARIABLES
    LIQUID_PRESSURE
    LIQUID_SATURATION
  /
  OBSERVATION_FILE
    PERIODIC TIME 1.d0 d
  /
END
```

### Step 5: Initial Conditions

For groundwater, use HYDROSTATIC:

```
FLOW_CONDITION initial
  TYPE
    LIQUID_PRESSURE HYDROSTATIC
  /
  DATUM 0.d0 0.d0 25.d0      ! water table at z=25m
  LIQUID_PRESSURE 101325.d0   ! atmospheric at datum
END

INITIAL_CONDITION
  FLOW_CONDITION initial
  REGION all
END
```

The DATUM specifies where the water table is. Below datum: fully saturated.
Above datum: pressure decreases (suction), saturation from vG curve.

### Step 6: Cross-Reference Validation

Before writing, verify:

| Check | Requirement |
|---|---|
| MATERIAL ↔ CHARACTERISTIC_CURVES | Each material references an existing CC |
| STRATA ↔ REGION | Each strata references existing region and material |
| BOUNDARY_CONDITION ↔ REGION | BC regions are face-type regions |
| INITIAL_CONDITION ↔ REGION | IC region covers entire domain |
| FLOW_CONDITION ↔ FILE | Referenced dataset files exist |
| OBSERVATION ↔ REGION | Obs regions are point or small volume |

## Verification

1. Run `pflotran -pflotranin input.in -stochastic_test` for syntax check
2. Check that all REGIONs referenced actually exist
3. STRATA covers the entire domain (no unassigned cells)
4. At least one INITIAL_CONDITION for each process
5. BOUNDARY_CONDITION regions are face-type (FACE keyword)
6. No circular dependencies between blocks

## Traps

| Symptom | Cause | Fix |
|---|---|---|
| "Region X not found" | Typo in region name | Match names exactly (case-sensitive) |
| "Material Y not found" | Missing MATERIAL_PROPERTY block | Add block before STRATA |
| No output produced | Missing OUTPUT block or wrong FORMAT | Add FORMAT HDF5 |
| Solver diverges at t=0 | Inconsistent IC and BC | Use HYDROSTATIC for IC |
| "Error reading input" | Fortran parsing issue | Check block nesting, use `END` or `/` consistently |

## Example

Minimal complete input deck for Bengbu Basin:

```
SIMULATION
  SIMULATION_TYPE SUBSURFACE
  PROCESS_MODELS
    SUBSURFACE_FLOW flow
      MODE RICHARDS
    /
  /
END

SUBSURFACE

GRID
  TYPE STRUCTURED
  NXYZ 50 50 10
  BOUNDS
    0.d0 0.d0 0.d0
    25000.d0 25000.d0 50.d0
  /
END

! ... material, characteristic curves, regions ...
! ... flow conditions, IC, BC, strata ...

TIME
  FINAL_TIME 10.d0 y
  INITIAL_TIMESTEP_SIZE 1.d-2 y
  MAXIMUM_TIMESTEP_SIZE 0.5 y
END

OUTPUT
  TIMES y 1.0 2.0 5.0 10.0
  FORMAT HDF5
  VARIABLES
    LIQUID_PRESSURE
    LIQUID_SATURATION
  /
END

END_SUBSURFACE
```
