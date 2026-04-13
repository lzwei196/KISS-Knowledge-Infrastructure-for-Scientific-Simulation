# Stage 0: Configuration — Process Selection and Simulation Setup

## Purpose

Select the appropriate OGS process type for the physical problem, define the simulation domain extent and period, and identify required input data. This stage produces no files — it establishes decisions that constrain all downstream stages.

## Inputs

- **Physical problem description**: What needs to be simulated (groundwater flow, heat transport, deformation, etc.)
- **Domain geometry**: Spatial extent, dimension (1D/2D/3D), geological structure
- **Simulation period**: Start time, end time, desired timestep resolution
- **Available data**: Mesh, boundary conditions, material properties, observations

## Outputs

- **Process type selection**: One of 15+ OGS process type enumerations
- **Dimension**: 1D, 2D, or 3D (determines mesh, body force vector, element types)
- **Coupling scheme**: Monolithic (all variables solved together) or staggered (sequential coupling)
- **Time scope**: t_initial and t_end in seconds (SI)

## Procedure

### Step 1: Identify the dominant physics

| If you need... | Use process type | Primary variables |
|----------------|-----------------|-------------------|
| Saturated groundwater flow | `LIQUID_FLOW` | pressure (Pa) |
| Unsaturated zone flow | `RICHARDS_FLOW` | pressure (Pa, negative = suction) |
| Steady-state head distribution | `STEADY_STATE_DIFFUSION` | pressure (Pa) |
| Soil heat transport | `HEAT_CONDUCTION` | temperature (K) |
| Coupled heat + flow | `HT` | temperature (K), pressure (Pa) |
| Groundwater + deformation | `HYDRO_MECHANICS` | pressure (Pa), displacement (m) |
| Unsaturated + deformation | `RICHARDS_MECHANICS` | pressure (Pa), displacement (m) |
| Heat + unsaturated flow | `THERMO_RICHARDS_FLOW` | temperature (K), pressure (Pa) |
| Full THMC | `TH2M` | gas pressure, cap. pressure, T, displacement |

### Step 2: Determine dimension and mesh requirements

- **1D**: Column models (vertical infiltration, well drawdown along axis)
- **2D**: Cross-sections, plan-view aquifers (most common for regional GW)
- **3D**: Full subsurface volumes (CO2 storage, geothermal, mining)

Mesh format: VTU (VTK Unstructured Grid). Can be generated with Gmsh, SALOME, or OGS MeshLib utilities. Boundary submeshes must be separate VTU files.

### Step 3: Convert time to seconds

OGS uses seconds exclusively for time. Common conversions:
- 1 hour = 3,600 s
- 1 day = 86,400 s
- 1 month ≈ 2,592,000 s (30 days)
- 1 year ≈ 31,536,000 s (365 days)
- 10 years ≈ 315,360,000 s

### Step 4: Choose solver strategy

- **Picard** (fixed-point iteration): Robust, slow convergence. Use for initial testing.
- **Newton**: Quadratic convergence, but requires good initial guess. Use for production.
- **Staggered coupling**: For multi-physics, solve each variable in sequence per timestep.

## Verification

- [ ] Process type matches the physics being modeled
- [ ] Dimension matches the available mesh
- [ ] Time values converted to seconds
- [ ] Solver type selected (Picard for testing, Newton for production)

## Traps

| Trap | Consequence | Prevention |
|------|-------------|------------|
| Using `LIQUID_FLOW` for unsaturated zone | No capillary effects, wrong answer | Use `RICHARDS_FLOW` |
| Forgetting body force for flow | No gravity-driven flow | Add `<specific_body_force>` |
| Wrong dimension count in body force | Crash or wrong gravity direction | Match mesh dimension exactly |
| Time in days instead of seconds | 86,400× shorter simulation | Always convert to seconds |

## Example

For a 2D cross-section groundwater flow problem over 1 year:

```
Process: LIQUID_FLOW
Dimension: 2D
t_initial: 0
t_end: 31536000  (365 × 86400)
delta_t: 86400  (daily timesteps)
Solver: Picard (10 iterations max)
Body force: "0 -9.81"  (2D: x=0, y=-g)
```
