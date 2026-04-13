# Stage 0: Configuration and Setup

## Purpose

Define the Ribasim model scope: study area, simulation period, coordinate reference
system, solver settings, and output preferences. This stage produces the `ribasim.toml`
configuration file that drives all subsequent stages.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| Study area definition | Spatial extent / description | User | Yes |
| Simulation period | Start/end dates (ISO 8601) | User | Yes |
| Coordinate Reference System | EPSG code string | User | Yes |
| Solver preferences | Algorithm, tolerances | User | Optional |
| Output frequency | Seconds | User | Optional (default: 86400) |

## Outputs

| Output | Format | Path |
|--------|--------|------|
| Configuration file | TOML | `<model_dir>/ribasim.toml` |
| Input directory | Directory | `<model_dir>/input/` |
| Results directory | Directory | `<model_dir>/results/` |

## Procedure

### Step 1: Choose simulation period

Select start and end dates. Ribasim uses ISO 8601 datetime format:
```toml
starttime = "2020-01-01"
endtime = "2021-01-01"
```

Ensure the period covers all time series data (forcing, boundary conditions).
Ribasim will error if boundary time series don't cover the full period.

### Step 2: Set coordinate reference system

Choose an appropriate CRS for the study area. Common choices:
- Netherlands: `EPSG:28992` (Amersfoort / RD New)
- Global: `EPSG:4326` (WGS84)
- UTM zones: `EPSG:326XX` for northern hemisphere

```toml
crs = "EPSG:28992"
```

All node coordinates and geometries must use this CRS.

### Step 3: Configure solver

The default QNDF solver works for most models. Key parameters:

```toml
[solver]
algorithm = "QNDF"        # Implicit multistep (recommended)
saveat = 86400             # Daily output (seconds)
abstol = 1e-5              # Absolute tolerance
reltol = 1e-5              # Relative tolerance
sparse = true              # Sparse Jacobian (faster for >20 nodes)
autodiff = true            # Automatic differentiation
depth_threshold = 0.1      # Low-storage reduction (m)
```

### Step 4: Configure allocation (optional)

If using water allocation:
```toml
[allocation]
timestep = 86400           # Daily allocation updates (seconds)
```

### Step 5: Create directory structure

```
my_model/
  ribasim.toml             # Configuration
  input/
    database.gpkg          # All model data
  results/                 # Output directory (created by Ribasim)
```

## Verification

1. Parse TOML with Python: `tomllib.load(open("ribasim.toml", "rb"))`
2. Check `starttime < endtime`
3. Verify CRS is a valid EPSG code
4. Confirm `input/` directory exists
5. Check `results/` directory is writable

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Time format | Fatal | Dates must be ISO 8601 strings (`"2020-01-01"`) or bare dates (`2020-01-01`). Other formats cause TOML parse errors. |
| saveat units | Silent | `saveat` is in **seconds**, not hours or days. `saveat = 24` gives output every 24 seconds, not 24 hours. Use `saveat = 86400` for daily. |
| allocation timestep | Silent | Also in **seconds**. `timestep = 1` means allocation every second (extremely slow). Use `timestep = 86400` for daily. |
| CRS mismatch | Silent | If node coordinates use a different CRS than declared, distances and areas will be wrong. No error is raised. |
| depth_threshold too high | Silent | Values > 1.0 m prevent basins from filling normally. Default 0.1 m is appropriate for most cases. |

## Example

```toml
# Minimal configuration for a 1-year daily simulation
starttime = "2020-01-01"
endtime = "2021-01-01"
crs = "EPSG:28992"
input_dir = "input"
results_dir = "results"
ribasim_version = "2026.1.0"

[solver]
algorithm = "QNDF"
saveat = 86400

[logging]
verbosity = "info"
```
