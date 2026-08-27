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
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (21 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (24 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing_to_issm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_issm.py --help` |
| `tools/convert_geometry_to_issm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_geometry_to_issm.py --help` |
| `tools/parse_issm_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_issm_output.py --help` |
| `tools/run_issm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_issm.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# ISSM (Ice-sheet and Sea-level System Model) — Knowledge Infrastructure

**Package**: `hydrocraft-issm-cryosphere` v1.0.0
**Model**: ISSM v2026.1 (Ice-sheet and Sea-level System Model)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-04-30
**Stats**: 4 tools | 5 skill documents | 20 diagnostic triplets | ~2,000 lines of validated Python
**Validation status**: `synthetic_only` — only the SquareIceShelf/SquareSheet
NightlyRun benchmarks have been executed (`_work/ISSM/issm_run_test{101,201,301}.py`,
domain `Square.exp` is a 5-point square, not a real glacier).
**Real-site validation**: NOT DONE. Before claiming a real-site result, fetch
BedMachine geometry + MEaSUREs surface velocity for a chosen target
(e.g. Pine Island Glacier, Thwaites, Jakobshavn) and use
`tools/convert_geometry_to_issm.py` to build a real `md` from them. Today
the KI's `outputs/` and `_work/ISSM/` contain no real-glacier mesh,
geometry, friction, or velocity data.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/SNOTEL/SKILL.md` ONLY for context. NOTE: point seasonal-snow SWE (e.g. SNOTEL) is NOT a valid ISSM validation target — ISSM has no snowpack SWE output (see NON-PRODUCIBLE VARIABLES below).
See `data_ki/BedMachine/SKILL.md` for ice topography.
See `data_ki/MEaSUREs/SKILL.md` for ice velocity.


## Overview

This knowledge infrastructure enables autonomous ice sheet and sea-level simulations using ISSM (Ice-sheet and Sea-level System Model), a large-scale thermo-mechanical 2D/3D parallelized multi-purpose finite-element software developed at NASA JPL and UC Irvine.

**What ISSM does**: Finite-element model for ice sheet dynamics. Simulates:
- Ice flow velocity (SSA, SIA, HO, Full Stokes, L1L2, MOLHO formulations)

> **NON-PRODUCIBLE VARIABLES / VALID DOMAIN (dag gate guard)**
> ISSM is an unstructured-mesh finite-element ICE-SHEET DYNAMICS model. Its dag.yaml
> outputs are: Vel/Vx/Vy/Vz (m/yr), Thickness/Surface/Base (m), Temperature (K),
> grounding-line position, IceVolume/GroundedArea/TotalSmb, and relative sea level.
> It produces **NO point snowpack SWE** (md.smb.mass_balance is a PRESCRIBED forcing
> in m/yr ice-equivalent, not a computed seasonal snow water equivalent).
> Valid real-site targets: glacier/ice-sheet surface velocity (MEaSUREs), ice
> thickness / surface / base elevation (BedMachine), grounding-line position, and
> ice volume / TotalSmb, over a polar or alpine GLACIATED domain in projected (meter)
> coordinates. Any target whose observed variable is SWE/snowpack, or whose site has
> no glacier/ice sheet (e.g. a mid-latitude SNOTEL site), is STRUCTURALLY INVALID and
> MUST be rejected by the dag gate with no retry.
- Thermal evolution (cold-ice temperature or enthalpy formulation)
- Mass transport (thickness evolution via continuity equation)
- Transient dynamics (coupled time-stepping of velocity + thickness + temperature)
- Grounding line migration (floating vs grounded ice transitions)
- Calving and ice front evolution (von Mises, level-set, crevasse depth)
- Subglacial hydrology (GlaDS, Shakti, Shreve, PISM, DC models)
- Damage evolution (crevasse formation and propagation)
- Glacial isostatic adjustment (solid earth deformation, Love numbers)
- Sea-level change (gravitationally self-consistent, GRACE, Farrell)
- Surface mass balance (PDD, MUNGSM, d18O, components, GEMB)
- Basal melting (linear, quadratic, PICO, Beckmann-Goosse, ISMIP6)
- Inverse methods (control method, AD-based inversion for friction/rheology)
- Uncertainty quantification (Dakota integration, sampling)

**Key difference from hydrological models**: ISSM operates on unstructured triangular/prismatic finite-element meshes over ice sheet domains (Antarctica, Greenland, individual glaciers). It is not a gridded basin model. The primary workflow is MATLAB/Python scripted, and the C++ core handles the numerical solve via PETSc.

---

## Installation

### Source

```
ISSM v2026.1:    source/repo/
Repository:      github.com/ISSMteam/ISSM
License:         BSD 3-Clause
Platforms:       Linux, macOS, Windows (MSYS2)
```

### Dependencies (external packages)

**Required:**
- C/C++ compiler (gcc/g++ or clang)
- Fortran compiler (gfortran)
- Autotools (autoconf, automake, libtool)
- PETSc (with bundled BLAS/LAPACK, MPICH, METIS, ParMETIS, MUMPS, ScaLAPACK)
- Triangle (mesh generation)
- M1QN3 (optimization, Fortran)

**Optional:**
- MATLAB (for MATLAB interface)
- Python 3 + NumPy (for Python interface)
- Dakota (uncertainty quantification)
- ADOLC/CoDiPack (automatic differentiation)
- GDAL/PROJ (geospatial data)
- GMT/GMSH (mesh generation, mapping)
- Boost (C++ utilities)
- NetCDF/HDF5 (data I/O)

### Build Process

```bash
# 1. Install external packages (PETSc bundles most deps)
cd externalpackages/petsc
./install-3.22-linux64.sh 4    # 4 = number of CPUs

cd ../triangle
./install-linux64.sh

# 2. Source environment
source etc/environment.sh

# 3. Configure
./scripts/automakererun.sh
./configure \
  --prefix=${ISSM_DIR} \
  --with-petsc-dir=${ISSM_DIR}/externalpackages/petsc/install \
  --with-triangle-dir=${ISSM_DIR}/externalpackages/triangle/install \
  --with-mpi-include=${ISSM_DIR}/externalpackages/petsc/install/include \
  --with-mpi-libflags="-L${ISSM_DIR}/externalpackages/petsc/install/lib -lmpi -lmpicxx -lmpifort" \
  --with-blas-lapack-dir=${ISSM_DIR}/externalpackages/petsc/install

# 4. Build
make -j 8
make install
```

### Produced Binaries

| Binary | Purpose |
|--------|---------|
| `issm` | Main ice sheet simulator |
| `issm_slc` | Sea-level change model |
| `issm_ocean` | Ocean coupling model |
| `kriging` | Spatial interpolation tool |
| `issm_dakota` | Dakota-ISSM integration |

### Python Dependencies

```
numpy, scipy, netCDF4 (for Python API)
```

### Test Example

```
examples/SquareIceShelf/     # Simplest idealized test
  runme.m / runme.py         # Main script (8 lines)
  Square.par / Square.py     # Parameterization (31 lines)
  DomainOutline.exp          # Domain boundary (5 points)
  Front.exp                  # Ice front boundary
```

---

## Pipeline (9 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Domain selection, period, physics modules, flow equation |
| 1 | Mesh Generation | `triangle()`, `bamg()` | Create 2D mesh from .exp domain outline |
| 2 | Mask Definition | `setmask()` | Define grounded ice vs floating ice vs ocean |
| 3 | Parameterization | `parameterize()` | Load geometry, materials, friction, BCs from .par file |
| 4 | Mesh Extrusion | `extrude()` (optional) | Convert 2D mesh to 3D prisms for HO/FS |
| 5 | Flow Equation | `setflowequation()` | Assign physics per element (SSA, SIA, HO, FS, etc.) |
| 6 | Solver Config | (manual) | Configure cluster, toolkits, timestepping |
| 7 | Execution | `solve()` | Run C++ FEM solver via MATLAB/Python wrapper |
| 8 | Post-processing | (analysis) | Extract results, plot, validate, export NetCDF |

### Stage Dependencies

```
Stage 0 → Stage 1 → Stage 2 → Stage 3 → Stage 4 (optional) → Stage 5 → Stage 6 → Stage 7 → Stage 8
```

All stages are sequential. Stage 4 (extrusion) is only needed for 3D simulations (HO, FS).

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `convert_forcing_to_issm` | s3 | `tools/convert_forcing_to_issm.py` | 280 | Convert external forcing data to ISSM input format |
| `convert_geometry_to_issm` | s3 | `tools/convert_geometry_to_issm.py` | 250 | Convert bed/surface/thickness data to ISSM mesh |
| `run_issm` | s7 | `tools/run_issm.py` | 310 | Execute ISSM Python simulation end-to-end |
| `parse_issm_output` | s8 | `tools/parse_issm_output.py` | 260 | Parse ISSM results to CSV/JSON |

**Total**: 4 tools, ~1,100 lines of validated Python code.

---

## Model Object (md) Structure

The ISSM model is represented by a `model` class with ~60 sub-objects:

### Mesh & Domain

| Field | Type | Units | Description |
|-------|------|-------|-------------|
| `md.mesh.x` | array[nv] | m | Vertex x-coordinates |
| `md.mesh.y` | array[nv] | m | Vertex y-coordinates |
| `md.mesh.elements` | array[ne×3] | - | Element connectivity (triangles) |
| `md.mesh.numberofvertices` | int | - | Total vertex count |
| `md.mesh.numberofelements` | int | - | Total element count |

### Geometry

| Field | Type | Units | Description |
|-------|------|-------|-------------|
| `md.geometry.surface` | array[nv] | m | Ice surface elevation |
| `md.geometry.base` | array[nv] | m | Ice base elevation |
| `md.geometry.thickness` | array[nv] | m | Ice thickness (= surface - base) |
| `md.geometry.bed` | array[nv] | m | Bedrock elevation |

### Materials

| Field | Type | Units | Description |
|-------|------|-------|-------------|
| `md.materials.rheology_B` | array[nv] | Pa s^(1/n) | Ice viscosity parameter (Glen's flow law) |
| `md.materials.rheology_n` | array[ne] | - | Flow law exponent (typically 3) |
| `md.materials.rho_ice` | scalar | kg/m^3 | Ice density (917) |
| `md.materials.rho_water` | scalar | kg/m^3 | Ocean water density (1023) |
| `md.materials.rho_freshwater` | scalar | kg/m^3 | Freshwater density (1000) |

### Friction

| Field | Type | Units | Description |
|-------|------|-------|-------------|
| `md.friction.coefficient` | array[nv] | (Pa m^-1 s)^(1/2) | Basal friction coefficient |
| `md.friction.p` | array[ne] | - | Friction law exponent p |
| `md.friction.q` | array[ne] | - | Friction law exponent q |

### Initialization

| Field | Type | Units | Description |
|-------|------|-------|-------------|
| `md.initialization.vx` | array[nv] | m/yr | Initial x-velocity |
| `md.initialization.vy` | array[nv] | m/yr | Initial y-velocity |
| `md.initialization.temperature` | array[nv] | K | Initial temperature |
| `md.initialization.pressure` | array[nv] | Pa | Initial pressure |

### Boundary Conditions

| Field | Type | Units | Description |
|-------|------|-------|-------------|
| `md.stressbalance.spcvx` | array[nv] | m/yr | Prescribed x-velocity (NaN = free) |
| `md.stressbalance.spcvy` | array[nv] | m/yr | Prescribed y-velocity (NaN = free) |
| `md.thermal.spctemperature` | array[nv] | K | Prescribed temperature (NaN = free) |

---

## Flow Equations

| Code | Name | Dimensions | Best For |
|------|------|------------|----------|
| `SSA` | Shallow Shelf Approximation | 2D (depth-integrated) | Ice shelves, fast ice streams |
| `SIA` | Shallow Ice Approximation | 2D (vertical shear) | Slow grounded ice sheets |
| `HO` | Higher-Order (Blatter-Pattyn) | 3D (needs extrude) | Transition zones, outlet glaciers |
| `FS` | Full Stokes | 3D (needs extrude) | Ice divides, grounding lines |
| `L1L2` | L1L2 hybrid | 2D | Fast alternative to HO |
| `MOLHO` | Modular higher-order | 2D+3D | Hybrid formulation |

---

## Solution Types

| Type | Short | Physics | Output Fields |
|------|-------|---------|---------------|
| `Stressbalance` | sb | Momentum conservation | Vx, Vy, Vz, Vel, Pressure |
| `Masstransport` | mt | Thickness evolution | Thickness, Surface |
| `Thermal` | th | Heat equation | Temperature, Enthalpy |
| `Transient` | tr | Coupled time-dependent | All above per timestep |
| `Balancethickness` | mc | Diagnostic thickness | Thickness |
| `Hydrology` | hy | Subglacial water | WaterPressure, HydraulicHead |
| `DamageEvolution` | da | Crevasse damage | DamageD |
| `Steadystate` | ss | Steady-state coupling | Vel, Thickness, Temperature |

---

## Input Formats

### .exp (Argus Contour Format)

Domain boundaries and contours. ASCII format:

```
## Name:domainoutline
## Icon:0
# Points Count  Value
5 1.
# X pos Y pos
0 0
1000000 0
1000000 1000000
0 1000000
0 0
```

**Units**: Meters (projected coordinates, typically polar stereographic)
**Read by**: `expread()` in MATLAB/Python

### NetCDF (.nc)

External datasets (SeaRISE, BedMachine, etc.) with gridded fields:
- `x1, y1` — grid coordinates (m)
- `usrf` — surface elevation (m)
- `topg` — bedrock topography (m)
- `thkmask` — grounded (1) / floating (-1) mask
- `surfvelx, surfvely` — surface velocity (m/yr)
- `bheatflx_fox` — geothermal heat flux (W/m^2)

### .arch (Archive Format)

ISSM's custom binary format for storing pre-computed mesh/field data.
**Read by**: `archread()` in MATLAB/Python

### .par / .py (Parameter Files)

MATLAB or Python scripts executed with `md` in scope. These load data, interpolate onto mesh, and set all model fields.

---

## Output Description (dag.yaml; template section 6)

**Source of truth**: `dag.yaml`. This section restates the dag so an agent reading
only `SKILL.md` can identify the observable outputs and the headline variable. If
this section ever disagrees with `dag.yaml`, the dag wins.

**Headline output**: `IceVolume / GroundedArea / TotalSmb`

> `IceVolume / GroundedArea / TotalSmb` — Integrated transient diagnostics: total ice volume, grounded area, total surface mass balance per timestep. (`m^3 / m^2 / m^3 ice eq`)

| Output variable (dag `var`) | Rank | Unit | Description |
|-----------------------------|------|------|-------------|
| `IceVolume / GroundedArea / TotalSmb` | 1 | `m^3 / m^2 / m^3 ice eq` | Integrated transient diagnostics: total ice volume, grounded area, total surface mass balance per timestep. |
| `Vel (and Vx, Vy, Vz)` | dag output | `m/yr` | Ice velocity magnitude and components. |
| `Thickness` | dag output | `m` | Ice thickness. |
| `Surface (and Base)` | dag output | `m` | Ice surface and base elevation. |
| `Temperature` | dag output | `K` | Ice temperature. |
| `grounding-line position (MaskOceanLevelset)` | dag output | level-set field | Grounding-line position through `MaskOceanLevelset`. |
| `relative sea level (S)` | dag output | sea-level field | Relative sea level. |

The rank-1 output is transient and integrated: it is not a point snowpack SWE
quantity, and it must not be validated against non-glacier station snowpack data.

---

## Output Format

Results stored in `md.results.<SolutionType>`:

### Stress Balance Results

| Field | Units | Description |
|-------|-------|-------------|
| `Vx` | m/yr | x-velocity |
| `Vy` | m/yr | y-velocity |
| `Vel` | m/yr | Velocity magnitude |
| `Pressure` | Pa | Ice pressure |

### Transient Results

Array of solutions per timestep:
```python
md.results.TransientSolution[i].Vel    # velocity at timestep i
md.results.TransientSolution[i].Thickness  # thickness at timestep i
```

### Export Options

- MATLAB `.mat` files (native)
- NetCDF via `export_netCDF(md, 'output.nc')`
- ParaView VTU format
- Binary ISSM format

---

## Unit Table (template section 8)

Exact I/O shapes live in `docs/format_spec.yaml`; this table summarizes the units
that matter when preparing ISSM inputs and interpreting dag outputs. The dag is the
authority for output units, and ISSM documentation/examples are the authority for
model object fields.

| Variable or field | Source/common unit | ISSM or dag unit | Conversion / convention | Diagnostic guard |
|-------------------|--------------------|------------------|-------------------------|------------------|
| Velocity (`Vel`, `Vx`, `Vy`, `Vz`) | m/s in some satellite products | `m/yr` | multiply m/s by `3.1536e7` | `dt_001` |
| Temperature | degC in some climate products | `K` | add `273.15` | `dt_002` |
| Thickness | km in some GIS datasets | `m` | multiply by `1000` | `dt_003` |
| Coordinates | degrees longitude/latitude | `m` projected coordinates | project to a polar/alpine meter CRS before meshing | `dt_004` |
| SMB (`md.smb.mass_balance`) | mm/yr water equivalent or kg/m^2/yr | `m/yr ice equiv.` as prescribed forcing | convert to ice-equivalent model forcing before solve | `dt_007` |
| Geothermal flux | mW/m^2 | `W/m^2` | divide by `1000` | `dt_008` |
| Pressure | MPa or kPa | `Pa` | multiply MPa by `1e6`; multiply kPa by `1e3` | `dt_009` |
| Mesh resolution | km | `m` | multiply by `1000` | `dt_010` |
| `IceVolume / GroundedArea / TotalSmb` | model transient diagnostics | `m^3 / m^2 / m^3 ice eq` | dag rank-1 output; parse as integrated diagnostics per timestep | dag output |
| `Surface (and Base)` | elevation products | `m` | maintain `surface = base + thickness` consistency | `dt_003`, `dt_018` |
| `grounding-line position (MaskOceanLevelset)` | mask / grounding-line products | level-set field | respect ISSM mask sign convention | `dt_011` |
| `relative sea level (S)` | sea-level field | sea-level field | use ISSM sea-level output convention from `dag.yaml` and post-processing docs | dag output |

---

## Unit Trap Table

**CRITICAL**: These unit mismatches cause silent failures. Each has a diagnostic triplet.

| Variable | ISSM Expects | Common Source | Conversion | Trap ID |
|----------|-------------|---------------|------------|---------|
| Velocity | m/yr | m/s (satellite) | × 3.1536e7 | dt_001 |
| Temperature | K | °C (climate data) | + 273.15 | dt_002 |
| Thickness | m | km (GIS datasets) | × 1000 | dt_003 |
| Coordinates | m (projected) | degrees (lat/lon) | Project via EPSG | dt_004 |
| Friction coeff | (Pa m^-1 s)^(1/2) | dimensionless | Model-specific | dt_005 |
| Rheology B | Pa s^(1/n) | Pa^-n s^-1 (A) | B = A^(-1/n) | dt_006 |
| SMB | m/yr ice equiv. | mm/yr w.e. or kg/m^2/yr | ÷ ρ_ice or × 1e-3 | dt_007 |
| Geothermal flux | W/m^2 | mW/m^2 | ÷ 1000 | dt_008 |
| Pressure | Pa | MPa or kPa | × 1e6 or × 1e3 | dt_009 |
| Mesh resolution | m | km | × 1000 | dt_010 |

---

## Critical Domain Knowledge

### 1. Velocity in m/yr, NOT m/s (dt_001)

ISSM uses meters per year for all velocity quantities. Satellite-derived velocities (e.g., MEaSUREs) are often in m/s or m/day. Off by ~3.15e7 if m/s is used directly. The ice will appear to not move at all.

### 2. Temperature in Kelvin, NOT Celsius (dt_002)

ISSM uses Kelvin for temperature fields. Climate reanalysis products typically provide °C. If you set `md.initialization.temperature` in °C, the ice will appear absurdly cold (e.g., -263°C becomes 10 K), and the rheology will be completely wrong.

### 3. Coordinates must be in meters (projected) (dt_004)

ISSM requires projected coordinates (e.g., polar stereographic) in meters. Geographic coordinates (lat/lon in degrees) will produce a mesh ~111,000x too small, and all physics will be wrong. Use EPSG:3031 for Antarctica, EPSG:3413 for Greenland.

### 4. Friction coefficient must be 0 on floating ice (dt_005)

Floating ice has no basal friction. If `md.friction.coefficient` is non-zero where `md.mask.ocean_levelset < 0`, the solver will apply basal drag to floating ice, producing unrealistically slow ice shelf velocities.

### 5. Glen's flow law: B vs A convention (dt_006)

ISSM uses the B (viscosity) convention: `σ = 2 η ε̇` where `η = B^n / (2 ε̇^(n-1))`. Many publications use the A (fluidity) convention: `ε̇ = A σ^n`. Conversion: `B = A^(-1/n)`. Using A directly as B produces velocities that are orders of magnitude wrong.

### 6. Thickness consistency: surface = base + thickness (dt_003)

ISSM enforces `surface = base + thickness`. If these are inconsistent (e.g., loaded from different datasets at different resolutions), the model may crash or produce non-physical results. Always compute one from the other two.

### 7. Mask levelset convention (dt_011)

- `md.mask.ice_levelset < 0` → ice present
- `md.mask.ice_levelset > 0` → no ice
- `md.mask.ocean_levelset < 0` → floating (ocean below)
- `md.mask.ocean_levelset > 0` → grounded (bedrock below)

These are SIGNED DISTANCE FUNCTIONS. Positive = outside, negative = inside. Confusing the sign convention produces inverted ice coverage.

### 8. Boundary conditions use NaN for free nodes (dt_012)

In ISSM, prescribed boundary conditions (spcvx, spcvy, spctemperature) use NaN to indicate a free (unconstrained) node. If you use 0 instead of NaN, the node is constrained to zero velocity/temperature, creating artificial ice divides or frozen boundaries.

### 9. The paterson() function converts T(K) → B(Pa s^1/n) (dt_006)

`rheology_B = paterson(temperature_in_kelvin)` is the standard way to set ice viscosity. Passing temperature in °C instead of K produces wrong rheology values. Always verify temperature is in Kelvin before calling `paterson()`.

---

## Skill Knowledge

| Stage | Topic | Document |
|-------|-------|----------|
| s1 | Mesh generation and refinement | `docs/s1_mesh_generation.md` |
| s2 | Mask definition and ice domains | `docs/s2_mask_definition.md` |
| s3 | Parameterization and data loading | `docs/s3_parameterization.md` |
| s5 | Flow equations and solver config | `docs/s5_flow_equations.md` |
| s7 | Execution and post-processing | `docs/s7_execution.md` |

---

## Diagnostic Triplets

20 triplets covering 5 failure domains. See `diagnostics/triplets.yaml` for full details.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | **silent** | unit_conversion | Velocity in m/s instead of m/yr |
| dt_002 | **silent** | unit_conversion | Temperature in °C instead of K |
| dt_003 | **silent** | unit_conversion | Thickness in km instead of m |
| dt_004 | **silent** | unit_conversion | Coordinates in degrees instead of meters |
| dt_005 | **silent** | unit_conversion | Non-zero friction on floating ice |
| dt_006 | **silent** | unit_conversion | Glen's A used instead of B |
| dt_007 | **silent** | unit_conversion | SMB in wrong units (mm w.e. vs m ice) |
| dt_008 | **silent** | unit_conversion | Geothermal flux in mW/m^2 instead of W/m^2 |
| dt_009 | **silent** | unit_conversion | Pressure in wrong units |
| dt_010 | **silent** | unit_conversion | Mesh resolution in km instead of m |
| dt_011 | **silent** | parameter_format | Mask levelset sign convention inverted |
| dt_012 | **silent** | parameter_format | Using 0 instead of NaN for free BC nodes |
| dt_013 | fatal | mesh_quality | Degenerate elements (zero area triangles) |
| dt_014 | fatal | mesh_quality | Disconnected mesh regions |
| dt_015 | degraded | solver_config | Wrong flow equation for domain type |
| dt_016 | fatal | solver_config | PETSc not found or misconfigured |
| dt_017 | degraded | solver_config | Time step too large for CFL stability |
| dt_018 | **silent** | physics_coupling | Inconsistent geometry (surface ≠ base + thickness) |
| dt_019 | degraded | physics_coupling | Missing initial conditions for transient |
| dt_020 | **silent** | physics_coupling | Wrong density constants (ρ_ice, ρ_water) |

**Silent error count**: 13/20 (65%) — extremely high due to the model's tolerance of physically unreasonable inputs.

---

## Validated Results (template section 11)

**Current validation status**: `synthetic_only`. The KI has executed only the
SquareIceShelf/SquareSheet NightlyRun benchmarks in
`_work/ISSM/issm_run_test{101,201,301}.py`; the `Square.exp` domain is a
5-point square, not a real glacier. Real-site validation is not done.

Before claiming a real-site result, fetch BedMachine geometry and MEaSUREs surface
velocity for a glaciated target such as Pine Island Glacier, Thwaites, or Jakobshavn,
then use `tools/convert_geometry_to_issm.py` to build a real `md`. The current
`outputs/` and `_work/ISSM/` contents contain no real-glacier mesh, geometry,
friction, or velocity data.

### Convention Bars from `docs/validation_convention.yaml`

These bars are the KI's sourced validation convention. The convention wins over
remembered thresholds. Null convention bands are written as `no cited threshold`;
they are not pass/fail guesses.

| Dag variable | Metric | Direction | Very good | Good | Satisfactory | Citation keys |
|--------------|--------|-----------|-----------|------|--------------|---------------|
| `Vel (and Vx, Vy, Vz)` | `rmse` | minimize | `50.0` (`seroussi2019_initmip_antarctica`, `larour2012_issm`) | `94.5` (`seroussi2019_initmip_antarctica`, `larour2012_issm`) | `308.0` (`seroussi2019_initmip_antarctica`, `larour2012_issm`) | `seroussi2019_initmip_antarctica`, `larour2012_issm` |
| `Vel (and Vx, Vy, Vz)` | `nse` | maximize | no cited threshold | no cited threshold | no cited threshold | none in convention |
| `Vel (and Vx, Vy, Vz)` | `rmse` | minimize | no cited threshold | no cited threshold | no cited threshold | none in convention |
| `Thickness` | `rmse` | minimize | `304.0` (`quiquet2018_grisli`, `seroussi2019_initmip_antarctica`) | `350.0` (`quiquet2018_grisli`, `seroussi2019_initmip_antarctica`) | `422.3` (`quiquet2018_grisli`, `seroussi2019_initmip_antarctica`) | `quiquet2018_grisli`, `seroussi2019_initmip_antarctica` |

No convention bar was provided in the extracted KI facts for the rank-1 output
`IceVolume / GroundedArea / TotalSmb`; do not assign a validation verdict for that
headline output unless `docs/validation_convention.yaml` supplies a cited threshold.

### Validation Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Geometry | BedMachine | pending real-site replacement | Needed before real-site validation. |
| Surface velocity | MEaSUREs | pending real-site replacement | Needed for `Vel (and Vx, Vy, Vz)` validation. |
| Surface mass balance forcing | CMFD/MSWX/NASA POWER or domain-specific SMB product | pending real-site replacement | `md.smb.mass_balance` is prescribed forcing, not computed SWE. |
| Synthetic benchmark domain | SquareIceShelf/SquareSheet NightlyRun | executed | Synthetic only; not a real glacier. |

---

## Quick Start (Python)

```python
from model import *
from triangle import triangle
from setmask import setmask
from parameterize import parameterize
from setflowequation import setflowequation
from solve import solve
from generic import generic
from socket import gethostname

# Step 1: Create model and mesh
md = triangle(model(), 'DomainOutline.exp', 100000)  # 100 km resolution

# Step 2: Set mask (all floating for ice shelf)
md = setmask(md, 'all', '')

# Step 3: Parameterize
md = parameterize(md, 'Square.py')

# Step 4: Set flow equation
md = setflowequation(md, 'SSA', 'all')

# Step 5: Configure solver
md.cluster = generic('name', gethostname(), 'np', 2)

# Step 6: Solve
md = solve(md, 'Stressbalance')

# Step 7: Access results
print(f"Max velocity: {max(md.results.StressbalanceSolution.Vel)} m/yr")
```

---

## Data Requirements

| Data | Source | Format | Status |
|------|--------|--------|--------|
| ISSM source | github.com/ISSMteam/ISSM | Git repository | Available |
| BedMachine | nsidc.org/data/idbmg4 | NetCDF | TO DOWNLOAD |
| MEaSUREs velocity | nsidc.org | NetCDF/GeoTIFF | TO DOWNLOAD |
| SeaRISE | tinyurl.com/srise-data | NetCDF | Available for Pig example |
| RACMO2 SMB | Utrecht University | NetCDF | TO DOWNLOAD |

---

## File Structure

```
ki/
  SKILL.md                            # This file (agent entry point)
  tools/
    convert_forcing_to_issm.py        # External forcing → ISSM input arrays
    convert_geometry_to_issm.py       # Bed/surface data → ISSM geometry
    run_issm.py                       # Execute ISSM Python simulation
    parse_issm_output.py              # Parse results to CSV/JSON
  docs/
    s1_mesh_generation.md             # Mesh creation and refinement
    s2_mask_definition.md             # Ice/ocean mask setup
    s3_parameterization.md            # Model parameterization
    s5_flow_equations.md              # Physics and solver config
    s7_execution.md                   # Running and post-processing
  diagnostics/
    triplets.yaml                     # 20 diagnostic triplets
```
