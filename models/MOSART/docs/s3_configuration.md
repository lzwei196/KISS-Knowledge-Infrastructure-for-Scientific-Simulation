# Stage 3: Model Configuration

## Purpose

Create the `config.yaml` file that controls all aspects of a mosartwmpy simulation: time period, forcing paths, water management toggle, output settings, and numerical parameters. The configuration merges with built-in defaults — only values that differ from defaults need to be specified.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Grid file path | Stage 2 | Domain grid NetCDF |
| Runoff file path | Stage 1 | Forcing NetCDF |
| Demand file path | External/ABM | Monthly water demand NetCDF |
| Reservoir files | GRanD utilities | 4 reservoir parameter files |
| Simulation period | User | Start and end dates |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `config.yaml` | YAML | Complete simulation configuration |

## Procedure

### Step 1: Define simulation period and name

```yaml
simulation:
  name: my_simulation
  start_date: 1981-05-01
  end_date: 1981-05-31
```

### Step 2: Set timestep and subcycling

```yaml
simulation:
  timestep: 10800      # 3 hours (default)
  subcycles: 3         # subcycles per timestep
  routing_iterations: 5 # iterations per subcycle
```

**Effective time resolution**: `10800 / 3 / 5 = 720 seconds` (12 minutes) for main channel routing, further subdivided per cell based on CFL stability.

### Step 3: Configure grid path

```yaml
grid:
  path: ./input/domains/mosart_conus_nldas_grid.nc
```

### Step 4: Configure runoff forcing

```yaml
runoff:
  read_from_file: true
  path: ./input/runoff/runoff_{Y}_{M}.nc   # multi-file with year/month
  variables:
    surface_runoff: QOVER        # mm/s
    subsurface_runoff: QDRAI     # mm/s
    wetland_runoff: ~             # optional, null to disable
```

### Step 5: Configure water management (optional)

```yaml
water_management:
  enabled: true
  demand:
    read_from_file: true
    path: ./input/demand/demand_{Y}_{M}.nc
    demand: totalDemand           # m3/s
  reservoirs:
    enable_istarf: true
    parameters:
      path: ./input/reservoirs/reservoirs.nc
    dependencies:
      path: ./input/reservoirs/dependency_database.parquet
    streamflow:
      path: ./input/reservoirs/mean_monthly_reservoir_flow.parquet
    demand:
      path: ./input/reservoirs/mean_monthly_reservoir_demand.parquet
```

### Step 6: Configure output

```yaml
simulation:
  output_path: ./output
  output_resolution: 86400      # daily averaging
  output_file_frequency: monthly # one file per month
```

### Step 7: Optional subdomain configuration

```yaml
grid:
  subdomain:
    - 45.52,-122.68    # Portland, OR (Columbia River basin)
  unmask_output: true   # keep full grid in output
```

## Verification

- [ ] `start_date` is before `end_date`
- [ ] `output_resolution` is a multiple of `timestep`
- [ ] All file paths resolve to existing files
- [ ] Grid lat/lon matches runoff lat/lon
- [ ] Demand file covers simulation period (monthly)
- [ ] All 4 reservoir files exist if `water_management.enabled: true`

## Traps

### TRAP 1: Timestep too large for small basins
**Symptom**: Numerical instability, NaN values in discharge.
**Diagnosis**: CFL condition violated — water traverses multiple cells per step.
**Prevention**: Use default 10800s. For very steep/small basins, try 3600s.

### TRAP 2: Multi-file path template mismatch
**Symptom**: `FileNotFoundError` during simulation.
**Diagnosis**: Template `{Y}` expects `runoff_1981.nc` but files are `runoff_1981_05.nc`.
**Prevention**: Match template exactly to file naming: `{Y}` for year, `{M}` for month, `{D}` for day.

### TRAP 3: Water management enabled but reservoir files missing
**Symptom**: Crash during grid initialization.
**Diagnosis**: `water_management.enabled: true` but reservoir paths don't exist.
**Prevention**: Either provide all 4 reservoir files or set `enabled: false`.

### TRAP 4: Output resolution not a multiple of timestep
**Symptom**: `Exception` at initialization.
**Diagnosis**: e.g., `output_resolution: 43200` with `timestep: 10800` (not evenly divisible).
**Prevention**: Use `output_resolution: 86400` (daily) with `timestep: 10800` (3hr).

## Example

```yaml
# Minimal config.yaml for CONUS May 1981 tutorial
simulation:
  name: tutorial
  start_date: 1981-05-24
  end_date: 1981-05-26

grid:
  path: ./input/domains/mosart_conus_nldas_grid.nc

runoff:
  read_from_file: true
  path: ./input/runoff/runoff_1981_05.nc

water_management:
  enabled: true
  demand:
    read_from_file: true
    path: ./input/demand/demand_1981_05.nc
  reservoirs:
    enable_istarf: true
    parameters:
      path: ./input/reservoirs/reservoirs.nc
    dependencies:
      path: ./input/reservoirs/dependency_database.parquet
    streamflow:
      path: ./input/reservoirs/mean_monthly_reservoir_flow.parquet
    demand:
      path: ./input/reservoirs/mean_monthly_reservoir_demand.parquet
```
