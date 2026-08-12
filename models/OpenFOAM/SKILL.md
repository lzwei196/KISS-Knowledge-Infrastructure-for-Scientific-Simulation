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

# OpenFOAM Knowledge Infrastructure

| Field | Value |
|-------|-------|
| Package | OpenFOAM-dev (CFD Framework) |
| Domain | Computational Fluid Dynamics / Hydraulics / Storm Surge |
| Language | C++ (9,257 source files) |
| Build System | wmake (custom), Allwmake master script |
| License | GPL v3 |
| Source | https://github.com/OpenFOAM/OpenFOAM-dev |
| Tools | 7 |
| Diagnostic Triplets | 32 (20 general + 12 ocean/storm-surge) |
| Validation | cavity tutorial; Hurricane Laura 2020 IB barometric (NSE=0.51, R=0.84 @ Grand Isle) |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/NOAA_Tides/SKILL.md` for tidal observation data.
See `data_ki/NDBC/SKILL.md` for wave buoy observations.


## 1. Overview

OpenFOAM (Open Field Operation and Manipulation) is a free, open-source CFD toolbox
written in C++. It solves complex fluid flows involving chemical reactions, turbulence,
heat transfer, acoustics, solid dynamics, and electromagnetics using the Finite Volume
Method (FVM).

**Key Capabilities for Hydraulics:**
- Incompressible and compressible flow (Navier-Stokes equations)
- Free-surface flows via Volume of Fluid (VoF) method (`interFoam` / `incompressibleVoF`)
- Multiphase Eulerian and Lagrangian particle tracking
- Turbulence: RANS (k-epsilon, k-omega SST, Spalart-Allmaras), LES, DES, DNS
- Adaptive mesh refinement and dynamic mesh motion
- Fully parallelized via MPI domain decomposition

**Architecture (dev version):**
The development version uses a modular solver architecture where `foamRun` dynamically
loads solver modules (e.g., `incompressibleFluid`, `fluid`, `incompressibleVoF`). Legacy
solver binaries (`simpleFoam`, `icoFoam`, `interFoam`) are thin wrappers calling `foamRun`.

---

## 2. Installation

### 2.1 Prerequisites
- C++ compiler: GCC >= 7, Clang, or Intel
- MPI: OpenMPI or MPICH (for parallel runs)
- Scotch or METIS (mesh partitioning)
- flex (lexer generator)
- ParaView (optional, for visualization)

### 2.2 Build from Source
```bash
# Clone repository
git clone https://github.com/OpenFOAM/OpenFOAM-dev.git OpenFOAM-dev

# Source environment
cd OpenFOAM-dev
source etc/bashrc

# Build everything (libraries + solvers + utilities)
./Allwmake -j$(nproc) 2>&1 | tee log.Allwmake

# Verify
blockMesh -help
foamRun -help
```

### 2.3 Environment Variables
| Variable | Purpose |
|----------|---------|
| `WM_PROJECT_DIR` | Root of OpenFOAM installation |
| `FOAM_APPBIN` | Compiled executables |
| `FOAM_LIBBIN` | Compiled libraries |
| `FOAM_TUTORIALS` | Tutorial case directory |
| `WM_COMPILER` | Compiler selection (Gcc, Clang) |
| `WM_ARCH_OPTION` | 32 or 64 bit addressing |

### 2.4 Test Installation
```bash
mkdir -p $FOAM_RUN && cd $FOAM_RUN
cp -r $FOAM_TUTORIALS/incompressibleFluid/cavity .
cd cavity
blockMesh
foamRun
```

---

## 3. Case Directory Structure

Every OpenFOAM simulation is defined by a case directory:

```
caseDir/
+-- 0/                  # Initial and boundary conditions
|   +-- p               # Pressure field
|   +-- U               # Velocity field
|   +-- k               # Turbulent kinetic energy (if turbulent)
|   +-- epsilon          # Turbulent dissipation (if turbulent)
+-- constant/           # Time-invariant properties
|   +-- polyMesh/       # Mesh definition (generated)
|   |   +-- points      # Vertex coordinates
|   |   +-- faces       # Face definitions
|   |   +-- owner       # Face-to-cell ownership
|   |   +-- neighbour   # Face-to-cell adjacency
|   |   +-- boundary    # Patch definitions
|   +-- physicalProperties   # Fluid viscosity, density
|   +-- momentumTransport    # Turbulence model config
+-- system/             # Solver configuration
    +-- controlDict     # Time stepping, write control, solver
    +-- fvSchemes       # Discretization schemes
    +-- fvSolution      # Linear solver settings, PIMPLE config
    +-- blockMeshDict   # Mesh generation parameters
    +-- decomposeParDict # Parallel decomposition
```

---

## 4. Pipeline Stages

| # | Stage | Tool | Description | Depends On |
|---|-------|------|-------------|------------|
| s0 | Configuration | `configure_case.py` | Set domain extents, fluid properties, time parameters | - |
| s1 | Mesh Generation | `generate_mesh.py` | Create computational mesh from blockMeshDict or external geometry | s0 |
| s2 | Boundary Conditions | `convert_forcing_to_openfoam.py` | Convert forcing data (velocity, pressure) to OpenFOAM field format | s1 |
| s3 | Physical Properties | `convert_properties_to_openfoam.py` | Convert fluid/soil properties to OpenFOAM dictionaries | s0 |
| s4 | Solver Setup | (manual) | Configure fvSchemes, fvSolution, controlDict | s1, s2, s3 |
| s5 | Execution | `run_openfoam.py` | Run solver binary with monitoring | s4 |
| s6 | Post-processing | `parse_openfoam_output.py` | Extract time series, fields to CSV/VTK | s5 |
| s7 | Visualization | (ParaView / matplotlib) | Create figures from extracted data | s6 |

---

## 5. Input Formats and Units

### 5.1 FoamFile Header (all field/dictionary files)
```cpp
FoamFile
{
    format      ascii;              // ascii or binary
    class       volScalarField;     // field type
    location    "0";                // time directory
    object      p;                  // field name
}
```

### 5.2 Dimension Array
OpenFOAM enforces dimensional consistency via a 7-element array:
```
dimensions [kg  m  s  K  mol  A  cd]
           [M   L  T  Th N    J  Lum]
```

| Quantity | Dimension Array | SI Unit |
|----------|----------------|---------|
| Pressure (kinematic) | `[0 2 -2 0 0 0 0]` | m^2/s^2 |
| Pressure (dynamic) | `[1 -1 -2 0 0 0 0]` | Pa |
| Velocity | `[0 1 -1 0 0 0 0]` | m/s |
| Kinematic viscosity | `[0 2 -1 0 0 0 0]` | m^2/s |
| Dynamic viscosity | `[1 -1 -1 0 0 0 0]` | Pa.s |
| Density | `[1 -3 0 0 0 0 0]` | kg/m^3 |
| Temperature | `[0 0 0 1 0 0 0]` | K |
| Turbulent kinetic energy | `[0 2 -2 0 0 0 0]` | m^2/s^2 |
| Turbulent dissipation | `[0 2 -3 0 0 0 0]` | m^2/s^3 |
| Volumetric flux (phi) | `[0 3 -1 0 0 0 0]` | m^3/s |
| Mass flux | `[1 0 -1 0 0 0 0]` | kg/s |
| Surface tension | `[1 0 -2 0 0 0 0]` | kg/s^2 |

### 5.3 Boundary Condition Types
| BC Type | Usage | Key Parameters |
|---------|-------|----------------|
| `fixedValue` | Dirichlet (fixed value) | `value uniform (Ux Uy Uz)` |
| `zeroGradient` | Neumann (zero flux) | none |
| `inletOutlet` | Switches on flow direction | `inletValue`, `value` |
| `totalPressure` | Total pressure inlet | `p0`, `gamma` |
| `noSlip` | Wall no-slip (velocity) | none |
| `slip` | Free-slip wall | none |
| `empty` | 2D simulation (ignored direction) | none |
| `symmetry` | Symmetry plane | none |
| `wedge` | Axisymmetric 2D | none |
| `cyclic` | Periodic | `neighbourPatch` |
| `fixedFluxPressure` | Pressure for fixed-velocity walls | `value` |

---

## 6. Unit Trap Table

These are the most dangerous unit/format traps that cause silent errors or crashes:

| ID | Trap | Expected | Common Mistake | Consequence |
|----|------|----------|----------------|-------------|
| ut_001 | Kinematic vs dynamic pressure | `[0 2 -2 0 0 0 0]` for incompressible | Using Pa `[1 -1 -2 0 0 0 0]` | Dimension mismatch crash |
| ut_002 | Kinematic viscosity `nu` | m^2/s (e.g., 1e-6 for water) | Using dynamic viscosity mu in Pa.s | Velocities off by density factor |
| ut_003 | blockMesh `convertToMeters` | Applied to all vertex coords | Forgetting scale factor (mm vs m) | Mesh 1000x too large/small |
| ut_004 | Velocity inlet units | m/s always | Using cm/s or mm/s | Flow rate off by orders of magnitude |
| ut_005 | Time step `deltaT` vs Courant | Courant = U*dt/dx < 1 | Too large dt for mesh | Divergence, floating point overflow |
| ut_006 | Turbulence inlet values | k = 1.5*(U*I)^2, eps = Cmu*k^1.5/l | Wrong turbulence intensity I | Incorrect turbulent profiles |
| ut_007 | Gravity vector | (0 -9.81 0) or (0 0 -9.81) | Wrong sign or axis | Buoyancy reversed |
| ut_008 | `writeInterval` interpretation | Depends on `writeControl` | `timeStep` vs `runTime` confusion | Too many/few output files |
| ut_009 | Parallel decomposition | `numberOfSubdomains` must match `mpirun -np N` | Mismatch between dict and CLI | MPI crash at startup |
| ut_010 | Boundary patch names | Must match blockMeshDict names exactly | Typo or case mismatch | Unassigned patch, crash |
| ut_011 | `internalField uniform 0` for vectors | Must be `uniform (0 0 0)` | Scalar 0 for vector field | Parse error |
| ut_012 | Surface tension `sigma` in VoF | `[1 0 -2 0 0 0 0]` (kg/s^2) | Using N/m as scalar without dimensions | Wrong interface dynamics |
| ut_013 | Hydrostatic p_rgh init in VoF | p_rgh_water = p_atm_BC + (ρ_w-ρ_a)·g·z_surface | `uniform 0` or `uniform p_atm` | 400,000 Pa imbalance → 32 m/s spike → 4s deltaT forever |
| ut_014 | phaseProperties `sigma` (dev) | `sigma 0.07;` (scalar, no parens) | `sigmas ((air water) 0.07);` (legacy) | FATAL: "keyword sigma is undefined" |
| ut_015 | cAlpha in fvSolution (dev) | Removed — set via div(phi,alpha) in fvSchemes | `cAlpha 0.5;` in alpha.water solver block | FATAL: "Deprecated and unused cAlpha" |
| ut_016 | Storm surge IB formula | η_IB = −(Pair−1013.25)×100/(ρ×g) [mbar→m] | Omitting ×100 for mbar→Pa conversion | 100× too small surge |
| ut_017 | Free surface cell alignment | z_surface must equal a blockMesh cell face | z_surface inside a cell (e.g. 47.5m in 10m cells) | Max(alpha)=1.82 at t=0 → RT instability |

---

## 7. Solver Reference

### 7.1 Key Solvers (foamRun modules)
| Module | Physics | Typical Use |
|--------|---------|-------------|
| `incompressibleFluid` | Incompressible Navier-Stokes | Pipe flow, channel flow, external aero |
| `fluid` | General compressible/thermal | HVAC, heat exchangers |
| `isothermalFluid` | Compressible, no energy eq | Gas dynamics |
| `incompressibleVoF` | Two-phase VoF | Free surface, wave, dam break |
| `compressibleVoF` | Two-phase VoF + compressibility | Cavitation |
| `multiphaseEuler` | N-phase Eulerian | Bubble columns, fluidized beds |
| `incompressibleDriftFlux` | Drift flux mixture | Slurry, sediment transport |
| `solid` | Heat conduction in solids | Conjugate heat transfer |
| `solidDisplacement` | Structural mechanics | FSI coupling |

### 7.2 Key Utilities
| Utility | Purpose |
|---------|---------|
| `blockMesh` | Structured hex mesh generation |
| `snappyHexMesh` | Automated unstructured meshing |
| `decomposePar` | Domain decomposition for parallel |
| `reconstructPar` | Merge parallel results |
| `foamToVTK` | Export to VTK for ParaView |
| `postProcess` | Run function objects post-hoc |
| `checkMesh` | Mesh quality validation |
| `mapFields` | Interpolate fields between meshes |

### 7.3 PIMPLE Algorithm Settings
```cpp
PIMPLE
{
    nOuterCorrectors    50;     // Outer PIMPLE loops (1=PISO, >1=PIMPLE)
    nCorrectors         2;      // Pressure correction steps per outer
    nNonOrthogonalCorrectors 1; // Non-orthogonal correction
    pRefCell            0;      // Reference cell for pressure
    pRefValue           0;      // Reference pressure value
    residualControl
    {
        U               1e-5;   // Convergence criterion
        p               1e-5;
    }
}
```

---

## 8. Critical Domain Knowledge

### dk_001: Kinematic vs Dynamic Pressure
OpenFOAM's incompressible solvers use **kinematic pressure** p/rho with dimensions
`[0 2 -2 0 0 0 0]` (m^2/s^2), NOT dynamic pressure in Pascal. When coupling with
external tools that output Pa, you MUST divide by density. This is the single most
common source of error for new users.

### dk_002: convertToMeters in blockMeshDict
The `convertToMeters` factor is applied to ALL vertex coordinates. If your vertices
are already in meters, set it to 1. If vertices are in millimeters, set 0.001.
Forgetting this produces a mesh at the wrong scale -- all velocities and Reynolds
numbers will be wrong, but the simulation may still converge, producing silently
incorrect results.

### dk_003: Boundary Patch Consistency
Patch names in `0/U`, `0/p`, etc. MUST exactly match those defined in
`constant/polyMesh/boundary` (generated by blockMesh/snappyHexMesh). A single
character mismatch causes a fatal "patch not found" error. After regenerating the
mesh, always update boundary condition files.

### dk_004: Courant Number and Time Stepping
For explicit or semi-implicit time schemes, the Courant number Co = U*dt/dx must
remain below ~1. Use `adjustTimeStep yes` with `maxCo 1` in controlDict for
adaptive stepping. For steady-state (SIMPLE), this does not apply -- use large
pseudo-time steps instead.

### dk_005: Gravity Direction in Hydraulic Simulations
For free-surface flows (VoF), gravity MUST be defined in `constant/g` as a
`uniformDimensionedVectorField`. The standard convention is `(0 -9.81 0)` for
Y-up or `(0 0 -9.81)` for Z-up. Using the wrong axis or sign produces inverted
buoyancy -- heavy fluid rises, light fluid sinks.

### dk_006: Turbulence Model Initialization
Under-initialized turbulence fields (k, epsilon, omega) cause the first few
iterations to diverge. Use the estimations:
- k = 1.5 * (U_ref * TI)^2  where TI = turbulence intensity (typically 0.01-0.1)
- epsilon = C_mu^0.75 * k^1.5 / l  where l = characteristic length scale
- omega = k^0.5 / (C_mu^0.25 * l)

### dk_007: writeControl vs writeInterval Semantics
- `writeControl timeStep; writeInterval 100;` writes every 100 time steps
- `writeControl runTime; writeInterval 0.1;` writes every 0.1 seconds of simulation time
- `writeControl adjustableRunTime;` adjusts dt to hit exact write times
Mixing these up produces unexpected output frequency.

### dk_008: VoF Phase Fraction alpha
In VoF simulations, `alpha.water` (or `alpha.phase1`) ranges 0-1. The field must
be initialized correctly: 1 = water, 0 = air. Using `setFields` with `boxToCell`
or `cylinderToCell` is required. An all-zero alpha field means no water exists.

### dk_010: incompressibleVoF vs shallowWaterFoam for Ocean Domains
**incompressibleVoF is designed for lab-scale problems** (wave tank, ship waves, dam break).
It is NOT appropriate for basin-scale ocean/storm surge domains (>100 km horizontal) because:
1. **Mass loss**: MULES numerical diffusion smears alpha into the air cell layer; open atmosphere
   BCs then let diffused alpha escape. At 40m depth with 10m cells, mass loss rate ~4.7e-7/s.
2. **Standing waves**: Closed slip-wall domain has no wave absorption. Initial pressure transients
   create resonant gravity waves (period T = 2L/c ≈ 27 h for 977 km basin). deltaT permanently
   oscillates at 0.25-1.5s — 100× slower than needed.
3. **Zero surge from uniform forcing**: Domain-averaged uniform p_atm has ∇p_atm = 0. The IB
   surface rise is exactly cancelled by the p_rgh change at the gauge → net surge = 0.
4. **VoF scale constraint**: For a 977km × 674km × 50m domain, VoF must resolve both the
   40m water column AND the 977km horizontal dynamics simultaneously — computationally intractable.

**Use shallowWaterFoam instead** (`$WM_PROJECT_DIR/applications/legacy/incompressible/shallowWaterFoam/`):
- Solves 2D depth-integrated SWE: ∂h/∂t + ∇·(hU) = 0; ∂(hU)/∂t + ∇·(UhU) + g·h·∇(h+h0) = 0
- Fields: h (depth), hU (depth-integrated velocity), h0 (bed topography)
- Typical dt = 0.5 × dx / √(g·h) = 0.5 × 4886 / √(9.81×40) = 123s → 4320 steps for 5 days
- Barometric forcing: set h0(x,y,t) = −(p_atm − p_ref)/(ρ·g) (inverted barometer)
- Reference performance: IB-only gives NSE=0.51, R=0.84 vs NOAA obs @ Grand Isle for Laura 2020

### dk_011: libparallel.so Must Be Built Before decomposePar
When building individual OpenFOAM utilities (not running Allwmake), the dependency
`libparallel.so` in `src/parallel/parallel/` must be compiled first or decomposePar
will fail with "cannot find -lparallel". Fix:
```bash
cd $WM_PROJECT_DIR/src/parallel/parallel && wmake libso
# Then retry decomposePar
```

### dk_012: MULESCorr yes Causes Rayleigh-Taylor Instability
`MULESCorr yes` (the MULES correction step) applies an additional corrective flux after
the bounded MULES step. This correction can overshoot, producing alpha > 1 in interface
cells. When alpha > 1 in an upper cell, that cell has density > ρ_water, sitting above
normal water → Rayleigh-Taylor unstable. The velocity grows exponentially until NaN.
**Always use `MULESCorr no` for large domains or when alpha Max > 1 is observed.**
`nSubCycles 1-2` is sufficient; `nSubCycles 5` with `MULESCorr no` is stable but slow.

### dk_013: runTimeModifiable Does Not Apply to 0/ Field Files
`runTimeModifiable true` in controlDict allows hot-editing of `system/fvSchemes`,
`system/fvSolution`, and `system/controlDict`. It does NOT re-read boundary conditions
from `0/` field files. For a running parallel case, BC changes must be made to ALL
`processor*/0/fieldName` files and require a solver restart.

### dk_014: Water Level Extraction from p_rgh Probe (VoF)
For an incompressibleVoF storm surge simulation, the water level anomaly at a gauge
located at height z_probe (within the water column) is:
```
η(t) = (p_rgh_probe(t) − p_rgh_probe(0)) / ((ρ_water − ρ_air) × g)
```
This only gives correct surge if: (a) mass is conserved (no alpha leakage), AND
(b) the forcing has spatial variation at the gauge location (∇p_atm ≠ 0).
With uniform domain-averaged forcing: the IB rise and p_rgh change cancel → η = 0.

### dk_009: Parallel Run MPI Consistency
`mpirun -np N foamRun -parallel` requires:
1. `system/decomposeParDict` with `numberOfSubdomains N;`
2. `decomposePar` run first to create `processor0/` ... `processorN-1/` directories
3. The N values MUST match. A mismatch causes immediate MPI abort.

---

## 9. Calibration and Tuning Parameters

| Parameter | Location | Range | Controls | Sensitivity |
|-----------|----------|-------|----------|-------------|
| `nu` (kinematic viscosity) | physicalProperties | 1e-7 to 1e-3 m^2/s | Reynolds number | High |
| `deltaT` | controlDict | 1e-6 to 1 s | Temporal resolution | High |
| `nOuterCorrectors` | fvSolution/PIMPLE | 1-100 | Coupling convergence | Medium |
| `nCorrectors` | fvSolution/PIMPLE | 1-4 | Pressure accuracy | Medium |
| `relaxationFactors` | fvSolution | 0.1-1.0 | Stability vs speed | High |
| `turbulence intensity` | 0/k inlet | 0.01-0.10 | Inlet turbulence level | Medium |
| `y+ (first cell height)` | blockMeshDict grading | 1-300 | Wall treatment accuracy | High |
| Convection scheme | fvSchemes/divSchemes | linearUpwind to QUICK | Numerical diffusion | Medium |
| `maxCo` | controlDict | 0.5-5.0 | Adaptive time step limit | High |
| `sigma` (surface tension) | physicalProperties | 0.01-0.1 N/m | VoF interface behavior | High (VoF) |

---

## 10. Data Requirements

| Data | Source | Format | Notes |
|------|--------|--------|-------|
| Domain geometry | CAD / GIS / manual | STL, blockMeshDict vertices | Meters (SI) |
| Fluid properties | Literature / measurement | physicalProperties dict | Kinematic viscosity, density |
| Inlet velocity | Measurement / design spec | 0/U fixedValue | m/s, vector (Ux Uy Uz) |
| Outlet pressure | Design / atmospheric | 0/p fixedValue/zeroGradient | m^2/s^2 (kinematic) |
| Turbulence BC | Estimation from Re | 0/k, 0/epsilon, 0/omega | Derived from U and length scale |
| Bathymetry (hydraulics) | DEM / survey | STL surface for snappyHexMesh | Must be watertight |
| Forcing (tidal, wave) | Tide tables / wave spectrum | Time-varying BC via coded/uniformFixedValue | m/s or m |

---

## 11. Quick Start

```bash
# 1. Source environment
source $WM_PROJECT_DIR/etc/bashrc

# 2. Copy tutorial case
cp -r $FOAM_TUTORIALS/incompressibleFluid/cavity myCase && cd myCase

# 3. Generate mesh
blockMesh

# 4. Check mesh quality
checkMesh

# 5. Run solver
foamRun

# 6. Convert output for visualization
foamToVTK

# 7. Parallel execution (4 cores)
decomposePar
mpirun -np 4 foamRun -parallel
reconstructPar
```

---

## 12. Output Format

### 12.1 Time Directories
Each write produces a directory named by the simulation time (e.g., `0.1/`, `0.2/`):
```
0.1/
+-- p           # Pressure field (all cells + boundaries)
+-- U           # Velocity field
+-- phi         # Face flux field
+-- uniform/    # Uniform fields (time info)
```

### 12.2 Field File Format
```cpp
internalField   nonuniform List<scalar>
1000            // number of cells
(
    0.0
    0.00123
    ...
)
;

boundaryField
{
    inlet { type calculated; value nonuniform List<scalar> 20 (...); }
    ...
}
```

### 12.3 Log File
The solver writes residuals, Courant number, and execution time to stdout.
Typical log line:
```
Time = 0.5
smoothSolver:  Solving for Ux, Initial residual = 0.00234, Final residual = 1.2e-07, No Iterations 3
GAMG:  Solving for p, Initial residual = 0.0156, Final residual = 4.5e-07, No Iterations 12
ExecutionTime = 1.23 s  ClockTime = 2 s
```

### 12.4 Function Objects
Post-processing probes, forces, and field averages are written to `postProcessing/`:
```
postProcessing/
+-- forces/
|   +-- 0/
|       +-- force.dat         # Time series of forces
+-- probes/
    +-- 0/
        +-- p                 # Probed pressure values
        +-- U                 # Probed velocity values
```

---

## 13. Coupling Points

| # | Interface | From | To | Data Exchanged |
|---|-----------|------|----|----------------|
| 1 | Mesh import | External CAD/GIS | OpenFOAM polyMesh | STL geometry, cell zones |
| 2 | Forcing BC | Hydrological model | OpenFOAM inlet | Discharge (m^3/s) -> velocity (m/s) |
| 3 | VoF init | DEM/bathymetry | alpha.water | Water surface elevation -> phase field |
| 4 | Output export | OpenFOAM fields | Downstream models | Velocity, pressure, WSE |
| 5 | Parallel | MPI decomposition | Multi-core execution | Domain partitioning |
| 6 | FSI | OpenFOAM fluid | OpenFOAM solid | Pressure on interface patches |

---

## 14. Diagnostic Triplets Summary

See `diagnostics/triplets.yaml` for full definitions.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | fatal | dimension_mismatch | Kinematic vs dynamic pressure dimensions |
| dt_002 | silent | unit_conversion | convertToMeters forgotten or wrong |
| dt_003 | fatal | patch_consistency | Boundary patch name mismatch |
| dt_004 | fatal | numerical_stability | Courant number exceeds limit |
| dt_005 | silent | unit_conversion | Gravity vector wrong axis or sign |
| dt_006 | degraded | initialization | Turbulence fields under-initialized |
| dt_007 | silent | configuration | writeControl/writeInterval mismatch |
| dt_008 | silent | initialization | VoF alpha field all zeros |
| dt_009 | fatal | parallel | MPI np vs decomposeParDict mismatch |
| dt_010 | fatal | mesh_quality | Non-orthogonality > 70 degrees |
| dt_011 | silent | unit_conversion | Dynamic viscosity used instead of kinematic |
| dt_012 | fatal | syntax | Scalar used for vector internalField |
| dt_013 | degraded | convergence | Relaxation factors too aggressive |
| dt_014 | silent | output | purgeWrite deleting needed time dirs |
| dt_015 | fatal | dependency | Missing MPI or Scotch at runtime |
| dt_016 | degraded | mesh_quality | y+ outside wall function valid range |
| dt_017 | silent | configuration | Empty functionObjects block |
| dt_018 | fatal | syntax | Missing semicolon in dictionary |
| dt_019 | silent | unit_conversion | Surface tension sigma wrong dimensions |
| dt_020 | degraded | convergence | Insufficient nNonOrthogonalCorrectors |
| dt_021 | silent | solver_selection | incompressibleVoF used for basin-scale ocean surge (>100km) — mass loss + zero signal |
| dt_022 | fatal | numerical_stability | deltaT → machine-zero from MULESCorr alpha>1 Rayleigh-Taylor instability |
| dt_023 | fatal | numerical_stability | Fixed U + fixed p_rgh at same boundary (atmosphere) is overdetermined |
| dt_024 | fatal | library_dependency | decomposePar build fails: libparallel.so not built yet |
| dt_025 | silent | initialization | alpha.water inletOutlet at atmosphere causes mass loss via MULES diffusion |
| dt_026 | fatal | configuration | cAlpha deprecated in OpenFOAM-dev fvSolution alpha block |
| dt_027 | degraded | initialization | Free surface not aligned with cell face → setFields alpha overshoot > 1 |
| dt_028 | silent | initialization | Uniform p_rgh=0 init → 400kPa imbalance → standing waves → deltaT stuck at 0.25s |
| dt_029 | fatal | numerical_stability | Open lateral BCs (zeroGradient p_rgh) → hydrostatic pressure drives 28 m/s outflow |
| dt_030 | degraded | numerical_stability | interfaceCompression scheme creates periodic Co spikes that collapse deltaT |
| dt_031 | silent | output_interpretation | p_rgh gauge masked by mass loss; uniform forcing gives zero spatial surge variation |
| dt_032 | fatal | configuration | Dev incompressibleVoF requires phaseProperties + physicalProperties.water/air (not transportProperties) |

---

## 15. File Structure

```
ki/
+-- SKILL.md                    # This file
+-- tools/
|   +-- convert_forcing_to_openfoam.py    # Forcing/BC converter
|   +-- convert_properties_to_openfoam.py # Physical properties converter
|   +-- generate_mesh.py                  # Mesh generation wrapper
|   +-- run_openfoam.py                   # Execution wrapper
|   +-- parse_openfoam_output.py          # Output parser
|   +-- configure_case.py                 # Case configuration generator
|   +-- check_case.py                     # Pre-run validation
+-- docs/
|   +-- s0_configuration.md       # Case configuration skill
|   +-- s1_mesh_generation.md     # Mesh generation skill
|   +-- s2_boundary_conditions.md # Forcing/BC setup skill
|   +-- s3_physical_properties.md # Property configuration skill
|   +-- s4_solver_setup.md        # Solver and scheme selection skill
|   +-- s5_execution.md           # Running OpenFOAM skill
|   +-- s6_postprocessing.md      # Output analysis skill
+-- diagnostics/
    +-- triplets.yaml             # 20 diagnostic triplets
```
