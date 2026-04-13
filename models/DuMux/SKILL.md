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

# DuMux (DUNE for Multi-Phase/Component/Scale/Physics) — Knowledge Infrastructure

**Package**: `hydrocraft-dumux-groundwater` v1.0.0
**Model**: DuMux 3.11-dev (built on DUNE framework)
**Domain**: Groundwater flow and transport in porous media
**Created by**: Knowledge Dissection Toolkit
**Last updated**: 2026-03-25
**Stats**: 4 tools | 5 skill documents | 18 diagnostic triplets | ~1,500 lines of validated Python
**Validation status**: `example_validated` (1ptracer example, Sparkling-like domain)

---

## Overview

DuMux is a C++ simulation framework for flow and transport in porous media, built on top of the DUNE (Distributed and Unified Numerics Environment) framework. It supports multi-phase, multi-component, multi-scale, and multi-physics simulations using finite volume discretization methods.

**What DuMux does for groundwater**:
- Single-phase Darcy flow (1p model): pressure field, velocity field
- Tracer transport (advection-diffusion): contaminant migration
- Two-phase flow (2p model): water + NAPL or water + air in vadose zone
- Richards equation: variably saturated flow
- Non-isothermal coupling: heat transport in aquifers
- Multi-domain coupling: surface-subsurface, fracture-matrix

**Governing equation (1p model)**:
```
∂(φ ρ)/∂t + ∇·{-ρ (K/μ) (∇p - ρ g)} = q
```
Where:
- φ = porosity [-]
- ρ = fluid density [kg/m³]
- K = intrinsic permeability [m²]
- μ = dynamic viscosity [Pa·s]
- p = pressure [Pa]
- g = gravitational acceleration [m/s²]
- q = source/sink term [kg/(m³·s)]

**Primary variable**: pressure (p) in [Pa]

**Key difference from lumped hydrological models**: DuMux is a physically-based, spatially-distributed PDE solver. It resolves subsurface flow on a computational grid (structured or unstructured) rather than using conceptual storage-discharge relationships.

---

## Installation

### Prerequisites

DuMux requires the DUNE framework (v2.10+). The recommended installation uses the DUNE build system.

```
Required DUNE modules:
  dune-common    >= 2.10
  dune-geometry  >= 2.10
  dune-grid      >= 2.10
  dune-localfunctions >= 2.10
  dune-istl      >= 2.10

Optional DUNE modules:
  dune-alugrid   >= 2.10   (unstructured adaptive mesh)
  dune-foamgrid  >= 2.10   (fracture networks)
  dune-functions  >= 2.10   (advanced basis functions)

C++ compiler: GCC >= 11 or Clang >= 14 (C++20 required)
Build system:  CMake >= 3.16
MPI:           Optional (for parallel runs)
```

### Build from source

```bash
# 1. Install DUNE dependencies
./bin/installexternal.py --all   # or install DUNE modules manually

# 2. Configure with CMake
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release \
         -DCMAKE_CXX_FLAGS="-O3 -march=native" \
         -DDUNE_CHECK_BOUNDS=OFF

# 3. Build all tests/examples
make -j$(nproc)

# 4. Run tests
ctest -j$(nproc)
```

### Python dependencies (for KI tools)

```
numpy, pandas, matplotlib, pyyaml, vtk (or meshio for VTK parsing)
```

### Test example

```
source/repo/examples/1ptracer/     # Single-phase + tracer transport
  main.cc                          # C++ source
  params.input                     # INI-style parameter file
  CMakeLists.txt                   # Build configuration
  spatialparams_*.hh               # Permeability/porosity fields
  problem_*.hh                     # Boundary conditions + sources
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Domain, grid, model type, simulation period |
| 1 | Grid/Domain setup | `convert_grid_to_dumux` | Define computational mesh (structured/DGF/Gmsh) |
| 2 | Forcing/Recharge | `convert_forcing_to_dumux` | Meteorological data → recharge boundary conditions |
| 3 | Soil/Aquifer params | `convert_soil_to_dumux` | HWSD/field data → permeability, porosity, van Genuchten |
| 4 | Build & Execute | `run_dumux` | Compile problem, run simulation with parameter file |
| 5 | Output parsing | `parse_dumux_output` | VTK output → CSV time series, spatial fields |
| 6 | Validation | (manual/tools) | Compare with observations, compute metrics |

### Parallelism

Stages 1, 2, 3 can run in parallel after stage 0.
Stage 4 depends on 1, 2, 3.
Stage 5 depends on 4.
Stage 6 depends on 5.

---

## Input Format: `.input` files (INI-style)

DuMux uses INI-style parameter files with `[Section]` headers and `Key = Value` entries.

### Example `params.input`:
```ini
[Grid]
LowerLeft = 0 0              # domain lower-left corner [m]
UpperRight = 1 1              # domain upper-right corner [m]
Cells = 50 50                 # grid resolution (nx ny)

[SpatialParams]
Permeability = 1e-10          # intrinsic permeability [m²]
PermeabilityLens = 1e-11      # lens permeability [m²]
LensLowerLeft = 0.2 0.2       # lens region [m]
LensUpperRight = 0.8 0.8      # lens region [m]
Porosity = 0.2                # porosity [-]

[TimeLoop]
DtInitial = 10                # initial time step [s]
TEnd = 5000                   # simulation end time [s]
MaxTimeStepSize = 10          # maximum time step [s]

[Problem]
Name = groundwater            # output file prefix
EnableGravity = true          # include gravity

[Vtk]
AddVelocity = true            # include velocity in output
Precision = Float64           # output precision

[LinearSolver]
MaxIterations = 10000         # max solver iterations
Tolerance = 1e-12             # convergence tolerance
```

### CLI invocation:
```bash
./executable params.input [-Section.Key value]
```

Parameters can be overridden on the command line:
```bash
./example_1ptracer params.input -Problem.Name my_run -TimeLoop.TEnd 10000
```

---

## Output Format: VTK

DuMux writes output in VTK format (`.vtu` for unstructured, `.pvd` for time series).

### Key output variables (1p model):
| Variable | Unit | Description |
|----------|------|-------------|
| pressure | Pa | Fluid pressure field |
| density | kg/m³ | Fluid density |
| viscosity | Pa·s | Dynamic viscosity |
| porosity | - | Pore volume fraction |
| permeability | m² | Intrinsic permeability |
| velocity | m/s | Darcy velocity (if AddVelocity=true) |

### Key output variables (tracer model):
| Variable | Unit | Description |
|----------|------|-------------|
| x^tracer | - | Mole/mass fraction of tracer |
| concentration | mol/m³ | Tracer concentration |
| velocity | m/s | Advective velocity |

### Output tools:
- VTK files viewable in ParaView
- Python parsing with `meshio` or `vtk` library
- Built-in gnuplot interface for quick plots

---

## Unit Convention Table

| Parameter | DuMux Unit | Common Alt | Conversion |
|-----------|-----------|------------|------------|
| Permeability | m² | darcy (D) | 1 D = 9.869e-13 m² |
| Pressure | Pa | bar, atm | 1 bar = 1e5 Pa |
| Time | s | hours, days | 1 day = 86400 s |
| Length | m | cm, mm | - |
| Porosity | - (fraction) | % | ÷ 100 |
| Density | kg/m³ | g/cm³ | × 1000 |
| Viscosity | Pa·s | mPa·s (cP) | 1 cP = 1e-3 Pa·s |
| Recharge | kg/(m²·s) | mm/day | mm/day × ρ / 86400000 |
| Hydraulic cond. | m/s | cm/day | cm/day / 8640000 |
| van Genuchten α | 1/Pa | 1/cm H₂O | 1/cm × 98.0665 = 1/Pa |
| Temperature | K | °C | K = °C + 273.15 |

### CRITICAL unit traps:

1. **Permeability is in m², NOT darcy**: Soil databases give K in darcy or hydraulic conductivity in m/s. Must convert: `K [m²] = k_h [m/s] × μ / (ρ × g)` where μ=1e-3 Pa·s, ρ=1000 kg/m³, g=9.81 m/s².

2. **Time is in seconds**: All TimeLoop parameters are in seconds. A 1-year simulation needs `TEnd = 31536000`. Forgetting this conversion leads to runs that end after microseconds.

3. **Recharge is mass flux [kg/(m²·s)]**: If using Neumann BC for recharge, convert from mm/day: `q = R_mm × ρ / (86400 × 1000)` where ρ=1000 kg/m³.

4. **van Genuchten α**: Soil databases often give α in 1/cm of water head. DuMux uses 1/Pa. Conversion: `α_Pa = α_cm / (ρ × g / 100)` = `α_cm / 98.0665`.

5. **Pressure is absolute, NOT gauge**: Initial conditions and boundary conditions use absolute pressure. At surface: p ≈ 101325 Pa (1 atm). Hydrostatic: `p = 101325 + ρ × g × depth`.

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_forcing_to_dumux` | s2 | `tools/convert_forcing_to_dumux.py` | Recharge/met data → Neumann BC values |
| `convert_soil_to_dumux` | s3 | `tools/convert_soil_to_dumux.py` | HWSD/soil data → permeability, porosity, vG params |
| `run_dumux` | s4 | `tools/run_dumux.py` | Build and execute DuMux simulation |
| `parse_dumux_output` | s5 | `tools/parse_dumux_output.py` | VTK → CSV extraction, time series, spatial fields |

**Total**: 4 tools, ~1,500 lines of validated Python code.

---

## Skill Knowledge

| Stage | Topic | Document |
|-------|-------|----------|
| s1 | Grid/domain setup | `docs/s1_grid_domain_setup.md` |
| s2 | Forcing and recharge conversion | `docs/s2_forcing_recharge.md` |
| s3 | Soil/aquifer parameters | `docs/s3_soil_parameters.md` |
| s4 | Building and running DuMux | `docs/s4_build_execution.md` |
| s5 | Output parsing and analysis | `docs/s5_output_parsing.md` |

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated.

### 1. Permeability in m², NOT darcy or hydraulic conductivity (dt_001)

DuMux uses intrinsic permeability in SI units (m²). Soil databases provide hydraulic conductivity K_h in m/s or cm/day. Conversion:
```
K [m²] = K_h [m/s] × μ / (ρ × g)
       = K_h [m/s] × 1e-3 / (1000 × 9.81)
       = K_h [m/s] × 1.0194e-7
```
Using K_h directly as permeability gives values ~1e7 too large → unrealistic flow velocities.

### 2. All times in seconds (dt_002)

Every temporal parameter in `.input` files uses seconds. Common mistakes:
- `TEnd = 365` means 365 seconds (6 minutes), not 1 year
- 1 year = 31,536,000 seconds
- 1 day = 86,400 seconds

### 3. Pressure is absolute, not gauge (dt_003)

Boundary pressures must include atmospheric pressure. At the water table surface:
`p = 101325 Pa` (1 atm). At depth d: `p = 101325 + 1000 × 9.81 × d`.
Using gauge pressure (p=0 at surface) shifts the entire solution by 1 atm.

### 4. van Genuchten α units differ between databases and DuMux (dt_004)

ROSETTA, HWSD, and most soil databases give α in 1/cm of water head. DuMux expects α in 1/Pa.
```
α_Pa = α_cm / 98.0665
```
Missing this conversion shifts the capillary pressure curve dramatically, producing wrong water retention.

### 5. Neumann BC sign convention (dt_005)

In DuMux, positive Neumann flux = **outward** (leaving the domain). For recharge (water entering from top), the flux must be **negative**:
```cpp
values[Indices::conti0EqIdx] = -rechargeRate;  // negative = inflow
```
Getting the sign wrong converts recharge into extraction.

### 6. Grid cell ordering affects permeability assignment (dt_006)

When reading permeability from external files, the cell ordering must match DuMux's grid traversal order (row-major for YaspGrid). Mismatched ordering silently assigns wrong permeability to wrong locations.

### 7. Gravity direction is -z (dt_007)

DuMux assumes gravity acts in the negative z-direction. For 2D vertical cross-sections, the second coordinate is z (vertical). Specifying a horizontal domain with gravity enabled produces incorrect hydrostatic pressure gradients.

### 8. Restart files require exact same grid (dt_008)

Restarting a simulation from a checkpoint requires the exact same grid (same cells, same ordering). Changing grid resolution between runs corrupts the restart and produces garbage output with no error message.

### 9. Adaptive time stepping can mask instabilities (dt_009)

DuMux's Newton solver reduces the time step on convergence failure. If the initial time step is too large, the solver may chop it down to microseconds, making the simulation appear to run but never reach TEnd. Monitor `dt` in the terminal output.

---

## Discretization Methods

| Method | Code | Best for |
|--------|------|----------|
| CC-TPFA | `CCTpfaModel` | Simple, fast; requires K-orthogonal grids |
| CC-MPFA | `CCMpfaModel` | Anisotropic K, non-orthogonal grids |
| Box (CVFE) | `BoxModel` | Vertex-centered; good for unstructured grids |
| FE | `FEMModel` | Standard finite elements |

### Grid types:
- `Dune::YaspGrid<dim>` — structured Cartesian (fast, simple)
- `Dune::ALUGrid<dim,dim,simplex,conforming>` — unstructured triangular/tetrahedral
- `Dune::FoamGrid<1,3>` — 1D networks in 3D space (fractures)
- `Dune::UGGrid<dim>` — general unstructured

---

## Model Types (porousmediumflow)

| Tag | Physics | Primary Variables |
|-----|---------|-------------------|
| `OneP` | Single-phase saturated flow | p |
| `OnePNC` | Single-phase N-component | p, x₁, x₂, ... |
| `TwoP` | Two-phase immiscible | p_w, S_n (or p_n, S_w) |
| `TwoPNC` | Two-phase N-component | p, S, x₁, ... |
| `Richards` | Variably saturated | p_w |
| `Tracer` | Passive tracer transport | x_tracer |
| `OnePNI` | Single-phase non-isothermal | p, T |

---

## Calibration Parameters (Priority Order)

| Parameter | Section | Unit | Range | Controls | Sensitivity |
|-----------|---------|------|-------|----------|-------------|
| Permeability | SpatialParams | m² | 1e-15 – 1e-8 | Flow velocity, head distribution | HIGH |
| Porosity | SpatialParams | - | 0.01 – 0.60 | Storage, transport velocity | HIGH |
| Recharge rate | Problem/BC | kg/(m²·s) | 0 – 1e-5 | Water input, head levels | HIGH |
| vG α | SpatialParams | 1/Pa | 1e-5 – 1e-2 | Capillary pressure curve | MEDIUM |
| vG n | SpatialParams | - | 1.1 – 5.0 | Retention curve shape | MEDIUM |
| Dispersivity | SpatialParams | m | 0.1 – 100 | Tracer spreading | MEDIUM |
| Diffusion coeff | Tracer | m²/s | 1e-12 – 1e-8 | Molecular diffusion | LOW |

---

## Data Requirements

| Data | Source | Purpose |
|------|--------|---------|
| DuMux source | github.com/dumux/dumux | Model framework |
| DUNE modules | dune-project.org | Required dependencies |
| Soil parameters | HWSD, ROSETTA, field data | K, φ, vG params |
| Recharge estimates | Met data, lysimeters | Top boundary condition |
| Head observations | Well monitoring | Calibration/validation |
| DEM | SRTM, LiDAR | Domain geometry |

---

## Quick Start (1p groundwater example)

```bash
# 1. Build the 1ptracer example
cd build/examples/1ptracer
make example_1ptracer

# 2. Run with default parameters
./example_1ptracer params.input

# 3. Override parameters on command line
./example_1ptracer params.input \
  -Problem.Name my_test \
  -TimeLoop.TEnd 10000 \
  -SpatialParams.Permeability 1e-11

# 4. View output in ParaView
paraview 1p_*.vtu
```

---

## Common C++ Patterns

### Problem class (boundary conditions):
```cpp
BoundaryTypes boundaryTypesAtPos(const GlobalPosition &pos) const {
    BoundaryTypes values;
    if (pos[dimWorld-1] < eps_ || pos[dimWorld-1] > yMax_ - eps_)
        values.setAllDirichlet();   // top/bottom: fixed head
    else
        values.setAllNeumann();     // sides: no-flow
    return values;
}

PrimaryVariables dirichletAtPos(const GlobalPosition &pos) const {
    return 1.0e5 + 1000*9.81*(yMax_ - pos[dimWorld-1]);  // hydrostatic
}
```

### Spatial parameters class:
```cpp
Scalar permeabilityAtPos(const GlobalPosition& pos) const {
    if (isInLens_(pos))
        return permeabilityLens_;   // low-K lens
    return permeability_;           // background K
}
```

### Main program pattern:
```cpp
int main(int argc, char** argv) try {
    Dumux::initialize(argc, argv);
    Parameters::init(argc, argv);
    // ... grid, problem, assembler, solver, time loop, VTK output
} catch (Dumux::ParameterException &e) { /* ... */ }
  catch (Dune::Exception &e) { /* ... */ }
```

---

## Error Handling

| Error Message | Cause | Fix |
|---------------|-------|-----|
| `ParameterException: Key not found` | Missing required parameter in .input | Add the key to the correct [Section] |
| `Newton: convergence failed` | Time step too large, bad initial conditions | Reduce DtInitial, check BC values |
| `DGFException` | Malformed grid file | Check DGF syntax, node/element counts |
| `ISTL: solver diverged` | Ill-conditioned system | Check permeability contrast, refine grid |
| `Segmentation fault at output` | Wrong grid/solution size mismatch | Ensure grid geometry matches solution vector |
| `NaN in solution` | Extreme parameter values, zero porosity | Check porosity > 0, permeability > 0 |

---

## Coupling Points

| # | Source | Target | Variable | Notes |
|---|--------|--------|----------|-------|
| 1 | Met/recharge model | DuMux | Recharge rate [kg/(m²·s)] | Top Neumann BC |
| 2 | River model | DuMux | River stage [Pa] | Lateral Dirichlet BC |
| 3 | DuMux | River model | Baseflow [m³/s] | Computed from head gradient |
| 4 | Soil database | DuMux | K, φ, vG params | Spatial parameter fields |
| 5 | DuMux (1p) | DuMux (tracer) | Velocity field | Sequential coupling |
