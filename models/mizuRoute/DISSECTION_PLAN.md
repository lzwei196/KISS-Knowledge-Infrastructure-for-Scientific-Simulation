# mizuRoute — Knowledge Dissection Plan

**Target model**: mizuRoute (NCAR/ESCOMP), reach-based river routing
**Repository**: https://github.com/ESCOMP/mizuRoute
**Documentation**: https://mizuroute.readthedocs.io/en/main/
**License**: Apache 2.0
**Language**: Fortran (93%) + Python (6%)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Date**: 2026-03-21
**Status**: Planning (Phase 0 — pre-dissection research)

---

## 1. Model Overview

### What mizuRoute Is

mizuRoute is a **reach-based (vector) river routing model** developed by NCAR that takes gridded runoff output from any hydrologic or land surface model and routes it through a user-defined catchment-based (vector) river network to compute streamflow at every reach. Unlike grid-based routing models (Lohmann, CaMa-Flood), mizuRoute operates on an explicit river network topology where each reach is a distinct segment with physical properties (length, slope, width).

### Key Capabilities

| Capability | Description |
|-----------|-------------|
| **5 routing methods** | IRF (impulse response function), KWT (Lagrangian kinematic wave tracking), KWE (Euler kinematic wave), MC (Muskingum-Cunge), DW (diffusive wave) |
| **Lake/reservoir routing** | Natural lakes (level-pool), managed reservoirs (rule curves), Hanasaki global reservoir scheme |
| **MPI parallelism** | Domain decomposition across river network tributaries for multi-decadal/century-scale runs |
| **Flexible network** | Any vector river network (NHDPlus, HydroSHEDS, MERIT Hydro, custom from DEM) |
| **Standalone + coupled** | Runs standalone with runoff NetCDF or coupled within CESM/CTSM |
| **Multi-scale** | From small catchments to continental/global domains (e.g., entire CONUS NHDPlus) |

### The 5 Routing Methods

| ID | Method | Physics | Best for | Computational cost |
|----|--------|---------|----------|-------------------|
| **IRF** | Impulse Response Function | Unit hydrograph convolution per reach (similar to Lohmann but per-reach, not per-grid) | Quick routing, large networks, no backwater | Lowest |
| **KWT** | Kinematic Wave Tracking (Lagrangian) | Tracks individual wave packets moving downstream | Moderate networks, flood wave propagation | Low |
| **KWE** | Kinematic Wave (Euler) | Fixed-grid finite difference Saint-Venant (kinematic form) | General purpose, good balance of physics/speed | Moderate |
| **MC** | Muskingum-Cunge | Storage-based routing with variable parameters derived from reach geometry | Operational forecasting, NWM-style routing | Moderate |
| **DW** | Diffusive Wave | Saint-Venant equations with diffusion term, captures backwater/attenuation | Flat terrain, tidal influence, reservoir backwater | Highest |

### Why mizuRoute for HydroCraft

HydroCraft currently has two routing approaches:

| Feature | Lohmann (current) | CaMa-Flood (current) | mizuRoute (proposed) |
|---------|-------------------|----------------------|---------------------|
| Grid type | Regular lat/lon grid | Regular lat/lon grid (15min) | Vector river network (reaches) |
| Physics | Unit hydrograph (single method) | Local inertia + floodplain | 5 selectable methods |
| Floodplain | No | Yes (key strength) | No (complement with CaMa) |
| Lake/reservoir | No | Limited | Yes (3 schemes) |
| MPI | No | OpenMP | MPI (domain decomposition) |
| Network source | DEM-derived grid | Global 15min map | Any vector network |
| Setup complexity | Low (DEM + soil) | Medium (regionalize global map) | Medium (network topology NetCDF) |
| Computational efficiency | Fast | Heavy (solves floodplain) | Fast-to-moderate (reach-only) |
| Key value | Simple, reliable default | Flood inundation mapping | Physically realistic reach routing, lake/reservoir support, method flexibility |

**Strategic value**: mizuRoute fills the gap between Lohmann (too simple for complex networks with lakes) and CaMa-Flood (too heavy when floodplain dynamics are not needed). It is the routing model used in the National Water Model (NWM) with Muskingum-Cunge, and in CESM/CTSM with IRF/KWT.

---

## 2. Installation Plan

### 2.1 Prerequisites

| Dependency | Required version | Notes |
|-----------|-----------------|-------|
| gfortran | >= 7.0 | Any modern gfortran works |
| NetCDF-Fortran | >= 4.5 | `libnetcdff.so` + `nf-config` |
| NetCDF-C | >= 4.6 | Underlying C library |
| MPI (optional) | MPICH or OpenMPI | Only needed for parallel runs |

All dependencies are already available on the HydroCraft server (used by WRF-Hydro and CaMa-Flood compilations).

### 2.2 Build Steps

```bash
# 1. Clone repository
cd KISSPATH_BINARIES
git clone https://github.com/ESCOMP/mizuRoute.git mizuRoute
cd mizuRoute

# 2. Initialize submodules (git-fleximod for external dependencies)
git submodule update --init --recursive
# OR: .lib/git-fleximod/git-fleximod update

# 3. Build
cd route/build/
# Edit Makefile: set FC=gfortran, NCDF_PATH, and optionally MPI flags
# For serial build:
make FC=gfortran

# 4. Verify
ls ../bin/mizuroute.exe
./mizuroute.exe --help  # or run test case
```

### 2.3 Expected Issues (from Fortran Traps pre-flight)

| Issue | Likelihood | Mitigation |
|-------|-----------|------------|
| NetCDF library path wrong (`libnetcdff.so`) | High | Use `nf-config --flibs` to get correct flags; same issue as WRF-Hydro dt_006 |
| Makefile variables need editing | Certain | Provide a pre-configured Makefile for the server |
| MPI not linked (serial-only build) | Low | Start with serial build, add MPI later |
| Path > 120 chars in Fortran CHARACTER variables | Medium | Check CHARACTER widths in source; use short paths or symlinks |

### 2.4 Proposed Installation Path

```
model/mizuRoute/
  route/bin/mizuroute.exe     # compiled binary
  route/build/Makefile         # build configuration
  docs/                        # upstream documentation
```

---

## 3. Input Data Formats

### 3.1 River Network Topology (NetCDF)

This is the core input that defines the vector river network. Each reach (segment) and its contributing catchment (HRU) are described.

**Required variables for river segments:**

| Variable | Type | Dimensions | Units | Description |
|----------|------|-----------|-------|-------------|
| `seg_id` | int | (seg) | - | Unique reach segment ID |
| `tosegment` | int | (seg) | - | Downstream segment ID (0 = outlet) |
| `seg_length` | float | (seg) | m | Reach length |
| `seg_slope` | float | (seg) | m/m | Reach bed slope |
| `seg_width` | float | (seg) | m | Channel width (optional, estimated if missing) |
| `seg_manning_n` | float | (seg) | - | Manning's roughness (optional, default 0.03) |
| `seg_hruId` | int | (seg, hru_per_seg) | - | HRU IDs draining to this segment |

**Required variables for HRUs (hydrologic response units):**

| Variable | Type | Dimensions | Units | Description |
|----------|------|-----------|-------|-------------|
| `hru_id` | int | (hru) | - | Unique HRU ID |
| `hru_seg_id` | int | (hru) | - | Which segment this HRU drains to |
| `hru_area` | float | (hru) | m^2 | HRU contributing area |
| `hru_lat` | float | (hru) | degrees | HRU centroid latitude |
| `hru_lon` | float | (hru) | degrees | HRU centroid longitude |

**Optional variables for lakes/reservoirs:**

| Variable | Type | Description |
|----------|------|-------------|
| `is_lake` | int | Flag for lake segments |
| `lake_id` | int | Lake identifier |
| `lake_area` | float | Lake surface area (m^2) |
| `lake_max_storage` | float | Maximum storage (m^3) |
| `lake_min_storage` | float | Minimum storage (m^3) |
| `d_h_d_a` | float | dH/dA (height-area relationship) |

**Key sources for network topology:**
- **NHDPlus** (US): National Hydrography Dataset Plus — pre-built, widely used by NWM
- **MERIT Hydro** (Global): 90m global hydrography dataset by Yamazaki et al.
- **HydroSHEDS** (Global): WWF global river network dataset
- **Custom from DEM**: Build from basin DEM using WhiteboxTools or TauDEM (HydroCraft already has WhiteboxTools)

### 3.2 Runoff Input (NetCDF)

Gridded or HRU-based runoff from the land surface model.

| Variable | Type | Dimensions | Units | Description |
|----------|------|-----------|-------|-------------|
| `time` | float | (time) | days since reference | Time coordinate |
| `RUNOFF` (or user-specified) | float | (time, hru) or (time, y, x) | mm/s or mm/day | Surface + subsurface runoff |

mizuRoute supports two spatial mapping modes:
1. **HRU-based**: Runoff provided per HRU (1:1 mapping, no spatial remapping needed)
2. **Grid-based**: Runoff on a regular grid (mizuRoute remaps to HRUs using area-weighted overlap)

For HydroCraft, VIC and WRF-Hydro produce gridded runoff, so grid-based mode with spatial remapping will be used.

### 3.3 Control File

The control file is a Fortran namelist-style file with `<variable_name>  <value>` pairs. Key sections:

**Directory/file paths:**
| Variable | Description |
|----------|-------------|
| `ancil_dir` | Directory containing ancillary/network data |
| `input_dir` | Directory containing runoff input |
| `output_dir` | Directory for output files |
| `fname_ntopOld` | River network topology NetCDF filename |
| `fname_qsim` | Runoff input NetCDF filename |
| `fname_output` | Output filename prefix |

**Variable name mapping:**
| Variable | Description |
|----------|-------------|
| `vname_hruid` | Variable name for HRU ID in network file |
| `vname_segid` | Variable name for segment ID |
| `vname_tosegment` | Variable name for downstream segment |
| `vname_length` | Variable name for segment length |
| `vname_slope` | Variable name for segment slope |
| `vname_area` | Variable name for HRU area |
| `vname_qsim` | Variable name for runoff in input file |
| `vname_time` | Variable name for time in input file |

**Time control:**
| Variable | Description |
|----------|-------------|
| `sim_start` | Simulation start (YYYY-MM-DD HH:MM:SS) |
| `sim_end` | Simulation end (YYYY-MM-DD HH:MM:SS) |
| `dt` | Routing time step (seconds) |
| `newFileFrequency` | How often a new input file is expected |

**Routing method selection:**
| Variable | Description |
|----------|-------------|
| `route_opt` | Routing method: 0=IRF, 1=KWT, 2=KWE, 3=MC, 4=DW |
| `doesBasinRoute` | Whether to apply basin (hillslope) IRF before reach routing (0 or 1) |
| `doesAccumRunoff` | Whether to accumulate runoff along the network (0 or 1) |

**Lake/reservoir control:**
| Variable | Description |
|----------|-------------|
| `is_lake_sim` | Enable lake simulation (True/False) |
| `lake_model_type` | Lake model: 1=level-pool, 2=Hanasaki, 3=HYPE |

**Spatial remapping:**
| Variable | Description |
|----------|-------------|
| `is_remap` | Enable spatial remapping from grid to HRUs (True/False) |
| `fname_remap` | Remapping weight file (NetCDF with overlap weights) |

---

## 4. Pipeline Stages

The mizuRoute pipeline for HydroCraft has 7 stages:

### Stage 0: Configuration (`s0_config`)
- **Purpose**: Define basin, time period, routing method, upstream model (VIC/WRF-Hydro)
- **Knowledge type**: Evaluative (method selection)
- **Inputs**: Basin name, time period, desired routing method, upstream runoff source
- **Outputs**: Configuration dictionary/YAML consumed by all downstream stages
- **Key decisions**:
  - Which routing method? IRF for quick runs, KWE for general purpose, MC for NWM-compatible, DW for flat terrain
  - Include lakes? If basin has significant lakes/reservoirs, enable lake routing
  - MPI or serial? Serial for small basins (<1000 reaches), MPI for large networks

### Stage 1: River Network Topology Construction (`s1_network`)
- **Purpose**: Build the river network topology NetCDF from DEM and basin shapefile
- **Knowledge type**: Procedural (automated DEM processing)
- **Inputs**: Basin shapefile, DEM (China 90m or Copernicus GLO-30)
- **Outputs**: River network topology NetCDF (`<basin>_network.nc`)
- **Tools needed**:
  - `build_network_topology.py` — Uses WhiteboxTools to extract stream network from DEM, compute Strahler order, extract reach properties (length, slope, width), identify catchments (HRUs), export as mizuRoute-format NetCDF
  - Alternative: `extract_merit_network.py` — Extract network from MERIT Hydro global dataset (pre-built, higher quality for large basins)
- **Key challenge**: Mapping between VIC/WRF-Hydro grid cells and mizuRoute HRUs. Each VIC grid cell may overlap multiple HRUs, requiring area-weighted remapping.

### Stage 2: Runoff Mapping / Remapping Weights (`s2_remap`)
- **Purpose**: Create spatial remapping weights from upstream model grid to mizuRoute HRUs
- **Knowledge type**: Procedural (spatial intersection)
- **Inputs**: VIC/WRF-Hydro grid definition (basin_grid.nc), river network topology (HRU polygons)
- **Outputs**: Remapping weight file (`<basin>_remap.nc`)
- **Tools needed**:
  - `generate_remap_weights.py` — Compute area-weighted overlap between source grid cells and target HRUs using geopandas spatial intersection
- **Critical pitfall**: CRS mismatch between VIC (WGS84 lat/lon) and HRU polygons (potentially UTM or other projection). Must verify CRS alignment before intersection.

### Stage 3: Runoff Format Conversion (`s3_runoff`)
- **Purpose**: Convert VIC or WRF-Hydro runoff output to mizuRoute input NetCDF format
- **Knowledge type**: Procedural (format + unit conversion)
- **Inputs**: VIC flux files (`OUT_RUNOFF` + `OUT_BASEFLOW`, mm/timestep) or WRF-Hydro CHRTOUT/LDASOUT
- **Outputs**: Runoff NetCDF (`<basin>_runoff_YYYY.nc`) with dimensions (time, y, x) or (time, hru)
- **Tools needed**:
  - `convert_vic_runoff.py` — Read VIC ASCII flux files, extract RUNOFF + BASEFLOW columns, convert to mm/s, write NetCDF with proper time coordinate
  - `convert_wrfhydro_runoff.py` — Read WRF-Hydro LDASOUT SFCRNOFF + UGDRNOFF, convert to mm/s on regular grid
- **Critical unit trap**: VIC reports runoff in mm/timestep (e.g., mm/3hr). mizuRoute expects mm/s (rate). Dividing by timestep in seconds is required. This is the #1 silent error risk.

### Stage 4: Control File Generation (`s4_control`)
- **Purpose**: Generate the mizuRoute control file with all paths, variable names, method selection, and time settings
- **Knowledge type**: Procedural + Evaluative (method selection, parameter defaults)
- **Inputs**: Configuration from s0, network file path from s1, remap file from s2, runoff file from s3
- **Outputs**: Control file (`<basin>.control`)
- **Tools needed**:
  - `generate_control_file.py` — Template-based generation with all variable names auto-populated from network and runoff NetCDF metadata

### Stage 5: Execution (`s5_execute`)
- **Purpose**: Run mizuRoute
- **Knowledge type**: Procedural (execution wrapper)
- **Inputs**: Control file, network NetCDF, runoff NetCDF, remap weights
- **Outputs**: Output NetCDF with simulated discharge at every reach
- **Tools needed**:
  - `run_mizuroute.py` — Execution wrapper with preflight validation (check all input files exist, NetCDF variables match control file), run mizuRoute, capture stdout/stderr, verify output
- **Expected runtime**: Seconds to minutes for small basins (serial), minutes to hours for continental (MPI)

### Stage 6: Output Extraction & Comparison (`s6_postprocess`)
- **Purpose**: Extract discharge at outlet reach, compare with Lohmann/CaMa-Flood results and observations
- **Knowledge type**: Procedural + Evaluative (model comparison)
- **Inputs**: mizuRoute output NetCDF, observed discharge (if available), Lohmann/CaMa results
- **Outputs**: Discharge timeseries CSV, comparison plots
- **Tools needed**:
  - `extract_discharge.py` — Read mizuRoute output, identify outlet reach, extract Q timeseries, compute NSE/RMSE/PBIAS
  - Integration with existing `skills/plot/plot_discharge_comparison.py` for visualization

### Pipeline Dependency Graph

```
s0_config ──────────────────────────────────────────┐
    │                                                │
    ├──> s1_network ──> s2_remap ──┐                │
    │                               ├──> s4_control ──> s5_execute ──> s6_postprocess
    └──> s3_runoff ────────────────┘
```

Stages s1 and s3 can run in parallel (independent). Stage s2 depends on s1 (needs HRU polygons). Stage s4 depends on s1, s2, s3 (needs all file paths). Stage s5 depends on s4. Stage s6 depends on s5.

---

## 5. Tools to Build

### 5.1 Tool Inventory

| ID | Tool name | Stage | Est. lines | Description |
|----|----------|-------|-----------|-------------|
| `t01` | `build_network_topology.py` | s1 | ~600 | Build river network topology NetCDF from DEM + basin shapefile using WhiteboxTools |
| `t02` | `extract_merit_network.py` | s1 | ~400 | Extract river network from MERIT Hydro global dataset (alternative to DEM-based) |
| `t03` | `generate_remap_weights.py` | s2 | ~300 | Compute area-weighted spatial remapping from VIC/WRF-Hydro grid to mizuRoute HRUs |
| `t04` | `convert_vic_runoff.py` | s3 | ~250 | Convert VIC flux files to mizuRoute runoff NetCDF (mm/timestep -> mm/s) |
| `t05` | `convert_wrfhydro_runoff.py` | s3 | ~300 | Convert WRF-Hydro LDASOUT/CHRTOUT to mizuRoute runoff NetCDF |
| `t06` | `generate_control_file.py` | s4 | ~350 | Generate mizuRoute control file from configuration + file metadata |
| `t07` | `run_mizuroute.py` | s5 | ~250 | Execution wrapper with preflight checks, monitoring, and output validation |
| `t08` | `extract_discharge.py` | s6 | ~300 | Extract discharge timeseries from mizuRoute output, compute metrics |
| `t09` | `run_mizuroute_full_pipeline.py` | all | ~400 | End-to-end pipeline wrapper (stages 1-6) |
| `t10` | `add_lakes_to_network.py` | s1 | ~350 | Add lake/reservoir attributes to network topology from global dam/lake databases |

**Estimated total**: 10 tools, ~3,500 lines

### 5.2 Tool Design Notes

**`build_network_topology.py` (t01)** — Most complex tool. Pipeline:
1. Clip DEM to basin extent (reuse existing `delineate_basin.py` infrastructure)
2. WhiteboxTools: breach depressions -> D8 flow direction -> flow accumulation -> stream extraction
3. WhiteboxTools: `stream_link_identifier` to assign unique reach IDs
4. WhiteboxTools: `subbasins` to delineate catchments (HRUs) for each stream link
5. Compute reach properties: length (from raster geometry), slope (from DEM endpoints), width (from drainage area regression: W = a * A^b)
6. Build topology: identify downstream reach for each reach (from flow direction at reach outlet)
7. Export as NetCDF with all required mizuRoute variables

**`generate_remap_weights.py` (t03)** — Spatial intersection:
1. Read VIC grid cells as polygons (from `basin_grid.nc`)
2. Read HRU catchment polygons (from network topology or separate shapefile)
3. Compute intersection areas using geopandas overlay
4. Calculate weight = intersection_area / HRU_total_area
5. Export as NetCDF weight file in mizuRoute expected format

**`convert_vic_runoff.py` (t04)** — Unit conversion critical:
- VIC OUT_RUNOFF and OUT_BASEFLOW are in mm/timestep (e.g., mm/3hr for 3-hourly output, mm/day for daily)
- mizuRoute expects mm/s (rate, not depth per timestep)
- Conversion: `runoff_mm_s = (OUT_RUNOFF + OUT_BASEFLOW) / (timestep_seconds)`
- For VIC daily output (FORCE_STEPS_PER_DAY=8, output daily): divide by 86400
- For VIC 3-hourly output: divide by 10800
- **Silent error if wrong**: mizuRoute runs fine but discharge is 8x or 24x too high/low

---

## 6. Skill Documents to Write

| ID | Document | Stage | Key content |
|----|----------|-------|-------------|
| `sd01` | `s0_config_skill.md` | s0 | Routing method selection guide (IRF vs KWT vs KWE vs MC vs DW), basin size/terrain decision tree, lake routing options |
| `sd02` | `s1_network_skill.md` | s1 | River network construction from DEM vs MERIT Hydro, stream threshold selection, reach property estimation, topology validation |
| `sd03` | `s2_remap_skill.md` | s2 | Spatial remapping concepts, CRS alignment, weight validation (sum-to-one check), grid-to-vector mapping |
| `sd04` | `s3_runoff_skill.md` | s3 | Unit conversion tables (VIC mm/timestep -> mm/s, WRF-Hydro kg/m^2 -> mm/s), temporal aggregation, missing data handling |
| `sd05` | `s4_control_skill.md` | s4 | Complete control file reference, variable name mapping between different network sources, method-specific parameters |
| `sd06` | `s5_execution_skill.md` | s5 | Running mizuRoute (serial vs MPI), interpreting stdout/log, common runtime errors, expected runtimes by basin size |
| `sd07` | `s6_comparison_skill.md` | s6 | 3-way routing comparison methodology (Lohmann vs CaMa vs mizuRoute), when to use which method, performance metrics interpretation |
| `sd08` | `s_lake_routing_skill.md` | s1/s5 | Lake/reservoir routing setup: level-pool, Hanasaki, rule curves, global dam databases (GRanD, GOOD2), parameter estimation |

**Estimated total**: 8 skill documents, ~10,000-14,000 words

---

## 7. Diagnostic Triplets (Planned)

### 7.1 Anticipated Failure Modes

| ID | Severity | Domain | Stage | Symptom | Root cause |
|----|----------|--------|-------|---------|-----------|
| `dt_m001` | fatal | compilation | build | `undefined reference to nf90_*` | Wrong NETCDF_LIB path (same as WRF-Hydro dt_006) |
| `dt_m002` | fatal | path_resolution | s5 | `Cannot open file: <network>.nc` | Control file path wrong or Fortran path truncation |
| `dt_m003` | silent | unit_conversion | s3 | Discharge 8-24x too high or low | VIC runoff not converted from mm/timestep to mm/s |
| `dt_m004` | fatal | parameter_format | s4 | `Variable <name> not found in file` | Variable name in control file doesn't match NetCDF (e.g., `seg_id` vs `COMID`) |
| `dt_m005` | silent | dependency_mismatch | s2 | Discharge near zero | CRS mismatch in remap weights -> zero overlap areas -> no runoff reaches HRUs |
| `dt_m006` | fatal | parameter_format | s1 | `tosegment references non-existent segment` | Network topology has dangling references (broken downstream connectivity) |
| `dt_m007` | degraded | parameter_format | s1 | Unrealistic peak discharge | Reach slope = 0 or negative (flat DEM artifact) -> set minimum slope 0.0001 m/m |
| `dt_m008` | silent | silent_error | s3 | Delayed or dampened hydrograph | Runoff temporal offset (VIC end-of-timestep vs mizuRoute start-of-timestep convention) |
| `dt_m009` | fatal | runtime | s5 | `CFL violation` or `dt too large` | DW/KWE routing with large timestep on short/steep reaches -> reduce dt |
| `dt_m010` | silent | dependency_mismatch | s2 | HRUs with zero runoff | VIC grid doesn't fully cover all HRUs -> edge HRUs get no runoff |
| `dt_m011` | degraded | parameter_format | s1 | Missing lake outflow | Lake segments not properly flagged in network topology |
| `dt_m012` | fatal | runtime | s5 | `MPI_ABORT` | MPI domain decomposition fails on disconnected network components |
| `dt_m013` | silent | unit_conversion | s3 | Runoff seasonality inverted (Southern Hemisphere) | Time zone or date convention mismatch in runoff NetCDF |
| `dt_m014` | warning | parameter_format | s4 | `doesBasinRoute` ignored | Basin IRF applied when not intended, or vice versa -> slight timing shift |
| `dt_m015` | silent | silent_error | s1 | Multiple outlets in network | Network not a single tree -> mizuRoute routes to wrong outlet |
| `dt_m016` | degraded | dependency_mismatch | s6 | Discharge systematically lower than Lohmann/CaMa | Channel losses (evaporation, infiltration) modeled in mizuRoute but not in Lohmann |
| `dt_m017` | fatal | path_resolution | s5 | Fortran CHARACTER truncation | File paths > 120 chars silently truncated; use symlinks (same as Lohmann routing) |
| `dt_m018` | silent | silent_error | s1 | Width estimation wrong | Power-law W = a*A^b uses coefficients for wrong climate zone |

**Estimated total**: 18 diagnostic triplets covering 7 failure domains

### 7.2 Cross-Model Pattern Applicability

From `PREFLIGHT.md`, the following trap categories apply to mizuRoute:

| Trap category | Applicable? | Specific concern |
|--------------|------------|------------------|
| **Has Fortran code** | YES | Path truncation (CHARACTER widths), column alignment in any config files |
| **Physical units** | YES | mm/s vs mm/timestep is the #1 risk (cross-model pattern cm_004) |
| **Spatial data** | YES | CRS mismatch between VIC grid and HRU polygons |
| **Will be coupled** | YES | VIC->mizuRoute, WRF-Hydro->mizuRoute, mizuRoute->CaMa-Flood |
| **Fixed-width text files** | MAYBE | Control file is key-value, not fixed-width (lower risk) |

---

## 8. Coupling Points

### 8.1 Upstream Couplings (Runoff Sources)

#### c_mzr_01: VIC runoff -> mizuRoute
- **Source**: VIC 5.1.0 flux output (OUT_RUNOFF + OUT_BASEFLOW)
- **Format transformation**: ASCII per-cell -> NetCDF (time, y, x)
- **Unit conversion**: mm/timestep -> mm/s (divide by timestep_seconds)
- **Spatial mapping**: VIC regular lat/lon grid -> mizuRoute HRUs via area-weighted remap
- **Temporal alignment**: VIC output at end-of-day/3hr -> mizuRoute at start of timestep
- **Tool**: `convert_vic_runoff.py`
- **Silent failure modes**: Wrong timestep divisor, missing cells at basin boundary

#### c_mzr_02: WRF-Hydro runoff -> mizuRoute
- **Source**: WRF-Hydro LDASOUT (SFCRNOFF + UGDRNOFF) — NOT CHRTOUT (which is already routed)
- **Format transformation**: NetCDF on Lambert grid -> NetCDF on regular grid or HRU
- **Unit conversion**: mm (accumulation over output interval) -> mm/s
- **Spatial mapping**: Lambert Conformal Conic -> WGS84 lat/lon -> HRU area weights
- **Critical pitfall**: WRF-Hydro SFCRNOFF includes routed upstream flow when routing is enabled (dt_v009). Must use raw runoff, not routed.
- **Tool**: `convert_wrfhydro_runoff.py`

### 8.2 Downstream Couplings (Using mizuRoute Output)

#### c_mzr_03: mizuRoute discharge -> CaMa-Flood lateral inflow
- **Use case**: mizuRoute handles reach routing efficiently, CaMa-Flood adds floodplain inundation dynamics at selected locations
- **Source**: mizuRoute reach discharge at selected nodes
- **Target**: CaMa-Flood lateral inflow boundary condition
- **Benefit**: Best of both worlds — efficient vector routing for the network + floodplain dynamics where needed
- **Complexity**: High — requires spatial matching between mizuRoute reaches and CaMa-Flood grid cells

#### c_mzr_04: mizuRoute discharge -> validation comparison
- **Use case**: 3-way model comparison (Lohmann vs CaMa-Flood vs mizuRoute) at the same outlet
- **Source**: mizuRoute outlet discharge timeseries
- **Target**: `skills/plot/plot_discharge_comparison.py`
- **Tool**: `extract_discharge.py` outputs in same format as Lohmann `.day` files

### 8.3 Coupling Summary Table

| Coupling ID | Source model | Target model | Variable | Units | Tool |
|------------|-------------|--------------|----------|-------|------|
| c_mzr_01 | VIC 5.1.0 | mizuRoute | RUNOFF + BASEFLOW | mm/s | `convert_vic_runoff.py` |
| c_mzr_02 | WRF-Hydro 5.2.0 | mizuRoute | SFCRNOFF + UGDRNOFF | mm/s | `convert_wrfhydro_runoff.py` |
| c_mzr_03 | mizuRoute | CaMa-Flood | reach discharge | m^3/s | (future tool) |
| c_mzr_04 | mizuRoute | plot tools | outlet discharge | m^3/s | `extract_discharge.py` |

---

## 9. Validation Plan

### 9.1 Phase 1: Single-Basin Smoke Test

**Basin**: Chaohe (潮河), ~8,783 km^2, semi-humid North China
**Why**: Existing VIC + Lohmann + CaMa-Flood results available for direct comparison
**Period**: 2000-2010
**Method**: IRF (simplest, closest to Lohmann for comparison)
**Success criteria**:
- mizuRoute runs without error
- Outlet discharge is within 20% of Lohmann result
- Hydrograph timing matches (r > 0.8 vs Lohmann)

### 9.2 Phase 2: 3-Way Comparison

**Basins**: Chaohe + Bengbu (Huai River, large basin) + Yajiang (Tibetan Plateau, challenging)
**Methods**: IRF, KWE, MC (3 methods x 3 basins = 9 runs)
**Comparison targets**:
- Lohmann routing discharge (existing)
- CaMa-Flood discharge (existing)
- Observed discharge (where available: Bengbu, Yajiang/Nuxia)

**Success criteria per method:**

| Method | Expected behavior vs Lohmann | Expected behavior vs CaMa |
|--------|------------------------------|---------------------------|
| IRF | Very similar (both unit hydrograph) | Similar magnitude, faster execution |
| KWE | Slightly different timing (wave propagation) | Similar physics, no floodplain |
| MC | Similar to NWM-style routing | More efficient, no flood inundation |

### 9.3 Phase 3: Lake/Reservoir Test

**Basin**: A basin with significant lake/reservoir (TBD — candidates: Three Gorges on Yangtze, Miyun Reservoir on Chaohe upstream)
**Method**: KWE + lake routing (level-pool or Hanasaki)
**Success criteria**: Lake outflow regulation pattern matches observed release schedule

### 9.4 Phase 4: Large-Scale / MPI Test

**Basin**: Pearl River or Yangtze sub-basin (>100,000 km^2, >10,000 reaches)
**Method**: MC with MPI (4-8 cores)
**Success criteria**: MPI speedup > 2x vs serial, results identical to serial run

---

## 10. Estimated Effort

| Phase | Description | Estimated time | Dependencies |
|-------|-------------|---------------|-------------|
| **Installation** | Clone, build, verify on test case | 2-4 hours | gfortran + NetCDF (already available) |
| **Phase 1: Pipeline Mapping** | Define stages, dependencies, milestones | 2-3 hours | Installation complete |
| **Phase 2: Knowledge Classification** | Classify procedural/evaluative/debugging per stage | 2-3 hours | Phase 1 complete |
| **Phase 3: Tool Extraction** | Build 10 tools (~3,500 lines) | 3-5 days | Phase 2 complete |
| **Phase 4: Skill Documents** | Write 8 skill docs (~12,000 words) | 2-3 days | Phase 3 mostly complete |
| **Phase 5: Diagnostic Triplets** | Build 18 triplets from real runs | 1-2 days | Concurrent with validation |
| **Phase 6: Assembly & Validation** | Cross-ref audit, end-to-end test, SKILL.md | 2-3 days | All phases complete |
| **Total** | | **~2 weeks** | |

### Critical Path

The critical path is:
1. Installation (2-4 hrs)
2. `build_network_topology.py` — most complex tool, requires understanding WhiteboxTools stream extraction and mizuRoute NetCDF format
3. `convert_vic_runoff.py` — unit conversion is the #1 silent error risk
4. Chaohe smoke test — validates the entire pipeline
5. SKILL.md assembly

---

## 11. Priority & Dependencies

### Within HydroCraft Platform

| Priority | Rationale |
|----------|-----------|
| **Medium-High** | Fills a real gap (reach-based routing with lakes), but Lohmann + CaMa-Flood cover most current use cases |
| **Higher if**: User needs lake/reservoir routing, or method comparison is scientifically valuable |
| **Lower if**: All basins are ungauged with no lakes (Lohmann sufficient) |

### Dependencies on Existing Infrastructure

| Dependency | Status | Notes |
|-----------|--------|-------|
| WhiteboxTools | Available | Used by basin delineation, reuse for stream network extraction |
| VIC flux output | Available | Existing VIC pipeline produces flux files in known format |
| WRF-Hydro output | Available | Existing WRF-Hydro pipeline produces LDASOUT in known format |
| geopandas | Available | In python_env, used for spatial intersection |
| NetCDF4 | Available | In python_env, used for reading/writing NetCDF |
| gfortran | Available | Used for WRF-Hydro compilation |
| NetCDF-Fortran | Available | libnetcdff.so already installed |
| MERIT Hydro dataset | NOT available | Optional; need to download (~50 GB) for global network extraction |
| GRanD dam database | NOT available | Optional; needed for lake/reservoir routing setup |

### Integration with CLAUDE.md

After dissection is complete, add mizuRoute to the routing options in CLAUDE.md:

```markdown
### Routing method selection:
- **Lohmann** (default): Unit hydrograph, fast, discharge only
- **CaMa-Flood**: Hydrodynamics, flood inundation, slower
- **mizuRoute**: Reach-based routing, 5 methods, lake/reservoir support
```

And update the platform table:
```
| **River Routing** | Lohmann, CaMa-Flood 4.20, mizuRoute | Channel discharge, flood inundation, reach-based routing |
```

---

## 12. File Structure (Target)

```
models/mizuRoute/
  knowledge_infrastructure/
    DISSECTION_PLAN.md                    # This file
    SKILL.md                              # Agent entry point (Phase 6)
    knowledge_infrastructure.yaml         # Schema-compliant package definition
    workflow/
      pipeline.drawio                     # Visual pipeline diagram
      workflow.md                         # Agent-readable workflow
    tools/
      s1_network/
        build_network_topology.py         # t01: DEM -> river network NetCDF
        extract_merit_network.py          # t02: MERIT Hydro -> river network
        add_lakes_to_network.py           # t10: Add lake attributes
      s2_remap/
        generate_remap_weights.py         # t03: Grid -> HRU spatial weights
      s3_runoff/
        convert_vic_runoff.py             # t04: VIC flux -> mizuRoute NetCDF
        convert_wrfhydro_runoff.py        # t05: WRF-Hydro -> mizuRoute NetCDF
      s4_control/
        generate_control_file.py          # t06: Generate control file
      s5_execution/
        run_mizuroute.py                  # t07: Execution wrapper
      s6_postprocess/
        extract_discharge.py              # t08: Extract Q timeseries
      run_mizuroute_full_pipeline.py      # t09: End-to-end wrapper
    docs/
      s0_config_skill.md
      s1_network_skill.md
      s2_remap_skill.md
      s3_runoff_skill.md
      s4_control_skill.md
      s5_execution_skill.md
      s6_comparison_skill.md
      s_lake_routing_skill.md
    diagnostics/
      triplets.yaml                       # 18 diagnostic triplets
      error_log.yaml                      # Runtime error capture
      episodes.yaml                       # Full debugging stories
```

---

## 13. Open Questions (To Resolve During Dissection)

1. **MERIT Hydro vs DEM-derived network**: For large basins (>50,000 km^2), is MERIT Hydro worth downloading (~50 GB)? It provides pre-built river network attributes that are more accurate than DEM-derived ones.

2. **NHDPlus for North American basins**: Should we support NHDPlus as a network source? It is the standard for the US National Water Model and has detailed reach attributes, but is US-only.

3. **Lake database**: Which global dam/lake database to use? GRanD (7,320 dams globally), GOOD2 (~38,000 dams), or HydroLAKES (1.4 million lakes)?

4. **Remap weight format**: Does mizuRoute expect SCRIP-format or ESMF-format remap weight files? This determines how `generate_remap_weights.py` outputs the weights.

5. **mizuRoute version pinning**: ESCOMP/mizuRoute uses `git-fleximod` for external dependencies (similar to git submodules). Which release tag to pin? Latest stable vs the one used in NWM?

6. **Diffusive wave (DW) method**: Does DW require additional channel cross-section data beyond what IRF/KWT/KWE need? If so, this adds complexity to the network topology tool.

7. **Restart capability**: mizuRoute supports restart files for long simulations. Should the pipeline handle restarts automatically (like CaMa-Flood's annual restart loop)?

---

## 14. References

- Mizukami, N., et al. (2016). mizuRoute version 1: a river network routing tool for a continental domain water resources applications. *Geosci. Model Dev.*, 9, 2223-2238. doi:10.5194/gmd-9-2223-2016
- Clark, M.P., et al. (2021). The evolution of process-based hydrologic models: Historical challenges and the collective quest for physical realism. *Hydrology and Earth System Sciences*, 25(7), 3713-3734.
- Lohmann, D., et al. (1996). A large-scale horizontal routing model to be coupled to land surface parameterization schemes. *Tellus A*, 48(5), 708-721.
- Yamazaki, D., et al. (2019). MERIT Hydro: A high-resolution global hydrography map based on latest topography datasets. *Water Resources Research*, 55, 5053-5073.
- ESCOMP/mizuRoute GitHub: https://github.com/ESCOMP/mizuRoute (DOI: 10.5281/zenodo.595402)
