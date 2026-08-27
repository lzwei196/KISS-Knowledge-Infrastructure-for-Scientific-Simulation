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

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (5 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (7 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (25 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing.py --help` |
| `tools/convert_geometry.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_geometry.py --help` |
| `tools/generate_sif.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/generate_sif.py --help` |
| `tools/parse_vtu_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_vtu_output.py --help` |
| `tools/run_elmerice.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_elmerice.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# Elmer/Ice Knowledge Infrastructure

**Package**: hydrocraft-elmerice-cryosphere
**Version**: 1.0.0
**Target Model**: Elmer/Ice (Elmer FEM 26.1)
**Domain**: Cryosphere — ice sheet and glacier dynamics
**Tools**: 5 validated Python scripts
**Diagnostics**: 18 triplets covering unit, mesh, solver, and physics traps
**Validation**: ISMIP-HOM Experiment A benchmark

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/SNOTEL/SKILL.md` for snow observations.
See `data_ki/BedMachine/SKILL.md` for ice topography.
See `data_ki/MEaSUREs/SKILL.md` for ice velocity.


## 1. Overview

Elmer/Ice is a glaciological extension of the Elmer FEM (Finite Element Method) open-source
multiphysics suite developed by CSC – IT Center for Science (Finland). It solves ice sheet
and glacier dynamics equations on unstructured finite-element meshes, supporting:

- **Full-Stokes** ice flow (nonlinear viscous fluid with Glen's flow law)
- **Shallow Shelf Approximation (SSA)** for fast-flowing ice streams
- **Shallow Ice Approximation (SIA)** for interior ice sheets
- **Anisotropic ice flow (AIFlow/GOLF)** with fabric tensor evolution
- **Enthalpy/temperature** solvers for polythermal ice thermodynamics
- **GlaDS subglacial hydrology** (coupled sheet-channel drainage)
- **Calving** (2D/3D crevasse-depth and level-set methods)
- **Adjoint-based inverse methods** for parameter estimation (friction, viscosity)
- **Ice thickness evolution** with surface/basal mass balance forcing

Key differences from simpler ice models (PISM, Yelmo, SICOPOLIS):
- Unstructured FEM meshes allow variable resolution and complex geometries
- Full-Stokes capability (no approximation in stress balance)
- Modular solver architecture — any solver can be replaced or extended
- Adjoint methods for rigorous data assimilation
- Requires more setup (SIF files, mesh generation) than structured-grid models

---

## 2. Installation

### 2.1 Build from Source (Linux/Ubuntu)

```bash
# Install dependencies
sudo apt install git cmake build-essential gfortran libopenmpi-dev \
  libblas-dev liblapack-dev libmumps-dev libparmetis-dev \
  libnetcdf-dev libnetcdff-dev

# Clone and build
git clone https://github.com/ElmerCSC/elmerfem.git
cd elmerfem && mkdir build && cd build

cmake -DWITH_MPI:BOOL=TRUE \
      -DWITH_OpenMP:BOOL=TRUE \
      -DWITH_ElmerIce:BOOL=TRUE \
      -DWITH_Mumps:BOOL=TRUE \
      -DWITH_UMFPACK:BOOL=TRUE \
      -DCMAKE_INSTALL_PREFIX=/opt/elmer \
      ..

make -j$(nproc)
sudo make install
export PATH=/opt/elmer/bin:$PATH
```

### 2.2 Key Binaries

| Binary | Purpose |
|--------|---------|
| `ElmerSolver` | Main FEM solver — reads SIF, runs simulation |
| `ElmerGrid` | Mesh generation and format conversion |
| `ElmerGUI` | Graphical interface (optional) |

### 2.3 Quick Test

```bash
cd elmerice/examples/Test_SSA
ElmerGrid 1 2 rectangle
ElmerSolver ismip_SSA_1D.sif
# Output: test_SSA_1D.vtu (open in ParaView)
```

---

## 3. Simulation Pipeline

```
s0_config ──> s1_geometry ──> s2_mesh ──> s3_forcing ──> s4_sif ──> s5_execute
                                 │                          │
                                 └──> s6_partition ─────────┘
                                        (parallel only)

s5_execute ──> s7_postprocess ──> s8_validation
```

| Stage | Name | Tools | Description |
|-------|------|-------|-------------|
| s0 | Configuration | — | Define domain, time period, physics modules |
| s1 | Geometry | `convert_geometry.py` | Prepare bedrock/surface DEMs, ice thickness |
| s2 | Mesh Generation | ElmerGrid / Gmsh | Create FEM mesh from geometry |
| s3 | Forcing | `convert_forcing.py` | Prepare SMB, temperature, sliding boundary data |
| s4 | SIF Generation | `generate_sif.py` | Build Simulation Input File with all parameters |
| s5 | Execution | `run_elmerice.py` | Run ElmerSolver (serial or MPI parallel) |
| s6 | Partitioning | ElmerGrid | Partition mesh for parallel runs |
| s7 | Post-processing | `parse_vtu_output.py` | Extract variables from VTU to CSV |
| s8 | Validation | — | Compare to observations or benchmarks |

---

## 4. Tools Reference

| Tool | Lines | Stage | Purpose |
|------|-------|-------|---------|
| `convert_geometry.py` | ~250 | s1 | Convert DEMs/ice thickness to Elmer mesh node data |
| `convert_forcing.py` | ~280 | s3 | Convert climate forcing to Elmer boundary conditions |
| `generate_sif.py` | ~350 | s4 | Generate SIF file from parameters + morphometry |
| `run_elmerice.py` | ~200 | s5 | Execute ElmerSolver with preflight checks |
| `parse_vtu_output.py` | ~220 | s7 | Parse VTU XML output to CSV time series |

---

## 5. Input Formats

### 5.1 Simulation Input File (SIF)

The SIF is a plain-text configuration file with hierarchical blocks:

```
Header
  Mesh DB "." "mesh_directory"
End

Simulation
  Coordinate System = Cartesian 2D | Cartesian 3D
  Simulation Type = Steady State | Transient
  Timestepping Method = "bdf"
  BDF Order = 1
  Timestep Intervals = 100
  Timestep Sizes = 1.0          ! years (for glaciology)
  Post File = "results.vtu"
  Output Intervals = 10
End

Constants
  Gas Constant = Real 8.314      ! J/(mol K)
  Sea Level = Real 0.0           ! m
  Water Density = Real 1025.0    ! kg/m3 (ocean)
End

Body 1
  Equation = 1
  Material = 1
  Body Force = 1
  Initial Condition = 1
End

Material 1
  Viscosity Exponent = Real $(1.0/3.0)    ! Glen's n=3
  Critical Shear Rate = Real 1.0e-10       ! s^-1
  Density = Real 910.0                      ! kg/m3
  ! SSA friction
  SSA Friction Law = String "weertman"
  SSA Friction Parameter = Real 1.0e-3
  SSA Friction Exponent = Real $(1.0/3.0)
End

Solver 1
  Equation = "SSA"
  Procedure = "ElmerIceSolvers" "SSABasalSolver"
  Variable = -dofs 1 "SSAVelocity"
  Linear System Solver = Direct
  Linear System Direct Method = umfpack
End
```

### 5.2 Mesh Files

ElmerGrid native format (directory with 4 files):
- `mesh.header` — element types and counts
- `mesh.nodes` — node coordinates (ID x y z)
- `mesh.elements` — element connectivity
- `mesh.boundary` — boundary element definitions

### 5.3 Grid Definition File (.grd)

Structured grid specification for ElmerGrid:
```
#####  rectangle  #####
Coordinate System = Cartesian 2D
Subcell Divisions in 2D = 1 1
Subcell Sizes 1 = 1.0
Subcell Sizes 2 = 1.0
Element Divisions 1 = 100
Element Divisions 2 = 1
Boundary Conditions
  Target Boundaries(4) = 1 2 3 4
End
```

---

## 6. Output Description and Formats

**Source**: `dag.yaml`. The dag is the model's output identity; if this
section and `dag.yaml` disagree, `dag.yaml` wins.

### 6.1 Dag output description

**Headline output** (`validation_rank: 1` in `dag.yaml`):

> `SSAVelocity` — Depth-averaged horizontal ice velocity (raw VTU stores m/s) (`m/a`)

Other dag outputs are `H`, `DHDT`, `Zs`, `GroundedMask`, `Temperature`, and
`Effective Pressure`.

| Output variable (dag `var`) | Rank | Unit | Output description |
|-----------------------------|------|------|--------------------|
| `SSAVelocity` | 1 | `m/a` | Depth-averaged horizontal ice velocity (raw VTU stores m/s) |
| `H` | — | — | Listed in `dag.yaml` as an output |
| `DHDT` | — | — | Listed in `dag.yaml` as an output |
| `Zs` | — | — | Listed in `dag.yaml` as an output |
| `GroundedMask` | — | — | Listed in `dag.yaml` as an output |
| `Temperature` | — | — | Listed in `dag.yaml` as an output |
| `Effective Pressure` | — | — | Listed in `dag.yaml` as an output |

### 6.2 VTU (VTK Unstructured Grid)

Primary output format — XML-based, readable by ParaView and VTK tools.

Key output variables and their units:

| Variable | DOFs | Unit | Description |
|----------|------|------|-------------|
| SSAVelocity | 1-2 | m/a | Depth-averaged horizontal ice velocity (raw VTU stores m/s) |
| Velocity | 3-4 | m/a | 3D velocity field (u,v,w) |
| Pressure | 1 | Pa | Ice pressure |
| Temperature | 1 | deg C | Ice temperature (relative to PMP) |
| H | 1 | m | Ice thickness |
| Zs | 1 | m | Surface elevation |
| Zb | 1 | m | Bed elevation |
| Depth | 1 | m | Depth below surface |
| GroundedMask | 1 | — | -1=floating, 0=GL, 1=grounded |
| Stress | 6 | MPa | Deviatoric stress tensor components |
| StrainRate | 6 | a^-1 | Strain rate tensor components |
| Enthalpy_h | 1 | J/kg | Ice enthalpy |
| Water Content | 1 | % | Temperate ice water fraction |
| Hydraulic Potential | 1 | m | Subglacial water potential (GlaDS) |
| Effective Pressure | 1 | Pa | Ice overburden minus water pressure |

### 6.3 Result Files

Native Elmer format for restart and advanced analysis.

### 6.4 NetCDF

Optional (requires `-DWITH_NETCDF=TRUE`), used for large-scale ice sheet runs.

---

## 7. Critical Domain Knowledge — Unit Traps

These are non-obvious issues that cause **silent failures** (the model runs but gives
wrong results). Each is cross-referenced to a diagnostic triplet.

| ID | Trap | Effect | Remedy |
|----|------|--------|--------|
| dt_001 | Velocity units: Elmer uses m/s internally but glaciology papers report m/a | Velocity 3.17e7x too large if m/a used as m/s | Always convert: 1 m/a = 3.1688e-8 m/s |
| dt_002 | Glen's flow law exponent: SIF needs `Viscosity Exponent = 1/n` not `n` | Viscosity 27x wrong if n=3 entered directly | Use `Real $(1.0/3.0)` for n=3 |
| dt_003 | Density units: must be kg/m3 (910 for ice, 1025 for seawater) | Flotation criterion fails if g/cm3 used | Never use g/cm3 — always kg/m3 |
| dt_004 | Temperature: Elmer uses Kelvin internally for Arrhenius, but SIF accepts Celsius with offset | Activation energy computation wrong | Use `Reference Temperature` consistently |
| dt_005 | Pressure Melting Point: Clausius-Clapeyron slope is 9.8e-8 K/Pa (NOT 7.42e-8) | Wrong temperate ice extent | Use `beta_clapeyron = 9.8e-8` |
| dt_006 | Friction parameter beta: dimensions depend on friction law choice | Orders of magnitude error in basal drag | Match beta units to friction law exponent |
| dt_007 | Coordinate system: 2D means x-z vertical plane, 3D means x-y-z | Solver crashes or wrong physics | Use `Cartesian 2D` for flowline, `3D` for plan-view+depth |
| dt_008 | Mesh node coordinates must be in meters, not km | Gravity term 1000x wrong | Convert all DEM data to meters |
| dt_009 | Time step units in SIF are seconds unless explicitly set | Transient simulation 3.17e7x too slow if years assumed | Set `Timestep Sizes = 31556926.0` for 1 year in seconds |

---

## 8. Unit Table / Unit Conversion Table

This table documents the unit conversions explicitly stated by this KI. Verify
source data attributes before adding any dataset-specific conversion rows.

| Variable | Source unit (verified) | Model/KI unit | Factor | Type | Source |
|----------|------------------------|---------------|--------|------|--------|
| `SSAVelocity` input or observation velocity | `m/a` | `m/s` internal Elmer velocity | `x3.1688e-8` | multiplicative | `dt_001` |
| `SSAVelocity` raw VTU output | `m/s` | `m/a` dag output | `x31556926.0` | multiplicative | `dag.yaml`, `dt_009` |
| Mesh node coordinates | `km` if supplied by source | `m` | `x1000` | multiplicative | `dt_008` |
| Time step size | years if supplied by workflow intent | seconds in SIF unless explicitly set | `x31556926.0` | multiplicative | `dt_009` |

Output unit verification checklist:
- Read raw VTU arrays before metric calculation; `SSAVelocity` is reported by
  the dag as `m/a`, while raw VTU storage is `m/s`.
- Confirm mesh coordinates are meters before running `ElmerSolver`.
- Confirm transient SIF timesteps are seconds unless the SIF explicitly encodes
  another time convention.

---

## 8a. Solver Configuration Reference

### 8.1 SSA Solver (Shallow Shelf Approximation)

**Procedure**: `"ElmerIceSolvers" "SSABasalSolver"` (2D reduced model)
**Variables**: `SSAVelocity` (DOFs=1 for flowline, DOFs=2 for plan-view)

**Friction Laws**:
| Law | Parameters | Formula |
|-----|-----------|---------|
| linear | beta | tau_b = beta * u |
| weertman | beta, m | tau_b = beta * |u|^(m-1) * u |
| coulomb | C, As, q | tau_b per Gagliardini 2007 |
| regularised coulomb | C, lambda | smooth Coulomb variant |
| budd | beta, m, q | tau_b = beta * z_b^q * |u|^(m-1) * u |

### 8.2 Thickness Solver

**Procedure**: `"ElmerIceSolvers" "ThicknessSolver"`
**Equation**: dH/dt + div(uH) = M_s + M_b
**Body Force keywords**:
- `Top Surface Accumulation` — SMB at surface (m/a ice equivalent)
- `Bottom Surface Accumulation` — basal melt (m/a, positive = freeze-on)

### 8.3 Enthalpy Solver

**Procedure**: `"ElmerIceSolvers" "EnthalpySolver"`
**Material keywords**:
- `Enthalpy Density` = 910.0 (kg/m3)
- `Enthalpy Heat Diffusivity` = k/(rho*Cp) (m2/s)
- `Enthalpy Water Diffusivity` (m2/s)

**Constants**:
- `T_ref_enthalpy` = 200.0 (K, reference temperature)
- `L_heat` = 334000.0 (J/kg, latent heat of fusion)
- `P_triple` = 611.73 (Pa, triple point pressure)
- `P_surf` = 101325.0 (Pa, surface pressure)

### 8.4 GlaDS Hydrology

**Procedure**: `"ElmerIceSolvers" "GlaDSCoupledSolver"`
**Variables**: `Hydraulic Potential`, `Sheet Thickness`, `Channel Area`

**Material keywords**:
- `Sheet Conductivity` (m^(7/4) kg^(-1/2))
- `Sheet flow exponent alpha` (typically 5/4)
- `Sheet flow exponent beta` (typically 3/2)
- `Bedrock Bump Length` (m, ~2.0)
- `Bedrock Bump Height` (m, ~0.1)
- `Englacial Void Ratio` (typically 1.0e-4)

### 8.5 Linear System Settings

```
Linear System Solver = Iterative | Direct
Linear System Iterative Method = BiCGStab | GMRES | CG
Linear System Direct Method = umfpack | mumps
Linear System Max Iterations = 1500
Linear System Convergence Tolerance = 1.0e-12
Linear System Preconditioning = ILU0 | ILU1 | ILUT
```

### 8.6 Nonlinear System Settings

```
Nonlinear System Max Iterations = 50
Nonlinear System Convergence Tolerance = 1.0e-6
Nonlinear System Newton After Iterations = 5
Nonlinear System Newton After Tolerance = 1.0e-5
Nonlinear System Relaxation Factor = 1.0
```

---

## 9. Calibration Parameters

| Parameter | Typical Range | Sensitivity | Affects |
|-----------|--------------|-------------|---------|
| SSA Friction Parameter (beta) | 1e-5 to 1e-1 | Very High | Ice velocity |
| Glen's n (Viscosity Exponent) | 1/3 (n=3) | High | Flow rate |
| Rate Factor A | 1e-25 to 1e-16 Pa^-3 s^-1 | High | Viscosity |
| Surface Mass Balance | Site-specific | Very High | Ice thickness |
| Basal Melt Rate | 0 to 50 m/a | High | Grounding line |
| Geothermal Heat Flux | 40-120 mW/m2 | Medium | Temperature field |
| Bedrock Bump Height | 0.01-1.0 m | Medium | GlaDS drainage |
| Sheet Conductivity | 0.001-0.05 | High | Subglacial water |

---

## 10. Data Requirements

| Data | Source | Format | Key Variables |
|------|--------|--------|---------------|
| Bed topography | BedMachine v5 | NetCDF | bed elevation (m) |
| Ice thickness | BedMachine v5 | NetCDF | thickness (m) |
| Surface elevation | ArcticDEM / REMA | GeoTIFF | elevation (m) |
| Surface velocity | MEaSUREs / ITS_LIVE | NetCDF | vx, vy (m/a) |
| Surface mass balance | RACMO / MAR | NetCDF | SMB (kg/m2/a) |
| Geothermal heat flux | Shapiro & Ritzwoller | NetCDF | GHF (mW/m2) |
| Ocean thermal forcing | ISMIP6 | NetCDF | TF (deg C) |

---

## 11. Validated Results

**Source**: `docs/validation_convention.yaml`. The convention file is the
field bar for this KI; if this section and the convention disagree, the
convention wins.

### 11.1 Validation benchmark

| Property | Value |
|----------|-------|
| Benchmark | ISMIP-HOM Experiment A |
| Headline dag output | `SSAVelocity` |
| Headline output unit | `m/a` |
| Headline output description | Depth-averaged horizontal ice velocity (raw VTU stores m/s) |

### 11.2 Performance bars from the convention

For minimize metrics, lower values are better. For maximize metrics, higher
values are better. Null convention bands are written as `no cited threshold`.

| Output variable | Metric | Direction | Satisfactory band | Good band | Very good band |
|-----------------|--------|-----------|-------------------|-----------|----------------|
| `SSAVelocity` | `rmse` | minimize | `94.5` (`seroussi2019`, `mcarthur2023`) | `47.5` (`seroussi2019`, `mcarthur2023`) | `7.31` (`seroussi2019`, `mcarthur2023`) |
| `SSAVelocity` | `nse` | maximize | no cited threshold | no cited threshold | no cited threshold |
| `H` | `rmse` | minimize | `320.8` (`seroussi2019`) | `160.0` (`seroussi2019`) | `91.2` (`seroussi2019`) |

### 11.3 Results interpretation

Grade `SSAVelocity` first because it is the rank-1 dag output. An achieved
`SSAVelocity` RMSE must be compared against the cited `seroussi2019` and
`mcarthur2023` bands above; an achieved `SSAVelocity` NSE has no cited
threshold in the convention. An achieved `H` RMSE must be compared against the
cited `seroussi2019` bands above.

---

## 12. Quick Start — ISMIP-HOM Benchmark A

```bash
# Step 1: Navigate to example directory
cd elmerice/examples/Test_SSA

# Step 2: Generate the mesh
ElmerGrid 1 2 rectangle

# Step 3: Run SSA 1D benchmark
ElmerSolver ismip_SSA_1D.sif

# Step 4: View results
paraview test_SSA_1D.vtu

# Step 5: Run 3D case (if 3D mesh is built)
ElmerSolver ismip_SSA_3D.sif

# Step 6: Run parallel (4 cores)
ElmerGrid 1 2 rectangle -partdual -metis 4
mpirun -np 4 ElmerSolver ismip_SSA_1D.sif
```

---

## 13. Diagnostic Triplets Summary

| ID | Stage | Symptom | Root Cause |
|----|-------|---------|------------|
| dt_001 | s3_forcing | Velocity 10^7x too large | m/a vs m/s confusion |
| dt_002 | s4_sif | Viscosity 27x wrong | n vs 1/n exponent |
| dt_003 | s4_sif | Flotation wrong | g/cm3 vs kg/m3 density |
| dt_004 | s4_sif | Wrong temperature field | K vs C confusion |
| dt_005 | s4_sif | Wrong PMP extent | beta_clapeyron value |
| dt_006 | s4_sif | Basal drag orders wrong | beta units mismatch |
| dt_007 | s2_mesh | Solver crash | 2D vs 3D confusion |
| dt_008 | s1_geometry | Gravity term wrong | km vs m coordinates |
| dt_009 | s4_sif | Simulation 10^7x slow | time step year vs s |
| dt_010 | s2_mesh | Convergence failure | Mesh too coarse at GL |
| dt_011 | s5_execute | MPI crash | Mesh not partitioned |
| dt_012 | s4_sif | Zero velocity | Missing body force |
| dt_013 | s4_sif | NaN in solution | Critical shear rate=0 |
| dt_014 | s3_forcing | Wrong SMB sign | Ablation sign convention |
| dt_015 | s7_postprocess | Empty VTU | Output Intervals too large |
| dt_016 | s4_sif | Wrong ice extent | Missing thickness limiter |
| dt_017 | s5_execute | MUMPS out of memory | Direct solver on fine mesh |
| dt_018 | s4_sif | Wrong fabric evolution | Fabric DOFs ≠ 5 |

---

## 14. File Structure

```
ki/
├── SKILL.md                              # This file — master reference
├── tools/
│   ├── convert_geometry.py               # s1: DEM/thickness → node data
│   ├── convert_forcing.py                # s3: Climate data → BC format
│   ├── generate_sif.py                   # s4: Parameter dict → SIF file
│   ├── run_elmerice.py                   # s5: Execute ElmerSolver
│   └── parse_vtu_output.py              # s7: VTU XML → CSV
├── docs/
│   ├── s1_geometry_preparation.md        # Geometry & DEM processing
│   ├── s2_mesh_generation.md             # Mesh creation with ElmerGrid/Gmsh
│   ├── s3_forcing_preparation.md         # Climate/SMB boundary conditions
│   ├── s4_sif_configuration.md           # SIF file assembly
│   ├── s5_execution.md                   # Running ElmerSolver
│   ├── s7_postprocessing.md              # Output extraction
│   └── s8_validation.md                  # Benchmark comparison
└── diagnostics/
    └── triplets.yaml                     # 18 symptom→diagnosis→remedy entries
```
