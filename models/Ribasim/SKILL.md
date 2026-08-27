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
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (14 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |
| what past runs learned | `.kdt_evolution.jsonl` | append-only memory of previous runs and fixes on this KI. |

*Projected 2026-08-24 from the KI's actual contents — 10 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_network.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_network.py --help` |
| `tools/convert_basin_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_basin_params.py --help` |
| `tools/parse_ribasim_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_ribasim_output.py --help` |
| `tools/run_ribasim.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_ribasim.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# Ribasim (Water Resources Model) — Knowledge Infrastructure

**Package**: `hydrocraft-ribasim` v1.0.0
**Model**: Ribasim 2026.1.0-rc2 (Deltares)
**Domain**: Water resources / regional surface water management
**Created by**: HydroCraft Auto-Dissect
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 18 diagnostic triplets
**Validation status**: `prototype`

---

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | Ribasim (Water Resources Model) |
| Package | `hydrocraft-ribasim` v1.0.0 |
| Model version | Ribasim 2026.1.0-rc2 (Deltares) |
| Language | Julia computational core; Python API for model building and I/O |
| Primary domain | Water resources / regional surface water management |
| Spatial mode | Directed water-network graph of nodes and links |
| Validation status | `prototype` |

---

## 2. What This Model Does

Ribasim routes water through engineered and natural surface-water networks represented as
directed graphs. It solves basin water balances, structure flows, control logic and
priority-based allocation; it is a network routing and allocation model, not a
rainfall-runoff generator.

---

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`** (projected from dag + triplets; regenerate it
after changing either source, never hand-edit it). This section explains the operational
intent and the traps; `docs/format_spec.yaml` is the schema contract.

### 3.1 Forcing And Boundary Inputs

| Input | Unit Ribasim expects | Typical source | Preparation note |
|-------|----------------------|----------------|------------------|
| Basin precipitation | m/s | ERA5, CMFD, MSWX, stations | Convert vertical fluxes before writing `Basin / static` or `Basin / time`. |
| Basin evaporation | m/s | ERA5, CMFD, MSWX, stations | Same vertical-flux conversion as precipitation. |
| Boundary inflow | m³/s | VIC, SWAT+, CaMa-Flood, gauges | Bind to `FlowBoundary / static` or time-varying flow boundary data. |
| Boundary level | m | Gauge records, downstream water-level model | Bind to `LevelBoundary / static` or time-varying level boundary data; datum consistency is required. |
| Demands | m³/s | Cadastral, operational or planning demand data | Bind to `UserDemand / time` with priority and return-flow information. |

### 3.2 Static Inputs

| Input | Source | Tool or section that prepares it |
|-------|--------|----------------------------------|
| Network topology | User-defined CSV/shapefile/GeoPackage | `tools/build_network.py` |
| Basin profiles | Surveys, DEM or lake/reservoir databases | `tools/convert_basin_params.py` |
| Structures | Operations manuals or site configuration | Python API / manual GeoPackage tables |
| Controls | Operations manuals or site configuration | Python API / manual GeoPackage tables |
| Allocation subnetworks and priorities | Planning or operational rules | Python API / manual GeoPackage tables |

### 3.3 Configuration Files

| File | Format | Notes |
|------|--------|-------|
| `ribasim.toml` | TOML | Main run configuration: time range, CRS, input/results directories, solver and allocation settings. |
| `input/database.gpkg` | GeoPackage / SQLite spatial | Main model database containing Node, Link and node-type parameter tables. |
| Optional time series | NetCDF | Time-varying tables can be referenced from TOML when not stored directly in the GeoPackage. |

---

## 4. Build Instructions

Run the KI preflight before any execution attempt:

```bash
python preflight_check.py
```

Install or expose the real Ribasim binary/package described by this KI; do not substitute a
Python formula or hand-coded approximation. If import, compile or execution fails, follow the
mandatory execution policy at the top of this file.

---

## 5. Execution

```bash
ribasim ribasim.toml
python tools/run_ribasim.py --help
python tools/run_ribasim.py <model_dir_or_config>
```

Read each tool's `--help` before composing a pipeline command. Stage-specific procedure and
verification details live in `docs/s*_*.md`.

---

## 6. Output Description

**Source: `dag.yaml`.** The dag is the model identity for observable outputs; if this section
and `dag.yaml` disagree, `dag.yaml` wins.

**Headline output** (the dag's rank-1 variable):

> `flow_rate` — Water flow rate on each network link (per from_node→to_node connection). (m³/s)

| Output variable (dag `var`) | Rank / status | Unit / status | Dag fact restated here |
|-----------------------------|---------------|---------------|------------------------|
| `flow_rate` | 1 | m³/s | Water flow rate on each network link (per from_node→to_node connection). |
| `level` | other dag output | dag output listed | Listed in the supplied dag output facts. |
| `storage` | other dag output | dag output listed | Listed in the supplied dag output facts. |
| `balance_error / relative_error` | other dag output | dag output listed | Listed in the supplied dag output facts. |
| `allocated / supplied / demand` | other dag output | dag output listed | Listed in the supplied dag output facts. |

Do not infer extra headline variables from NetCDF filenames. For scoring and observation
binding, use the dag variables above and read `dag.yaml` directly when full metadata is needed.

---

## 7. Tool Inventory

| Tool | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `tools/build_network.py` | Build Node/Link tables and TOML scaffolding | CSV/shapefile inputs and configuration | GeoPackage network tables and `ribasim.toml` |
| `tools/convert_basin_params.py` | Convert basin profiles and forcing into Ribasim-ready units | Basin data, forcing and morphometry | Basin profile, state, static and time tables |
| `tools/run_ribasim.py` | Execute the real Ribasim model with checks | Complete model directory or configuration | Ribasim results in `results_dir` |
| `tools/parse_ribasim_output.py` | Parse NetCDF outputs and compute summaries/metrics | Ribasim NetCDF results and optional observations | CSV outputs, plots and metric tables |

### Shared Utilities

Use the shared KI utilities when applicable:

```python
from ki_tools_common.load_forcing import load_daily_forcing
from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_forcing_ranges
from ki_tools_common.units import convert
```

---

## 8. Unit Conversion Table

Every unit conversion must be verified against the actual source data attributes before a
production run. These are the Ribasim-side units this KI expects.

| Variable | Source unit | Model unit | Conversion | Risk if wrong |
|----------|-------------|------------|------------|---------------|
| Precipitation | mm/day | m/s | divide by 86400000 | Silent magnitude error |
| Evaporation | mm/day | m/s | divide by 86400000 | Silent magnitude error |
| Flow rate | L/s | m³/s | divide by 1000 | Silent magnitude error |
| Flow rate | ML/day | m³/s | divide by 86.4 | Silent magnitude error |
| Level | cm | m | divide by 100 | Silent magnitude or datum error |
| Area | km² | m² | multiply by 1000000 | Silent storage/profile error |
| Area | ha | m² | multiply by 10000 | Silent storage/profile error |
| Storage | MCM | m³ | multiply by 1000000 | Silent storage error |
| Storage | ML | m³ | multiply by 1000 | Silent storage error |
| Solver timestep | hours | seconds | multiply by 3600 | Silent timestep error |
| Solver timestep | days | seconds | multiply by 86400 | Silent timestep error |
| Allocation timestep | days | seconds | multiply by 86400 | Silent timestep error |

---

## 8c. Sign Conventions And Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| `flow_rate` | m³/s on each network link, per `from_node→to_node` connection | Node-local or basin-total discharge | Wrong observation binding and link direction. |
| `level` | m, with the configured CRS/vertical datum | Local datum or cm | Apparent bias caused by datum or scale mismatch. |
| `storage` | m³ from basin area-level-storage profile | ML or MCM | Incorrect water-balance magnitude. |
| Precipitation / evaporation | m/s vertical fluxes | mm/day or mm/hr | Extreme water-balance error. |
| `balance_error / relative_error` | Diagnostic water-balance outputs | Treated as physical flux | False validation metric or masked solver issue. |

Output unit verification checklist:
- Read `units` attributes from output NetCDF variables before computing metrics.
- Inspect first values and time coordinates for order-of-magnitude and timestep mistakes.
- For `flow_rate`, confirm the link id and `from_node→to_node` direction before comparing to gauges.
- For `level`, confirm the observation and model use the same vertical datum.

---

## 9. Diagnostic Triplets (Top 5)

The full diagnostic corpus remains in `diagnostics/triplets.yaml`; check it before debugging.

| # | Error | Diagnosis | Remedy |
|---|-------|-----------|--------|
| `dt_001` | Precipitation in mm/day instead of m/s | Vertical flux unit mismatch | Convert mm/day to m/s before writing Ribasim basin forcing. |
| `dt_002` | Evaporation in mm/day instead of m/s | Vertical flux unit mismatch | Convert mm/day to m/s before writing Ribasim basin forcing. |
| `dt_003` | Area in km² instead of m² | Basin profile area unit mismatch | Convert km² to m² before writing area-level curves. |
| `dt_004` | Flow boundary in L/s instead of m³/s | Boundary flow unit mismatch | Convert L/s to m³/s before writing flow boundary data. |
| `dt_005` | Allocation timestep in days instead of seconds | Configuration timestep unit mismatch | Convert days to seconds in allocation settings. |

---

## 10. Coupling Interfaces

| Upstream model | Variable exchanged | Unit | Temporal resolution |
|----------------|--------------------|------|---------------------|
| VIC / SWAT+ | Runoff to `FlowBoundary` | m³/s | Match Ribasim `saveat` or boundary time series |
| CaMa-Flood | Discharge to `FlowBoundary` | m³/s | Match Ribasim `saveat` or boundary time series |
| ERA5 / CMFD / MSWX | Precipitation and evaporation to Basin forcing | m/s | Convert from source cadence before writing |
| Observations | Water levels to `LevelBoundary` or validation targets | m | Match datum and timestamp convention |

| Downstream model | Variable exchanged | Unit | Temporal resolution |
|------------------|--------------------|------|---------------------|
| CaMa-Flood | Basin outflow / lateral inflow | m³/s | Match downstream routing timestep |
| DELWAQ | Flows for water quality coupling | m³/s | Match coupling timestep |

---

## 11. Validated Results

This KI has validation status `prototype`; body campaign pending. No validated basin/body campaign result is recorded
in this SKILL body. Treat validation metrics as pending until a run is executed with the real
Ribasim binary/package and scored against `docs/validation_convention.yaml`.

### Performance Bars From `docs/validation_convention.yaml`

| Dag variable | Metric | Direction | Convention bar, with citation keys |
|--------------|--------|-----------|------------------------------------|
| `flow_rate` | NSE | maximize | very_good ≥ 0.75 (`moriasi2007`, `moriasi2015`, `shrestha2018`); good ≥ 0.65 (`moriasi2007`, `moriasi2015`, `shrestha2018`); satisfactory ≥ 0.5 (`moriasi2007`, `moriasi2015`, `shrestha2018`) |
| `flow_rate` | PBIAS | zero_centered | very_good ≤ 10 absolute percent bias (`moriasi2015`, `shrestha2018`); good ≤ 15 absolute percent bias (`moriasi2015`, `shrestha2018`); satisfactory ≤ 15 absolute percent bias (`moriasi2015`, `shrestha2018`) |
| `level` | NSE | maximize | satisfactory: no cited threshold |
| `storage` | NSE | maximize | satisfactory: no cited threshold |

### Campaign Tracking

| Component | Status | Notes |
|-----------|--------|-------|
| Body / basin validation campaign | Pending | No achieved metric is recorded in this SKILL body. |
| Headline score target | Pending | `flow_rate` is the dag rank-1 output. |
| Judgment standard | Available | Use the cited convention bars above; do not invent thresholds for null bands. |

---

## 12. Parameter Selection By Region

Ribasim parameter choices are site- and operations-specific. Use physically informed starting
points from surveys, DEM/lake morphometry, operational rules and observed inflow/level records;
then validate against the dag variables and the cited convention bars above. Do not treat these
starting points as calibration results.

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: Input from upstream hydrological models.
See `data_ki/GRanD/SKILL.md` for dam/reservoir database.
See `data_ki/HydroLAKES/SKILL.md` for lake morphometry.


## Overview

Ribasim is an open-source water resources model developed by Deltares (Netherlands) as a
replacement for the regional surface water modules Mozart and SIMRES in the Netherlands
Hydrological Instrument (NHI). It models water distribution networks as directed graphs
where nodes represent water system components (basins, pumps, weirs, demands) and edges
represent flow connections. The computational core is written in Julia using the SciML
ODE solver ecosystem; the Python API provides programmatic model building and I/O.

**What Ribasim models**:
- Water balance of interconnected basins (reservoirs, lakes, canals, rivers)
- Flow through controlled structures (pumps, outlets, weirs, rating curves)
- Rule-based and PID control of hydraulic structures
- Priority-based water allocation via linear programming (HiGHS solver)
- Manning and linear resistance flow between basins
- Tracer transport and concentration (experimental)

**Three-layer architecture**:
1. **Physical layer**: ODE-based water balance (du/dt = inflows − outflows)
2. **Control layer**: Discrete/continuous/PID control of structure parameters
3. **Allocation layer**: Optimization-based water distribution across demand nodes

**Key difference from hydrological models (VIC, SWAT+)**: Ribasim is a *network routing*
model, not a rainfall-runoff model. It takes external inflows/outflows as boundary
conditions and routes water through an engineered network with control rules.

---

## Installation

### Pre-built binary (recommended)

Download from GitHub releases:
- Linux: `ribasim_linux.zip` → extract → `ribasim` CLI executable
- Windows: `ribasim_windows.zip` → extract → `ribasim.exe`

```bash
# Extract and make executable
unzip ribasim_linux.zip -d ribasim_bin/
chmod +x ribasim_bin/bin/ribasim
export PATH="$PWD/ribasim_bin/bin:$PATH"
ribasim --version
```

### From source (Julia + Python)

```bash
# Requires: Julia 1.12.5, Python >=3.12, pixi package manager
pip install ribasim          # Python API only
# OR full dev install:
pixi install                 # Installs Julia + Python + all deps
pixi run build               # Builds standalone CLI binary
```

### Python API only

```bash
pip install ribasim
# Dependencies: geopandas, pandas, pydantic, shapely, netCDF4, pyarrow, xarray, pyogrio
```

### Test installation

```bash
ribasim --version            # Should print version
python -c "import ribasim; print(ribasim.__version__)"
```

---

## Input Format

### Configuration: `ribasim.toml`

The main entry point is a TOML configuration file with these sections:

```toml
starttime = "2020-01-01"
endtime = "2021-01-01"
crs = "EPSG:28992"
input_dir = "input"
results_dir = "results"
ribasim_version = "2026.1.0-rc2"

[solver]
algorithm = "QNDF"          # ODE solver (QNDF, FBDF, Rosenbrock23, Rodas4P)
saveat = 86400               # Output interval in seconds (86400 = daily)
dt = 0                       # Fixed timestep (0 = adaptive)
dtmin = 0.0                  # Minimum adaptive timestep
dtmax = 0.0                  # Maximum adaptive timestep (0 = unlimited)
abstol = 1e-5                # Absolute solver tolerance
reltol = 1e-5                # Relative solver tolerance
water_balance_abstol = 1e-3  # Water balance error tolerance (absolute)
water_balance_reltol = 1e-2  # Water balance error tolerance (relative)
sparse = true                # Use sparse Jacobian
autodiff = true              # Use automatic differentiation
depth_threshold = 0.1        # Low-storage reduction threshold (m)

[allocation]
timestep = 86400             # Allocation update interval (seconds)

[logging]
verbosity = "info"           # debug, info, warn, error

[results]
compression = true           # NetCDF compression
compression_level = 1        # Deflate level 0-9
subgrid = false              # Detailed subgrid levels
```

### Database: `input/database.gpkg`

A GeoPackage (SQLite + spatial) containing all model data:

| Table | Contents | Key Columns |
|-------|----------|-------------|
| `Node` | All node definitions | node_id, node_type, name, subnetwork_id, geometry (Point) |
| `Link` | All connections | from_node_id, to_node_id, link_type ("flow"/"control"), geometry (LineString) |
| `Basin / profile` | Area-level curves | node_id, level (m), area (m²), storage (m³) |
| `Basin / state` | Initial conditions | node_id, level (m) |
| `Basin / static` | Constant forcing | node_id, precipitation (m/s), evaporation (m/s), drainage (m³/s), infiltration (m³/s) |
| `Basin / time` | Time-varying forcing | node_id, time, precipitation (m/s), evaporation (m/s), etc. |
| `Pump / static` | Pump parameters | node_id, flow_rate (m³/s), min_upstream_level (m) |
| `TabulatedRatingCurve / static` | Q(h) lookup | node_id, level (m), flow_rate (m³/s) |
| `LinearResistance / static` | Linear flow | node_id, resistance (s/m²), max_flow_rate (m³/s) |
| `ManningResistance / static` | Manning flow | node_id, length (m), manning_n (s·m⁻¹/³), profile_width (m), profile_slope |
| `Outlet / static` | Gravity outflow | node_id, flow_rate (m³/s), min_upstream_level (m) |
| `FlowBoundary / static` | External inflow | node_id, flow_rate (m³/s) |
| `LevelBoundary / static` | External level | node_id, level (m) |
| `UserDemand / time` | Water demand | node_id, time, demand (m³/s), return_factor, min_level (m), demand_priority |
| `DiscreteControl / condition` | Control rules | node_id, listen_node_id, variable, threshold_high, threshold_low |
| `DiscreteControl / logic` | Control mapping | node_id, truth_state, control_state |
| `PidControl / static` | PID params | node_id, listen_node_id, target (m), proportional, integral, derivative |

### Time series: NetCDF (optional)

Time-varying data can alternatively be stored as NetCDF files referenced in the TOML:
```toml
[basin]
time = "basin/time.nc"
```

---

## Node Types (15+)

| Node Type | Category | State | Description |
|-----------|----------|-------|-------------|
| Basin | Storage | Yes (level) | Water body with area-level-storage profile |
| Pump | Structure | No | Uphill water transfer (controlled flow) |
| Outlet | Structure | No | Gravity-driven outflow |
| TabulatedRatingCurve | Structure | No | Level-dependent Q(h) relationship |
| LinearResistance | Structure | No | Q = Δh / R (bidirectional) |
| ManningResistance | Structure | No | Manning-Gauckler friction flow |
| FlowBoundary | Boundary | No | External prescribed inflow (m³/s) |
| LevelBoundary | Boundary | No | External prescribed water level (m) |
| UserDemand | Demand | No | Water extraction with allocation priority |
| FlowDemand | Demand | No | Flow-based allocation demand |
| LevelDemand | Demand | No | Level-based allocation demand |
| DiscreteControl | Control | No | Rule-based parameter switching |
| ContinuousControl | Control | No | Smooth function-based control |
| PidControl | Control | Yes (integral) | PID controller for level regulation |
| Junction | Utility | No | Flow confluence (no storage) |
| Terminal | Utility | No | Model boundary (water leaves) |

---

## Pipeline Stages

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Define study area, period, CRS, node layout |
| 1 | Network definition | `build_network.py` | Create Node/Link tables in GeoPackage |
| 2 | Basin parameters | `convert_basin_params.py` | Build area-level profiles and forcing |
| 3 | Structure parameters | (manual/Python API) | Configure pumps, weirs, resistances |
| 4 | Control rules | (manual/Python API) | Set up discrete/PID/continuous control |
| 5 | Allocation config | (manual/Python API) | Define subnetworks and demand priorities |
| 6 | TOML generation | `build_network.py` | Write ribasim.toml configuration |
| 7 | Execution | `run_ribasim.py` | Run Ribasim CLI with preflight checks |
| 8 | Output analysis | `parse_ribasim_output.py` | Parse NetCDF results to CSV/plots |

### Parallelism

Stages 1-5 can proceed in parallel for independent sub-components.
Stage 6 depends on all parameter stages.
Stage 7 depends on 6.
Stage 8 depends on 7.

---

## Unit Trap Table

| Variable | Ribasim Unit | Common Alternative | Conversion | Trap Severity |
|----------|-------------|-------------------|------------|---------------|
| Precipitation | m/s | mm/day | mm/day ÷ 86400000 | **SILENT** — 1000x error |
| Evaporation | m/s | mm/day | mm/day ÷ 86400000 | **SILENT** — 1000x error |
| Flow rate | m³/s | L/s, ML/day | L/s ÷ 1000; ML/day ÷ 86.4 | **SILENT** |
| Level | m (datum) | m AHD, cm | Must match CRS vertical datum | **SILENT** — offset |
| Area | m² | km², ha | km² × 1e6; ha × 1e4 | **SILENT** — basin drains instantly |
| Storage | m³ | MCM, ML | MCM × 1e6; ML × 1e3 | **SILENT** |
| Resistance | s/m² | — | Native unit | Conceptual trap |
| Manning n | s·m⁻¹/³ | — | Native unit | Range: 0.01-0.1 |
| Solver timestep | seconds | hours, days | hours × 3600; days × 86400 | **SILENT** |
| Allocation timestep | seconds | days | days × 86400 | **SILENT** |
| PID proportional | s⁻¹ | — | Dimensionless gain / s | Sign trap |
| PID integral | s⁻² | — | — | Sign trap |
| Depth threshold | m | cm | cm ÷ 100 | Solver instability |
| Time | DateTime string | epoch seconds | ISO 8601 format required | **FATAL** |

### Critical unit conversion: precipitation and evaporation

Ribasim uses **meters per second** for vertical fluxes. This is unusual — most
hydrological models use mm/day or mm/hr. The conversion factor is:

```
1 mm/day = 1e-3 m / 86400 s = 1.157e-8 m/s
```

A typical precipitation rate of 5 mm/day becomes 5.787e-8 m/s in Ribasim.
If you pass mm/day directly, the basin receives ~86 million times too much water.

---

## Execution

### CLI

```bash
ribasim ribasim.toml                    # Run model
ribasim ribasim.toml --threads 4        # Multi-threaded
ribasim --version                       # Print version
```

### Python API

```python
import ribasim

# Method 1: Run existing model
ribasim.run_ribasim("path/to/ribasim.toml")

# Method 2: Build and run programmatically
model = ribasim.Model(
    starttime="2020-01-01",
    endtime="2021-01-01",
    crs="EPSG:28992",
)
# Add nodes, links, parameters...
model.write("output_dir/ribasim.toml")
ribasim.run_ribasim("output_dir/ribasim.toml")
```

### Environment variables

| Variable | Purpose |
|----------|---------|
| `RIBASIM_HOME` | Path to Ribasim installation directory |
| `JULIA_NUM_THREADS` | Number of Julia threads |

---

## Output Format

All outputs are NetCDF4 files in the `results_dir`:

| File | Contents | Key Variables |
|------|----------|---------------|
| `basin.nc` | Basin water balance | level, storage, precipitation, evaporation, infiltration, drainage, inflow_rate, outflow_rate, balance_error |
| `flow.nc` | Link flow rates | flow_rate (m³/s) per link per timestep |
| `basin_state.nc` | Final basin states | level (m) — usable as restart |
| `control.nc` | Control state changes | control_state, truth_state per control node |
| `allocation.nc` | Allocation results | demand, allocated, supplied per demand node |
| `allocation_flow.nc` | Allocation flows | Optimized flows on allocation links |
| `subgrid_level.nc` | Detailed levels | Sub-basin water level variations |
| `solver_stats.nc` | Solver metrics | dt, iterations, convergence |
| `concentration.nc` | Tracer data | Substance concentrations (experimental) |

### Output dimensions

- `time`: Timestamps at `saveat` intervals
- `node_id`: Basin or demand node identifiers
- `link_id`: Flow link identifiers
- `substance`: Tracer names (if concentration enabled)

### Reading outputs

```python
import xarray as xr

# Basin results
ds = xr.open_dataset("results/basin.nc")
level = ds["level"].sel(node_id=1)
level.plot()

# Flow results
flow = xr.open_dataset("results/flow.nc")
```

---

## Tools Reference

| Tool | Script | Lines | Purpose |
|------|--------|------:|---------|
| `build_network` | `tools/build_network.py` | ~280 | Build GeoPackage from CSV/shapefile inputs |
| `convert_basin_params` | `tools/convert_basin_params.py` | ~250 | Convert external forcing/params to Ribasim units |
| `run_ribasim` | `tools/run_ribasim.py` | ~200 | Execute Ribasim with validation and error handling |
| `parse_ribasim_output` | `tools/parse_ribasim_output.py` | ~220 | Extract NetCDF results to CSV with metrics |

---

## Solver Configuration Guide

| Parameter | Default | When to Change |
|-----------|---------|----------------|
| algorithm | QNDF | Try FBDF for stiff systems; Rosenbrock23 for small models |
| saveat | 86400 | Reduce for sub-daily output (3600 = hourly) |
| abstol | 1e-5 | Increase to 1e-3 for faster runs; decrease for precision |
| reltol | 1e-5 | Same as abstol |
| sparse | true | Set false for small models (<20 nodes) |
| autodiff | true | Set false if Julia AD errors occur |
| depth_threshold | 0.1 | Reduce for shallow basins; increase for stability |
| water_balance_abstol | 1e-3 | Tighten for validation runs |

---

## Calibration Parameters (Priority Order)

| Parameter | Node Type | Range | Controls | Sensitivity |
|-----------|-----------|-------|----------|-------------|
| Basin profile (area-level) | Basin | Site-specific | Storage-level relationship | **HIGH** |
| resistance | LinearResistance | 1e2 - 1e8 s/m² | Inter-basin flow rate | **HIGH** |
| manning_n | ManningResistance | 0.01 - 0.10 | Channel friction | **HIGH** |
| flow_rate | Pump/Outlet | 0 - Qmax m³/s | Structure capacity | **MEDIUM** |
| depth_threshold | Solver | 0.01 - 1.0 m | Low-storage behavior | **MEDIUM** |
| precipitation/evaporation | Basin | Measured | Water balance forcing | **HIGH** |
| demand_priority | UserDemand | 1 - 10 | Allocation precedence | **LOW** |

---

## Coupling Points

| # | Source | Target | Variable | Notes |
|---|--------|--------|----------|-------|
| 1 | VIC/SWAT+ | Ribasim | Runoff → FlowBoundary | Convert m³/s |
| 2 | CaMa-Flood | Ribasim | Discharge → FlowBoundary | At basin inlet |
| 3 | Ribasim | CaMa-Flood | Basin outflow → lateral inflow | At basin outlet |
| 4 | ERA5/CMFD | Ribasim | Precip/evap → Basin forcing | Convert mm/day → m/s |
| 5 | Observations | Ribasim | Water levels → LevelBoundary | For calibration |
| 6 | Ribasim | DELWAQ | Flows → water quality model | Built-in coupling |

---

## Data Requirements

| Data | Source | Format | Purpose |
|------|--------|--------|---------|
| Network topology | User-defined | GeoPackage | Node positions and connections |
| Basin profiles | Surveys/DEM | CSV → GeoPackage | Area-level-storage curves |
| Meteorological forcing | ERA5/CMFD/stations | CSV → m/s | Precipitation, evaporation |
| Boundary inflows | VIC/CaMa/gauges | CSV → m³/s | FlowBoundary time series |
| Water demands | Cadastral/planning | CSV → m³/s | UserDemand time series |
| Control rules | Operations manuals | Manual entry | DiscreteControl conditions |
| Initial levels | Observations/guess | GeoPackage | Basin / state table |

---

## Quick Start

```python
import ribasim
from ribasim import Model, Node
from shapely.geometry import Point
import pandas as pd
import geopandas as gpd

# 1. Create model
model = Model(
    starttime="2020-01-01",
    endtime="2020-12-31",
    crs="EPSG:28992",
)

# 2. Add basin with profile
model.basin.add(
    Node(1, Point(0, 0), name="Reservoir"),
    [
        ribasim.Basin.Profile(area=[1000, 10000, 50000], level=[0, 5, 10]),
        ribasim.Basin.State(level=[5]),
        ribasim.Basin.Static(precipitation=[5.787e-8], evaporation=[2.315e-8]),
    ],
)

# 3. Add flow boundary (inflow)
model.flow_boundary.add(
    Node(2, Point(1, 0), name="Inflow"),
    [ribasim.FlowBoundary.Static(flow_rate=[10.0])],  # 10 m³/s
)

# 4. Add outlet
model.outlet.add(
    Node(3, Point(-1, 0), name="Spillway"),
    [ribasim.Outlet.Static(flow_rate=[8.0])],  # 8 m³/s max
)

# 5. Add terminal
model.terminal.add(Node(4, Point(-2, 0), name="Downstream"))

# 6. Connect nodes
model.link.add(model.flow_boundary[2], model.basin[1])
model.link.add(model.basin[1], model.outlet[3])
model.link.add(model.outlet[3], model.terminal[4])

# 7. Write and run
model.write("my_model/ribasim.toml")
ribasim.run_ribasim("my_model/ribasim.toml")
```

---

## Diagnostic Triplets Summary

18 triplets covering 5 failure domains. See `diagnostics/triplets.yaml` for full details.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | **silent** | unit_conversion | Precipitation in mm/day instead of m/s |
| dt_002 | **silent** | unit_conversion | Evaporation in mm/day instead of m/s |
| dt_003 | **silent** | unit_conversion | Area in km² instead of m² |
| dt_004 | **silent** | unit_conversion | Flow boundary in L/s instead of m³/s |
| dt_005 | **silent** | unit_conversion | Allocation timestep in days instead of seconds |
| dt_006 | fatal | parameter_format | Basin profile not monotonically increasing |
| dt_007 | fatal | parameter_format | Missing Basin / state table (no initial level) |
| dt_008 | fatal | parameter_format | Node connectivity validation failure |
| dt_009 | **silent** | parameter_format | CRS mismatch between data and model |
| dt_010 | **silent** | silent_error | Resistance too high → no flow between basins |
| dt_011 | **silent** | silent_error | depth_threshold too high → basin never fills |
| dt_012 | **silent** | silent_error | PID gains wrong sign → oscillation/instability |
| dt_013 | fatal | runtime | Solver divergence from extreme forcing |
| dt_014 | degraded | runtime | Water balance error exceeds tolerance |
| dt_015 | **silent** | silent_error | saveat too large → misses dynamics |
| dt_016 | **silent** | dependency_mismatch | Boundary timeseries gaps → zero flow |
| dt_017 | fatal | path_resolution | GeoPackage path not found |
| dt_018 | fatal | path_resolution | NetCDF time series file not found |

**Silent error count**: 10/18 (56%) — dominated by unit conversion traps.

---

## File Structure

```
ki/
  SKILL.md                          # This file (agent entry point)
  tools/
    build_network.py                # Network builder from CSV/shapefiles
    convert_basin_params.py         # Basin parameter/forcing converter
    run_ribasim.py                  # Execution wrapper with validation
    parse_ribasim_output.py         # Output parser to CSV
  docs/
    s0_configuration.md             # Configuration and setup
    s1_network_definition.md        # Network topology creation
    s2_basin_parameters.md          # Basin forcing and profiles
    s3_execution.md                 # Running the model
    s4_output_analysis.md           # Parsing and analyzing results
  diagnostics/
    triplets.yaml                   # 18 diagnostic triplets
```
