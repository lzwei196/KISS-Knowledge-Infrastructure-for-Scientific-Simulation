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
| before running a stage | `docs/s*_*.md` (7 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (20 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
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
| `tools/convert_thickness_to_icepack.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_thickness_to_icepack.py --help` |
| `tools/convert_velocity_to_icepack.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_velocity_to_icepack.py --help` |
| `tools/parse_icepack_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_icepack_output.py --help` |
| `tools/run_icepack_simulation.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_icepack_simulation.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# icepack v1.1.0 — Knowledge Infrastructure

**Package**: `hydrocraft-icepack-glacier` v1.0.0
**Model**: icepack v1.1.0 — Glacier Flow Modeling with Finite Elements
**Author**: Daniel Shapero, University of Washington
**Domain**: Cryosphere (ice sheets, ice shelves, ice streams, glaciers)
**Last updated**: 2026-03-26
**Stats**: 4 tools | 6 skill documents | 20 diagnostic triplets
**Validation status**: `structurally_validated`

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/SNOTEL/SKILL.md` for snow observations.
See `data_ki/BedMachine/SKILL.md` for ice topography.
See `data_ki/MEaSUREs/SKILL.md` for ice velocity.


## Overview

icepack is a Python library for modeling the flow of ice sheets and glaciers using the
finite element method (FEM). It is built on top of [Firedrake](https://www.firedrakeproject.org),
a sophisticated FEM framework, and uses PETSc for linear/nonlinear solvers.

**What icepack simulates:**
- **Ice shelf flow** (floating ice, depth-averaged SSA equations)
- **Ice stream flow** (grounded fast-flowing ice with basal sliding, SSA + friction)
- **Shallow ice flow** (slow-flowing grounded ice, SIA equations)
- **Hybrid model** (3D velocity on extruded meshes, combines membrane + vertical shear)
- **Mass transport** (thickness evolution via continuity equation)
- **Heat transport** (3D advection-diffusion of energy density in ice)
- **Damage transport** (continuum damage mechanics, fracture + healing)
- **Inverse problems** (inferring basal friction, ice fluidity from observations)

**Key difference from other cryosphere models**: icepack is a *library*, not a
standalone executable. Simulations are written as Python scripts that import icepack,
create meshes, define boundary conditions, and call solvers. There is no config file,
namelist, or CLI — the Python API *is* the interface.

---

## Installation

### Prerequisites

icepack depends on Firedrake, which must be installed first via its own installer:

```bash
# Install Firedrake (creates its own virtual environment)
curl -O https://raw.githubusercontent.com/firedrakeproject/firedrake/master/scripts/firedrake-install
python3 firedrake-install

# Activate the Firedrake venv
source firedrake/bin/activate
```

### Install icepack

```bash
# Inside the Firedrake venv
cd /path/to/icepack/source/repo
pip install -e .
```

### Python Dependencies

```
firedrake          # FEM framework (includes PETSc, UFL, TSFC)
numpy, scipy       # Numerical computing
matplotlib         # Plotting
rasterio, xarray   # Geospatial raster I/O
netCDF4            # NetCDF support
geojson, geopandas # GeoJSON / vector data
shapely            # Geometric operations
pooch              # Data download management
earthaccess        # NASA EarthData authentication
gmsh, MeshPy       # Mesh generation
tqdm               # Progress bars
```

### Unit System

**CRITICAL**: icepack uses a non-SI unit system internally:

| Quantity           | icepack unit     | SI unit    | Conversion factor         |
|--------------------|------------------|------------|---------------------------|
| **Stress**         | MPa              | Pa         | 1 MPa = 10^6 Pa           |
| **Length**         | meters           | meters     | 1:1                       |
| **Time**           | years            | seconds    | 1 yr = 365.25×24×3600 s   |
| **Velocity**       | m/yr             | m/s        | ÷ 3.15576×10^7            |
| **Gravity**        | m/yr²            | m/s²       | 9.81 × (3.15576×10^7)²    |
| **Density**        | MPa·yr²/m²      | kg/m³      | ρ / year² × 10^-6         |
| **Rate factor A**  | MPa^-3 yr^-1    | Pa^-3 s^-1 | complex (see viscosity.py) |
| **Heat capacity**  | m²/yr²/K        | J/(kg·K)   | c × year²                 |

This unit system is chosen so that Glen's flow law rate factor A ≈ 1 at typical
glacier temperatures. **All inputs must be converted to this system.**

---

## Pipeline (8 stages)

| # | Stage | Tool(s) / Module | Description |
|---|-------|-------------------|-------------|
| 0 | Configuration | (Python script) | Choose glacier, model type, time period |
| 1 | Data acquisition | `icepack.datasets` | Fetch velocity, thickness, bed elevation from NSIDC |
| 2 | Mesh generation | `icepack.meshing` | GeoJSON outline → unstructured triangular mesh |
| 3 | Interpolation | `icepack.interpolate` | Gridded raster data → FEM function space |
| 4 | Diagnostic solve | `FlowSolver.diagnostic_solve()` | Solve for velocity given thickness, fluidity |
| 5 | Prognostic solve | `FlowSolver.prognostic_solve()` | Evolve thickness forward in time |
| 6 | Inverse problem | `icepack.statistics` | Infer fluidity/friction from observed velocity |
| 7 | Post-processing | `icepack.plot`, matplotlib | Visualize fields, compute norms, export |

### Stage Dependencies

```
Stage 0 (config) → Stage 1 (data) → Stage 2 (mesh) → Stage 3 (interpolation)
                                                            ↓
                                          Stage 4 (diagnostic) ↔ Stage 5 (prognostic)
                                                            ↓
                                                     Stage 6 (inverse)
                                                            ↓
                                                     Stage 7 (post-processing)
```

---

## Output Description

**Source of truth**: `dag.yaml`. The dag is the model identity for outputs; if this
section and `dag.yaml` disagree, `dag.yaml` wins.

**Headline output** (dag `validation_rank: 1`):

> `velocity` — Solved depth-averaged (or 3D) ice velocity field satisfying the momentum balance; typical 0-4000 m/yr for Antarctic ice streams. (`m/yr`)

| Output variable (dag `var`) | Rank | Unit | Emitted in | Description |
|-----------------------------|------|------|------------|-------------|
| `velocity` | 1 | `m/yr` | `diagnostic_solve` return (`firedrake.Function`); time series exported to CSV by post-processing | Solved depth-averaged (or 3D) ice velocity field satisfying the momentum balance; typical 0-4000 m/yr for Antarctic ice streams. |
| `thickness` | 2 | `m` | `prognostic_solve` return (`firedrake.Function`); time series exported to CSV | Ice thickness after a prognostic time step, evolved by mass continuity; must remain > 0. |
| `surface` | 3 | `m` | `compute_surface` return (`firedrake.Function`) | Hydrostatic-consistent surface elevation recomputed from updated thickness and bed for grounded models. |
| `optimized_control` | 4 | `varies (A in MPa^-3 yr^-1, or C in Weertman units)` | `icepack.statistics` `MaximumProbabilityEstimator` result | Best-fit ice fluidity or ice-bed basal-friction field inferred from observed ice velocity via the inverse problem. |
| `simulated_velocity` | 5 | `m/yr` | `icepack.statistics` simulation at optimum | Model ice velocity at the inverse-problem optimum, for comparison against the observed ice velocity used in inversion. |

Other dag outputs are `thickness`, `surface`, `optimized_control`, and
`simulated_velocity`.

---

## Unit Table

**Exact shapes live in `docs/format_spec.yaml`** (projected from `dag.yaml` +
`diagnostics/triplets.yaml`). This table restates the model-facing units and the
conversion traps that affect the pipeline.

| Variable | Source or input unit | icepack / output unit | Conversion | Source |
|----------|----------------------|-----------------------|------------|--------|
| `velocity` | `m/s` for sources that provide SI velocity; MEaSUREs Antarctic data is typically already `m/yr` | `m/yr` | multiply by `3.15576e7` only when the source is `m/s`; do not double-convert data already in `m/yr` | `dag.yaml`, `docs/format_spec.yaml`, `diagnostics/triplets.yaml` `dt_001`, `dt_002` |
| `simulated_velocity` | model simulation at inverse-problem optimum | `m/yr` | none after model execution | `dag.yaml` |
| `thickness` | `m`; some datasets may store `km` | `m` | none for meters; multiply by `1000` if source is `km` | `dag.yaml`, `docs/format_spec.yaml`, `diagnostics/triplets.yaml` `dt_004` |
| `surface` | recomputed from updated thickness and bed | `m` | none after `compute_surface` | `dag.yaml` |
| `bed (b)` | dataset lookup | `m` | none when already meters | `docs/format_spec.yaml` |
| `accumulation` | `m w.e./yr` if supplied as water equivalent | `m ice/yr` | multiply by `rho_w/rho_i ~= 1.09` | `dag.yaml`, `docs/format_spec.yaml` |
| `temperature (T)` | `degC` in common source data | `K` | add `273.15` before `icepack.rate_factor(T)` | `docs/format_spec.yaml`, `diagnostics/triplets.yaml` `dt_003` |
| `fluidity (A)` | derived from temperature or inferred | `MPa^-3 yr^-1` | use `icepack.rate_factor(T)`; do not hand-convert SI `Pa^-3 s^-1` values | `docs/format_spec.yaml`, `diagnostics/triplets.yaml` `dt_015` |
| `friction (C)` | calibrated or inferred | `MPa yr^(1/m) m^(-1/m)` | none; must be non-negative | `docs/format_spec.yaml`, `diagnostics/triplets.yaml` `dt_005` |
| `timestep (dt)` | user-provided float | `yr` | none | `docs/format_spec.yaml` |
| `mesh_resolution (lcar)` | user-provided characteristic element length | `m` | none | `docs/format_spec.yaml` |
| `glacier_outline` | GeoJSON FeatureCollection | GeoJSON | use projected mesh coordinates in meters; do not use lat/lon coordinates directly as mesh coordinates | `docs/format_spec.yaml`, `diagnostics/triplets.yaml` `dt_012` |
| `optimized_control` | inferred field | `varies (A in MPa^-3 yr^-1, or C in Weertman units)` | interpret by the selected control variable | `dag.yaml` |

---

## Unit Trap Table

| Variable | Source format | icepack format | Conversion | Trap |
|----------|-------------|----------------|------------|------|
| Velocity | m/s (satellite) | m/yr | × 3.15576e7 | Velocities ~0 if left in m/s |
| Ice thickness | m | m | none | Must be > 0 everywhere on mesh |
| Temperature | °C | K (Kelvin) | + 273.15 | rate_factor() expects K; wrong T → wrong A |
| Rate factor A | Pa^-3 s^-1 | MPa^-3 yr^-1 | complex | Use `icepack.rate_factor(T)` to compute |
| Accumulation | m w.e./yr | m ice/yr | × (ρ_w/ρ_i) ≈ ×1.09 | Slight bias if not converted |
| Gravity | 9.81 m/s² | 9.81×year² m/yr² | automatic | Defined in constants.py; do NOT override |
| Density ice | 917 kg/m³ | 917/year²×1e-6 | automatic | Defined in constants.py; do NOT override |
| Density water | 1024 kg/m³ | 1024/year²×1e-6 | automatic | Defined in constants.py; do NOT override |
| Friction C | site-specific | MPa·yr^(1/m)·m^(-1/m) | N/A | Must be calibrated; typical 0.01–0.1 |
| Fluidity A | T-dependent | MPa^-3 yr^-1 | use rate_factor() | ~1–100 for T in [-30, 0]°C |
| Strain rate | s^-1 | yr^-1 | × year | Regularized by strain_rate_min = 1e-5 |
| Mesh coordinates | m (projected) | m | none | Must use projected CRS (not lat/lon) |

---

## Validated Results

**Source of truth**: `docs/validation_convention.yaml`. These are the KI's
validation bars, not achieved run metrics. A run is judged against these cited
bands; null bands are recorded as `no cited threshold`.

### Headline Validation Bar

| DAG variable | Observation shape | Metric | Direction | Very good | Good | Satisfactory | Cites |
|--------------|-------------------|--------|-----------|-----------|------|--------------|-------|
| `velocity` | spatial snapshot | `rmse` | minimize | `<= 3.51 m/yr` (`polashenski2024`, `armstrong2016`) | `<= 5.66 m/yr` (`polashenski2024`, `armstrong2016`) | `<= 9.49 m/yr` (`polashenski2024`, `armstrong2016`) | `polashenski2024`, `armstrong2016` |

`velocity` is validated when velocity-field `rmse` is `<= 9.49 m/yr`
(`polashenski2024`, `armstrong2016`) against gridded surface-velocity
observations, with spatial residuals inspected rather than auto-validating by
`csi`.

### Convention Bars

| DAG variable | Metric | Direction | Very good | Good | Satisfactory | Cites |
|--------------|--------|-----------|-----------|------|--------------|-------|
| `velocity` | `rmse` | minimize | `<= 3.51 m/yr` (`polashenski2024`, `armstrong2016`) | `<= 5.66 m/yr` (`polashenski2024`, `armstrong2016`) | `<= 9.49 m/yr` (`polashenski2024`, `armstrong2016`) | `polashenski2024`, `armstrong2016` |
| `velocity` | `rmse` | minimize | no cited threshold | no cited threshold | `<= 10.95 m/yr` (`armstrong2016`) | `armstrong2016` |
| `velocity` | `nse` | maximize | no cited threshold | no cited threshold | no cited threshold | none |
| `thickness` | `rmse` | minimize | no cited threshold | no cited threshold | no cited threshold | none |

`optimized_control` is inferred rather than directly observed and is verified
through the `simulated_velocity` misfit and documented regularization tradeoff.

---

## Physics Models Reference

### IceShelf — Floating Ice

```python
model = icepack.models.IceShelf()
solver = icepack.solvers.FlowSolver(model, dirichlet_ids=[1])
u = solver.diagnostic_solve(velocity=u0, thickness=h, fluidity=A)
```

**Governing equation**: Shallow Shelf Approximation (SSA)
- Action: viscosity (membrane stress) − gravity (buoyancy-driven spreading)
- Key inputs: `velocity`, `thickness`, `fluidity`
- No bed interaction (floating)

### IceStream — Grounded Fast Ice

```python
model = icepack.models.IceStream()
solver = icepack.solvers.FlowSolver(model, dirichlet_ids=[1, 3])
u = solver.diagnostic_solve(velocity=u0, thickness=h, surface=s, fluidity=A, friction=C)
```

**Governing equation**: SSA + Weertman basal friction
- Action: viscosity + friction − gravity
- Key inputs: `velocity`, `thickness`, `surface`, `fluidity`, `friction`
- Friction law: τ = −C|u|^(1/m−1)·u, default m = 3

### ShallowIce — Slow Grounded Ice

```python
model = icepack.models.ShallowIce()
solver = icepack.solvers.FlowSolver(model)
u = solver.diagnostic_solve(velocity=u0, thickness=h, surface=s, fluidity=A)
```

**Governing equation**: Shallow Ice Approximation (SIA)
- For slow-flowing interior ice
- Key inputs: `velocity`, `thickness`, `surface`, `fluidity`

### HybridModel — 3D Velocity

```python
model = icepack.models.HybridModel()
# Requires extruded mesh
```

**Governing equation**: Full 3D with horizontal membrane + vertical shear
- Uses extruded meshes (2D footprint × vertical layers)
- Handles both fast-sliding and slow-flow regimes
- Key inputs: `velocity`, `thickness`, `surface`, `fluidity`, optionally `friction`

### Mass Continuity (Prognostic)

```python
h_new = solver.prognostic_solve(dt=1.0, thickness=h, velocity=u, accumulation=a)
```

- dt in **years** (icepack time unit)
- Lax-Wendroff scheme (2nd-order, default) or implicit Euler
- `accumulation`: net surface mass balance in m/yr

### Rate Factor

```python
A = icepack.rate_factor(T)  # T in Kelvin
```

- Arrhenius-type law: A = A₀·exp(−Q/(R·T))
- Transition at 263.15 K (−10°C):
  - Cold: A₀ = 3.985e-13 × year × 1e18, Q = 60 kJ/mol
  - Warm: A₀ = 1.916e3 × year × 1e18, Q = 139 kJ/mol

---

## Solver Configuration

### Diagnostic (Velocity) Solver

Default: PETSc SNES (Newton line search)

```python
solver_params = {
    "snes_type": "newtonls",
    "snes_linesearch_type": "nleqerr",
    "ksp_type": "gmres",
    "pc_type": "lu",
    "pc_factor_mat_solver_type": "mumps",
}
```

Options:
- `diagnostic_solver_type`: `'petsc'` (default) or `'icepack'` (deprecated)
- `diagnostic_solver_parameters`: PETSc options dict

### Prognostic (Thickness) Solver

Default: Lax-Wendroff (2nd-order)

Options:
- `prognostic_solver_type`: `'lax-wendroff'` (default) or `'implicit-euler'`
- `prognostic_solver_parameters`: PETSc options dict

---

## Data Access

icepack provides built-in data fetching via `icepack.datasets`:

| Function | Dataset | Region |
|----------|---------|--------|
| `fetch_measures_antarctica()` | MEaSUREs velocity | Antarctica |
| `fetch_measures_greenland()` | MEaSUREs velocity | Greenland |
| `fetch_bedmachine_antarctica()` | BedMachine | Antarctica |
| `fetch_bedmachine_greenland()` | BedMachine | Greenland |
| `fetch_outline(name)` | Glacier outlines | Both |
| `fetch_randolph_glacier_inventory()` | RGI v7.0 | Global |

**Requires**: NASA EarthData account for NSIDC datasets.

---

## Tools Reference

| Tool | Stage | Script | Purpose |
|------|-------|--------|---------|
| `convert_velocity_to_icepack` | s1 | `tools/convert_velocity_to_icepack.py` | MEaSUREs/raster → FEM velocity field (m/s→m/yr) |
| `convert_thickness_to_icepack` | s1 | `tools/convert_thickness_to_icepack.py` | BedMachine/raster → thickness, bed, surface fields |
| `run_icepack_simulation` | s4-s5 | `tools/run_icepack_simulation.py` | Execute diagnostic + prognostic simulation loop |
| `parse_icepack_output` | s7 | `tools/parse_icepack_output.py` | Extract velocity, thickness time series to CSV |

---

## Meshing

icepack supports three mesh generation backends:

1. **gmsh** (recommended): `icepack.meshing.collection_to_gmsh(collection, lcar=5000)`
2. **Triangle** (MeshPy): `icepack.meshing.collection_to_triangle(collection, max_volume=1e9)`
3. **pygmsh** (deprecated): `icepack.meshing.collection_to_geo(collection, lcar=5000)`

Input: GeoJSON FeatureCollection with glacier outline as LineString/MultiLineString features.

The `normalize()` function preprocesses the collection:
1. Flatten MultiLineStrings → LineStrings
2. Snap endpoints together
3. Reorient features head-to-tail
4. Topologize into loops
5. Reorder (bounding feature first)

---

## Inverse Problems

icepack supports statistical inference of unknown parameters (fluidity, friction)
from observed velocity data:

```python
problem = icepack.statistics.StatisticsProblem(
    simulation=simulation_fn,
    loss_functional=loss_fn,
    regularization=regularization_fn,
    controls=initial_guess
)
estimator = icepack.statistics.MaximumProbabilityEstimator(problem)
result = estimator.solve()
```

Uses ROL (Rapid Optimization Library) via pyadjoint for adjoint-based optimization.

---

## Available Glacier Outlines

```python
icepack.datasets.get_glacier_names()
# ['amery', 'filchner-ronne', 'getz', 'helheim', 'hiawatha',
#  'jakobshavn', 'larsen-2015', 'larsen-2018', 'larsen-2019',
#  'pine-island', 'ross']
```

---

## Common Workflow Example

```python
import firedrake
import icepack

# 1. Create mesh
mesh = firedrake.RectangleMesh(nx=64, ny=64, Lx=50e3, Ly=50e3)

# 2. Define function spaces
Q = firedrake.FunctionSpace(mesh, "CG", 2)   # scalars
V = firedrake.VectorFunctionSpace(mesh, "CG", 2)  # vectors

# 3. Set up fields
h = firedrake.Function(Q)  # thickness
u = firedrake.Function(V)  # velocity
A = firedrake.Function(Q)  # fluidity

# 4. Initialize with expressions or interpolated data
x, y = firedrake.SpatialCoordinate(mesh)
h.interpolate(500 - 100 * x / 50e3)
A.interpolate(firedrake.Constant(icepack.rate_factor(254.15)))

# 5. Create model and solver
model = icepack.models.IceShelf()
solver = icepack.solvers.FlowSolver(model, dirichlet_ids=[1])

# 6. Diagnostic solve
u = solver.diagnostic_solve(velocity=u, thickness=h, fluidity=A)

# 7. Time stepping
dt = 0.5  # years
for step in range(100):
    u = solver.diagnostic_solve(velocity=u, thickness=h, fluidity=A)
    h = solver.prognostic_solve(dt, thickness=h, velocity=u, accumulation=a)
```

---

## Key Physical Constants (from constants.py)

| Constant | Symbol | Value (icepack units) | Notes |
|----------|--------|-----------------------|-------|
| Seconds per year | year | 3.15576e7 | 365.25 × 86400 |
| Gravity | g | 9.75e15 m/yr² | 9.81 × year² |
| Ice density | ρ_I | 9.2e-19 MPa·yr²/m² | 917/(year²×1e6) |
| Water density | ρ_W | 1.03e-18 MPa·yr²/m² | 1024/(year²×1e6) |
| Glen exponent | n | 3.0 | Power-law exponent |
| Weertman exponent | m | 3.0 | Sliding law exponent |
| Ideal gas const | R | 8.3144621e-3 kJ/(mol·K) | |
| Min strain rate | ε_min | 1e-5 yr⁻¹ | Regularization |
| Melting temp | T_m | 273.15 K | At atmospheric pressure |
| Heat capacity | c | 2e3 × year² m²/yr²/K | |
| Thermal diffusivity | α | ~39.6 m²/yr | |
| Latent heat | L | 334e3 × year² m²/yr² | |
