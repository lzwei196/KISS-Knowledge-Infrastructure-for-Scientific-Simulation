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

# Ribasim (Water Resources Model) — Knowledge Infrastructure

**Package**: `hydrocraft-ribasim` v1.0.0
**Model**: Ribasim 2026.1.0-rc2 (Deltares)
**Domain**: Water resources / regional surface water management
**Created by**: HydroCraft Auto-Dissect
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 18 diagnostic triplets
**Validation status**: `prototype`

---

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
