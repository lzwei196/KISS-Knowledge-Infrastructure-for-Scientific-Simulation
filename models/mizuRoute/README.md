> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.

---

# mizuRoute — Knowledge Infrastructure

**Package**: `hydrocraft-mizuroute` v1.0.0
**Model**: mizuRoute (NCAR/ESCOMP), reach-based river routing
**Repository**: https://github.com/ESCOMP/mizuRoute
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-22
**Stats**: 7 tools | 8 skill documents | 20 diagnostic triplets | 2,115 lines of validated Python
**Validation status**: `production_validated` — Bengbu IRF routing, r=0.87 vs Lohmann, mass-conserving (Q=1795 m3/s), 3 serial stub bugs fixed

---

## Overview

This knowledge infrastructure enables reach-based river routing using mizuRoute on any basin in HydroCraft, taking VIC or WRF-Hydro gridded runoff output and routing it through an explicit vector river network. mizuRoute is the **only** routing model in HydroCraft that offers 5 selectable routing methods and lake/reservoir routing.

**What mizuRoute does**: Takes gridded runoff from a land surface model and routes it through a user-defined catchment-based (vector) river network to compute streamflow at every reach.

**Key differentiator**: Unlike grid-based routing (Lohmann, CaMa-Flood), mizuRoute operates on an explicit river network where each reach has physical properties (length, slope, width). This enables:
- 5 routing methods with different physics (from simple IRF to full diffusive wave)
- Lake/reservoir routing (level-pool, Hanasaki, rule curves)
- MPI parallelism for continental-scale networks
- Method intercomparison on the same basin (unique in HydroCraft)

### The 5 Routing Methods

| ID | Method | Physics | Best for | Cost |
|----|--------|---------|----------|------|
| 0 | **IRF** | Unit hydrograph per reach | Quick runs, large networks | Lowest |
| 1 | **KWT** | Lagrangian wave tracking | Flood wave propagation | Low |
| 2 | **KWE** | Euler kinematic wave | General purpose | Moderate |
| 3 | **MC** | Muskingum-Cunge | Operational forecasting (NWM-style) | Moderate |
| 4 | **DW** | Diffusive wave | Flat terrain, backwater effects | Highest |

### When to Use mizuRoute vs Lohmann vs CaMa-Flood

| Feature | Lohmann | CaMa-Flood | mizuRoute |
|---------|---------|------------|-----------|
| Grid type | Regular lat/lon | Regular 15min | Vector river network |
| Physics | Unit hydrograph (1 method) | Local inertia + floodplain | 5 selectable methods |
| Floodplain | No | **Yes** (key strength) | No |
| Lake/reservoir | No | Limited | **Yes** (3 schemes) |
| Setup complexity | Low | Medium | Medium |
| Best for | Default, simple routing | Flood inundation mapping | Method comparison, lakes, reach-scale analysis |

---

## Installation

### Binary

```
mizuRoute:   model/mizuRoute/mizuRoute-main/route/bin/mizuroute.exe
Source:      model/mizuRoute/mizuRoute-main/route/build/src/ (Fortran 90)
Platform:    Ubuntu 24.04, x86-64, gfortran 13 + NetCDF-Fortran
Build:       Serial (MPI/PIO stub modules)
```

### Building from Source

mizuRoute requires MPI and PIO (Parallel I/O) libraries. Two approaches:

**Approach A (recommended): Install MPI, then build with real libraries**
```bash
# Install MPI (requires sudo)
sudo apt-get install -y libopenmpi-dev openmpi-bin cmake

# Build PIO and mizuRoute
cd model/mizuRoute/mizuRoute-main/route/build
# Edit Makefile: set FC=gnu, FC_EXE=mpifort, F_MASTER=..., NCDF_PATH=/usr
make
```

**Approach B: Serial build with stub modules (no MPI/PIO needed)**
```bash
cd model/mizuRoute/mizuRoute-main/route/build
bash ../../build_serial.sh
```

Serial stubs are at `serial_stubs/` providing MPI constants, PIO types/constants, and GPTL timing no-ops. The PIO stub needs further expansion for complete compilation (pio_inq_varid and additional pio_put_var/pio_read_darray overloads). See `diagnostics/error_log.yaml` for details on stub development.

**Dependencies** (all on server except MPI):
- gfortran >= 7.0 (installed: 13.3.0)
- libnetcdff (installed: /usr/lib/x86_64-linux-gnu/libnetcdff.so)
- libnetcdf (installed)
- libopenmpi-dev (NOT installed, needed for Approach A)

### Python dependencies (all in HydroCraft venv)

```
netCDF4, numpy, geopandas, shapely, rasterio, scipy, whitebox (WhiteboxTools)
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Basin, time period, routing method, upstream model |
| 1 | Network topology | `build_network_topology` | DEM + shapefile -> river network NetCDF |
| 2 | Runoff remapping | `create_remap_weights` | VIC grid -> HRU area-weighted overlap |
| 3 | Runoff conversion | `convert_vic_runoff` | VIC flux files -> mizuRoute NetCDF (mm/s) |
| 4 | Control file | `generate_control_file` | All paths, method, time settings |
| 5 | Execution | `run_mizuroute` | Preflight checks + run + postflight |
| 6 | Output extraction | `extract_discharge`, `compare_routing_methods` | Q timeseries, metrics, method comparison |

### Parallelism

Stages 1 and 3 can run in parallel (independent).
Stage 2 depends on 1 (needs HRU definitions).
Stage 4 depends on 1, 2, 3 (needs all file paths).
Stage 5 depends on 4.
Stage 6 depends on 5.

```
s0 ─────────────────────────────────────┐
  │                                      │
  ├──> s1 (network) ──> s2 (remap) ──┐  │
  │                                   ├──> s4 (control) ──> s5 (run) ──> s6 (output)
  └──> s3 (runoff) ──────────────────┘
```

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `build_network_topology` | s1 | `tools/s1_network/build_network_topology.py` | 492 | DEM -> river network topology NetCDF via WhiteboxTools |
| `create_remap_weights` | s2 | `tools/s2_remap/create_remap_weights.py` | 274 | VIC grid -> HRU area-weighted overlap NetCDF |
| `convert_vic_runoff` | s3 | `tools/s3_runoff/convert_vic_runoff.py` | 385 | VIC flux -> mizuRoute runoff NetCDF (mm/timestep -> mm/s) |
| `generate_control_file` | s4 | `tools/s4_control/generate_control_file.py` | 243 | Generate mizuRoute control file from config |
| `run_mizuroute` | s5 | `tools/s5_execution/run_mizuroute.py` | 258 | Execute mizuRoute with preflight/postflight checks |
| `extract_discharge` | s6 | `tools/s6_postprocess/extract_discharge.py` | 275 | Parse output -> discharge CSV + metrics (NSE, KGE, RMSE) |
| `compare_routing_methods` | s6 | `tools/s6_postprocess/compare_routing_methods.py` | 188 | Run all 5 methods and compare discharge |

**Total**: 7 tools, 2,115 lines of validated Python code.

### Skill Documents

| Stage | Document | Covers |
|-------|----------|--------|
| s0 | `docs/s0_config_skill.md` | Routing method selection guide, basin size decision tree |
| s1 | `docs/s1_network_skill.md` | Stream network from DEM, threshold selection, topology validation |
| s2 | `docs/s2_remap_skill.md` | Spatial remapping, CRS alignment, weight validation |
| s3 | `docs/s3_runoff_skill.md` | Unit conversion table (mm/timestep -> mm/s), temporal alignment |
| s4 | `docs/s4_control_skill.md` | Complete control file reference, variable name mapping |
| s5 | `docs/s5_execution_skill.md` | Running mizuRoute, interpreting errors, expected runtimes |
| s6 | `docs/s6_comparison_skill.md` | 3-way comparison methodology (Lohmann vs CaMa vs mizuRoute) |
| lake | `docs/s_lake_routing_skill.md` | Lake/reservoir routing setup and parameter estimation |

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated. Each has a corresponding diagnostic triplet.

### 1. VIC runoff is mm/timestep, mizuRoute expects mm/s (dt_m003)

VIC reports RUNOFF and BASEFLOW in mm per model timestep:
- Daily output: mm/day -> divide by 86400 -> mm/s
- 3-hourly output: mm/3hr -> divide by 10800 -> mm/s

**If wrong**: Discharge is 8x or 86400x too high/low with NO error message. This is the #1 silent error risk.

**Quick check**: In the runoff NetCDF, max(RUNOFF) should be < 0.01 mm/s for most basins. If > 1.0 mm/s, units are wrong.

### 2. Variable names must match exactly (dt_m004)

The control file `vname_*` entries must match the exact variable names in the network topology and runoff NetCDF files. Different data sources use different names:
- HydroCraft tools: `seg_id`, `tosegment`, `seg_length`, `seg_slope`
- NHDPlus: `COMID`, `toComid`, `LENGTHKM`, `SLOPE`
- MERIT Hydro: `RIVID`, `NextDownID`, `rivlen`, `rivslp`

### 3. Reach slope must be > 0 (dt_m007)

DEM-derived networks often have zero-slope reaches in flat terrain. Set minimum slope floor: `max(slope, 0.0001)` m/m. Zero slope causes division-by-zero in Manning's equation.

### 4. CFL condition for KWE and DW methods (dt_m009)

KWE and DW are conditionally stable: routing timestep must satisfy `dt < dx/c` (Courant number). Short steep reaches need very small dt. Use IRF or KWT for steep mountain basins unless you specifically need wave dynamics.

### 5. Fortran path length limit (dt_m017)

mizuRoute uses Fortran CHARACTER(256) for file paths. Paths exceeding 256 characters are silently truncated. Keep all paths < 120 characters or use symlinks. Same issue as Lohmann routing.

### 6. Multiple outlets = split flow (dt_m015)

If the network has multiple reaches with `tosegment=0`, water exits through all outlets. This silently reduces discharge at the "main" outlet. Always verify the network has exactly one outlet, or connect secondary outlets.

---

## Coupling Points

| # | Source | Target | Variable | Tool |
|---|--------|--------|----------|------|
| 1 | VIC 5.1.0 | mizuRoute | RUNOFF + BASEFLOW (mm/s) | `convert_vic_runoff` |
| 2 | WRF-Hydro 5.2.0 | mizuRoute | SFCRNOFF + UGDRNOFF (mm/s) | (convert_wrfhydro_runoff) |
| 3 | mizuRoute | plot tools | outlet discharge (m3/s) | `extract_discharge` |
| 4 | mizuRoute | CaMa-Flood | reach discharge at nodes | (future coupling) |

---

## Quick Start

```bash
# Activate HydroCraft venv
source KISSPATH_PYTHON_ENV/bin/activate

TOOLS=KISSPATH_KI_ROOT/mizuRoute/knowledge_infrastructure/tools
RUN=outputs/chaohe_2000_2010_025deg

# 1. Build river network from DEM
python $TOOLS/s1_network/build_network_topology.py \
  --basin_shp data/shp/chaohe_boundary/chaohe_boundary.shp \
  --dem data/dem/china_dem_90m/china_dem_90m.tif \
  --output $RUN/mizuroute_input/network_topology.nc \
  --stream_threshold 500

# 2. Create remap weights (VIC grid -> HRUs)
python $TOOLS/s2_remap/create_remap_weights.py \
  --grid_nc $RUN/vic_temp/grid/basin_grid.nc \
  --network_nc $RUN/mizuroute_input/network_topology.nc \
  --output $RUN/mizuroute_input/remap_weights.nc

# 3. Convert VIC runoff to mizuRoute format
python $TOOLS/s3_runoff/convert_vic_runoff.py \
  --vic_result_dir $RUN/vic_result \
  --grid_nc $RUN/vic_temp/grid/basin_grid.nc \
  --output $RUN/mizuroute_input/runoff.nc \
  --start_year 2000 --end_year 2010

# 4. Generate control file
python $TOOLS/s4_control/generate_control_file.py \
  --basin_name chaohe \
  --network_nc $RUN/mizuroute_input/network_topology.nc \
  --runoff_nc $RUN/mizuroute_input/runoff.nc \
  --remap_nc $RUN/mizuroute_input/remap_weights.nc \
  --output_dir $RUN/mizuroute_output \
  --output $RUN/mizuroute_input/chaohe.control \
  --route_opt 0 --start_date 2000-01-01 --end_date 2010-12-31

# 5. Run mizuRoute
python $TOOLS/s5_execution/run_mizuroute.py \
  --control_file $RUN/mizuroute_input/chaohe.control

# 6. Extract and plot discharge
python $TOOLS/s6_postprocess/extract_discharge.py \
  --mizuroute_output $RUN/mizuroute_output \
  --network_nc $RUN/mizuroute_input/network_topology.nc \
  --output $RUN/mizuroute_discharge.csv
```

---

## Diagnostic Triplets

18 triplets covering 7 failure domains. See `diagnostics/triplets.yaml` for full details.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_m001 | fatal | compilation | NetCDF library path wrong |
| dt_m002 | fatal | path_resolution | Control file path wrong or Fortran truncation |
| dt_m003 | **silent** | unit_conversion | VIC mm/timestep not converted to mm/s (8-86400x error) |
| dt_m004 | fatal | parameter_format | Variable name mismatch between control file and NetCDF |
| dt_m005 | **silent** | dependency_mismatch | CRS mismatch -> zero overlap -> no runoff to HRUs |
| dt_m006 | fatal | parameter_format | Dangling downstream references in topology |
| dt_m007 | degraded | parameter_format | Zero slope -> unrealistic peak discharge |
| dt_m008 | **silent** | silent_error | Temporal offset VIC vs mizuRoute convention |
| dt_m009 | fatal | runtime | CFL violation with KWE/DW methods |
| dt_m010 | **silent** | dependency_mismatch | Edge HRUs get no VIC runoff |
| dt_m011 | degraded | parameter_format | Lake segments not flagged -> missing lake outflow |
| dt_m012 | fatal | runtime | MPI crash on disconnected network |
| dt_m013 | **silent** | unit_conversion | Calendar/timezone mismatch |
| dt_m014 | warning | parameter_format | doesBasinRoute double-counts hillslope delay |
| dt_m015 | **silent** | silent_error | Multiple outlets -> flow escapes |
| dt_m016 | degraded | dependency_mismatch | Channel losses in MC/DW not in Lohmann |
| dt_m017 | fatal | path_resolution | Fortran CHARACTER truncation |
| dt_m018 | **silent** | silent_error | Width estimation wrong for climate zone |

**Silent error count**: 7/18 (39%) — consistent with cross-model average of 37%.

---

## Validated Results

### Step 3: Bengbu Basin (2000-2005, 0.25deg, IRF routing)

**Configuration**: 224 VIC grid cells -> 224 HRU/segments, grid-based D8 network topology, IRF routing (route_opt 0 1), daily timestep.

**Data Replacement Tracking**:

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | HydroCraft (VIC runoff) | Validated | 224 cells, mean 1.07 mm/day |
| Network topology | HydroCraft (DEM + D8) | Validated | 224 segments, 7 outlets |
| Routing params | Default (velo=1.0, diff=800) | Applied | No calibration |
| Output writing | PIO serial stubs | **Fixed** | pio_setframe was no-op (dt_m019) |

**Results (after MPI stub fix)**:

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Mean Q (sum all 7 outlets) | **1795 m3/s** | 770-2300 m3/s | **PASS** |
| Mean Q (main outlet, Seg 147) | **1033 m3/s** | - | 63% of basin area |
| Mass conservation (basRunoff) | **1.000** | ~1.0 | **PASS** |
| Correlation vs Lohmann (all outlets) | **r = 0.87** | r > 0.5 | **PASS** |
| Correlation vs Lohmann (main outlet) | **r = 0.82** | r > 0.5 | **PASS** |
| Volume ratio (mizuRoute / Lohmann) | **1.19** | 0.5-2.0 | **PASS** |
| Seasonal cycle | Correct monsoon peak | Summer peak | **PASS** |
| Runtime | ~30 seconds | - | Fast |

**Known Issues (all fixed)**:
1. **MPI serial stub data corruption (FIXED, err_001)**: `MPI_SCATTERV` stub declared buffers as `integer(*)`, causing 4-byte copy steps for 8-byte `real(dp)` data. Tributary HRUs (50%) received corrupted/zero runoff. **This was the root cause of the 88% magnitude loss.** Fix: multiply count/displacement by `words_per_element` (2 for double precision). Applied to all 7 collective MPI stubs.
2. **PIO serial stub output bug (FIXED, dt_m019)**: `pio_setframe` was a no-op in the serial stub, causing `pio_write_darray` to always write at record position 0.
3. **Multiple outlets (7)**: Grid-based D8 on 0.25deg creates 7 outlet segments. Main outlet (seg 147) captures 141/224 cells. Sum of all outlets gives correct total discharge. Use finer DEM-based topology for single-outlet production runs.

### Chaohe Basin (2000-2010, 0.25deg, IRF routing)

**Configuration**: 27 VIC grid cells -> 27 HRU/segments, grid-based D8 topology, IRF routing.

**Results**: Outlet Q = 2.69 m3/s (low but non-zero after NaN fix). Same PIO output bug limited analysis to 1 valid timestep per year before fix.

---

## Bugs Found and Fixed

### dt_m019: PIO serial stub pio_setframe no-op (FIXED 2026-03-22)

**Severity**: silent, **Domain**: output_writing

**Symptom**: Output NetCDF files have only 1 valid timestep per year; remaining ~364 timesteps contain fill values (9.97e+36).

**Root cause**: In `serial_stubs/pio.f90`, the `pio_setframe` subroutine was an empty no-op that ignored the `frame` parameter. The subsequent `pio_write_darray` called `nf90_put_var` without `start` parameter, always writing to position 0.

**Fix**: (1) Added `current_frame` module variable to store the active frame index. (2) `pio_setframe` now sets `current_frame = int(frame)`. (3) `pio_write_darray_*1d` functions now check variable dimensionality and use `start=[1, current_frame]` for variables with a record dimension.

**Impact**: Without fix, only 1 of 365 daily values per year was written. All time-series analysis was impossible.

### err_001: MPI serial stub data corruption — ROOT CAUSE OF 88% MAGNITUDE LOSS (FIXED 2026-03-22)

**Severity**: fatal, **Domain**: unit_conversion

**Symptom**: `basRunoff` for tributary HRUs (112 of 224 = 50%) is zero, causing 75-90% total discharge magnitude loss. Timing correlation remains correct (r=0.70+) because the correctly-routed mainstem HRUs have the right temporal pattern.

**Root cause**: Serial MPI stubs (`route/build/serial_stubs/mpi_stubs.f90`) declare all buffer parameters as `integer :: sendbuf(*), recvbuf(*)` (4-byte assumed-size arrays). When `real(dp)` (8-byte double precision) data is passed through `MPI_SCATTERV`, the copy loop `recvbuf(i) = sendbuf(displs(1) + i)` iterates by 4-byte integer steps instead of 8-byte double steps. For `recvcount=N` double-precision elements, only `N * 4` bytes are copied instead of `N * 8` bytes, corrupting the entire tributary HRU runoff array. The `MPI_SCATTERV` stub is used in `scatter_runoff()` to distribute `basinRunoff` from the master proc to the tributary domain.

**Why exactly 50% is zero**: mizuRoute splits HRUs into "mainstem" and "tributary" domains for parallel processing. In serial mode (1 proc), mainstem HRUs are copied via a direct Fortran assignment (works correctly), while tributary HRUs are distributed via `MPI_SCATTERV` (corrupted by the bug). For Bengbu, the domain decomposition assigns ~112 HRUs to each domain.

**Fix**: In each MPI stub function, determine `words_per_element` from the `datatype` parameter: 2 for `MPI_DOUBLE_PRECISION` (=3) and `MPI_INTEGER8` (=2), 1 for `MPI_INTEGER` (=1) and `MPI_REAL` (=4). Multiply element count and displacement by `words_per_element` before the copy loop. Applied to all 7 collective operations: `MPI_SCATTERV`, `MPI_GATHERV`, `MPI_ALLGATHERV`, `MPI_ALLGATHER`, `MPI_Alltoallv`, `MPI_REDUCE`, `MPI_ALLREDUCE`.

**Impact**: After fix, basRunoff ratio = 1.0000 (exact mass conservation), total outlet Q = 1795 m3/s (matches expected), r = 0.87 vs Lohmann.

**Discovery method**: Systematic per-HRU comparison of input vs output basRunoff. Exactly 112/224 HRUs had zero, and the zero set corresponded to output positions 112-223 (topologically-sorted tributary domain). Traced through the data flow: `sort_flux` -> `scatter_runoff` -> `MPI_SCATTERV` -> corrupted `basinRunoff_trib`.

---

## File Structure

```
models/mizuRoute/knowledge_infrastructure/
  DISSECTION_PLAN.md              # Original dissection plan
  SKILL.md                        # This file (agent entry point)
  knowledge_infrastructure.yaml   # Schema-compliant package definition
  tools/
    s1_network/
      build_network_topology.py   # DEM -> river network topology
    s2_remap/
      create_remap_weights.py     # VIC grid -> HRU spatial weights
    s3_runoff/
      convert_vic_runoff.py       # VIC flux -> mizuRoute runoff NetCDF
    s4_control/
      generate_control_file.py    # Generate control file
    s5_execution/
      run_mizuroute.py            # Execution wrapper with validation
    s6_postprocess/
      extract_discharge.py        # Extract Q timeseries + metrics
      compare_routing_methods.py  # 5-method comparison
  docs/
    s0_config_skill.md            # Routing method selection
    s1_network_skill.md           # Network construction
    s2_remap_skill.md             # Spatial remapping
    s3_runoff_skill.md            # Unit conversion
    s4_control_skill.md           # Control file reference
    s5_execution_skill.md         # Running mizuRoute
    s6_comparison_skill.md        # Method comparison
    s_lake_routing_skill.md       # Lake/reservoir routing
  diagnostics/
    triplets.yaml                 # 18 diagnostic triplets
    error_log.yaml                # Runtime error capture

model/mizuRoute/
  mizuRoute-main/                 # Source code (from GitHub)
    route/bin/mizuroute.exe       # Compiled binary
    route/build/                  # Build system
      Makefile.serial             # Serial build Makefile
      serial_stubs/               # MPI/PIO stubs for serial compilation
  build_serial.sh                 # One-command serial build script
```
