# SFINCS -- Knowledge Dissection Plan

**Prepared by**: HydroCraft Team (Jianyun Zhang Research Group, Hohai University)
**Date**: 2026-03-21
**Status**: Planning (pre-installation)

---

## Model Overview

| Field | Value |
|-------|-------|
| **Full Name** | Super-Fast INundation of CoastS (SFINCS) |
| **Developer** | Deltares (Netherlands) |
| **Version** | v2.1.1 (latest stable as of early 2026) |
| **License** | GPL-3.0 (open source since 2022) |
| **Repository** | https://github.com/Deltares/SFINCS |
| **Documentation** | https://sfincs.readthedocs.io |
| **Language** | Fortran 90 (core solver), C interop layer |
| **Python Tooling** | HydroMT-SFINCS (https://github.com/Deltares/hydromt_sfincs) -- model builder plugin |
| **Domain** | 2D shallow water flood inundation (coastal, fluvial, pluvial, compound) |

### What SFINCS Simulates

SFINCS solves a reduced-complexity 2D shallow water equation (subgrid-based) for rapid flood inundation modeling:

- **Coastal flooding**: Storm surge, tides, sea-level rise, wave setup
- **Fluvial flooding**: River overflow, levee breaches
- **Pluvial flooding**: Rainfall-driven urban flooding (ponding, sheet flow)
- **Compound flooding**: Combined coastal + fluvial + pluvial events (the primary use case -- events where multiple flood drivers interact)

The solver uses a subgrid approach: the hydrodynamic computation runs on a coarser "computational grid" (e.g., 50-200m) while bathymetry/topography and roughness are resolved at a finer "subgrid" resolution (e.g., 5-10m from high-res DEM). This gives accuracy comparable to a 10m full 2D model at computational cost closer to a 100m model.

### Key Differentiator from CaMa-Flood

| Feature | CaMa-Flood v4.20 | SFINCS v2.x |
|---------|------------------|-------------|
| **Resolution** | 15 arcmin (~28km), downscale to 1 arcmin (~1.8km) | 5m -- 1km (user-defined, typically 10-200m) |
| **Physics** | 1D local inertia along river network + floodplain storage | 2D shallow water with subgrid bathymetry |
| **Domain** | Global/continental river routing | Local/regional flood inundation (1-1000 km extent) |
| **Flood drivers** | River discharge only | Rainfall + river discharge + tide/surge + waves + wind + dam breaks |
| **Coastal** | No | Yes -- full tidal/surge boundary conditions |
| **Urban resolution** | No (1.8km at best) | Yes -- resolves streets and buildings with subgrid |
| **Speed** | Very fast (1D) | Fast for 2D (~10-100x faster than Delft3D/HEC-RAS 2D at same resolution) |
| **Use case** | Global/regional flood extent mapping | Local flood depth mapping, compound event analysis, urban flood risk |
| **GPU support** | No | Yes (OpenACC, CUDA) |

**SFINCS fills the high-resolution 2D flood inundation gap**: CaMa-Flood tells you WHICH grid cells flood at 15-arcmin scale; SFINCS tells you HOW DEEP the water is at 10-100m scale within a specific area of interest. They are complementary -- CaMa-Flood provides river boundary conditions for SFINCS.

### Binary/Package Availability

| Method | Status | Notes |
|--------|--------|-------|
| **Pre-built binaries** | Available | GitHub releases provide Linux/Windows executables for each tagged version |
| **Docker image** | Available | `deltares/sfincs` on Docker Hub |
| **Compile from source** | Possible | Requires Fortran compiler (gfortran/ifort) + NetCDF-Fortran libraries |
| **conda-forge** | HydroMT-SFINCS only | `conda install -c conda-forge hydromt_sfincs` (Python model builder, NOT the solver) |
| **pip** | HydroMT-SFINCS only | `pip install hydromt_sfincs` |

**Recommended for HydroCraft**: Download pre-built Linux binary from GitHub releases (simplest). Place at `model/sfincs/bin/sfincs`. Separately install HydroMT-SFINCS via pip for automated model setup.

---

## Installation Plan

### Phase A: SFINCS Solver (Fortran binary)

```
Target path: model/sfincs/bin/sfincs
```

**Option 1 (preferred): Pre-built binary from GitHub releases**
1. Download `sfincs_linux_x86_64` from https://github.com/Deltares/SFINCS/releases
2. Place at `model/sfincs/bin/sfincs`, `chmod +x`
3. Verify: `./sfincs --version`
4. Dependencies: libnetcdff (already installed for WRF-Hydro/CaMa-Flood)

**Option 2: Compile from source**
1. Clone repo: `git clone https://github.com/Deltares/SFINCS.git`
2. Dependencies: gfortran, netcdf-fortran, cmake
3. Build: `mkdir build && cd build && cmake .. && make`
4. Binary at `build/sfincs`

**Option 3: Docker**
```bash
docker pull deltares/sfincs:latest
docker run -v $(pwd):/data deltares/sfincs:latest
```

### Phase B: HydroMT-SFINCS (Python model builder)

```bash
source KISSPATH_PYTHON_ENV/bin/activate
pip install hydromt_sfincs
```

**HydroMT-SFINCS dependencies** (most already in the venv):
- hydromt (>=0.9.0): model builder framework
- geopandas, rasterio, xarray, netCDF4, shapely, pyproj
- dask (for lazy loading large DEMs)

**What HydroMT-SFINCS provides**:
- Automated grid generation from shapefile/bbox
- Automatic DEM/bathymetry download and subgrid table construction
- Manning's n from land use/land cover
- Spatially-varying rainfall from gridded datasets
- Observation point setup
- Boundary condition generation (water level, discharge, wave)

### Phase C: Validation datasets

- **Copernicus GLO-30 DEM**: Already available in HydroCraft (auto-downloaded by hydrobasin)
- **China DEM 90m**: Already at `data/dem/china_dem_90m/`
- **GEBCO bathymetry**: May need download for coastal basins (free, ~7.5 GB global)
- **FES2014 tidal model**: Needed for coastal boundary conditions (free academic license)
- **CMFD/MSWX precipitation**: Already available for rainfall forcing

### Estimated Effort: Installation

| Task | Time |
|------|------|
| Download + test pre-built binary | 0.5 hr |
| Install hydromt_sfincs + test | 0.5 hr |
| Download GEBCO bathymetry (coastal applications) | 1 hr |
| End-to-end test with simple case | 2 hr |
| **Total installation** | **4 hr** |

---

## SFINCS Input/Output Format

### Input Files

SFINCS uses a text-based configuration file (`sfincs.inp`) plus binary/NetCDF data files. The model reads everything from a single working directory.

| File | Format | Required | Description |
|------|--------|----------|-------------|
| `sfincs.inp` | Key-value text | Yes | Main configuration (grid, time, physics, I/O) |
| `sfincs.dep` | Binary (float32) | Yes | Bed level / topography on computational grid |
| `sfincs.msk` | Binary (uint8) | Yes | Active cell mask (0=inactive, 1=active boundary, 2=outflow, 3=active) |
| `sfincs.ind` | Binary (int32) | Yes | Subgrid index file |
| `sfincs.sbg` | Binary (float32) | Yes (subgrid mode) | Subgrid lookup tables (volume/cross-section vs water level) |
| `sfincs.man` | Binary (float32) | No | Spatially varying Manning's n |
| `sfincs.qin` | Binary (float32) | No | Spatially varying infiltration capacity |
| `sfincs.bnd` | Text (x,y pairs) | No | Water level boundary locations |
| `sfincs.bzs` | Text (time series) | No | Water level boundary time series |
| `sfincs.src` | Text (x,y pairs) | No | Discharge source locations |
| `sfincs.dis` | Text (time series) | No | Discharge source time series |
| `sfincs.precip` | NetCDF (gridded) | No | Spatially varying precipitation |
| `sfincs.spw` | Text (track format) | No | Tropical cyclone track (wind + pressure) |
| `sfincs.obs` | Text (x,y pairs) | No | Observation/output point locations |
| `sfincs.wnd` | Binary (float32) | No | Spatially varying wind fields |
| `sfincs.wst` | Binary (float32) | No | Initial water level |
| `sfincs.thd` | Text | No | Thin dam locations (levees, embankments) |
| `sfincs.drn` | Text | No | Drainage structure locations |
| `sfincs.weir` | Text | No | Weir locations and parameters |

### Key sfincs.inp Parameters

```
! Grid definition
mmax           = 500          ! Number of cells in x-direction
nmax           = 400          ! Number of cells in y-direction
dx             = 100.0        ! Cell size x (m)
dy             = 100.0        ! Cell size y (m)
x0             = 116.0        ! Origin x (longitude or easting)
y0             = 39.0         ! Origin y (latitude or northing)
rotation       = 0.0          ! Grid rotation (degrees)
epsg           = 32650        ! Coordinate reference system (EPSG code)

! Time
tref           = 20200701 000000   ! Reference time
tstart         = 20200701 000000   ! Start time
tstop          = 20200710 000000   ! Stop time
dt             = 10.0              ! Computational timestep (seconds)
dtout          = 3600.0            ! Output interval (seconds)
dthisout       = 600.0             ! Observation point output interval (seconds)

! Physics
manning        = 0.04         ! Uniform Manning's n (if no sfincs.man file)
zsini          = 0.0          ! Initial water level (if no sfincs.wst file)
qinf           = 0.0          ! Uniform infiltration rate (mm/hr)
baro           = 0            ! Barometric pressure effect (0=off, 1=on)
pavbnd         = 101325.0     ! Reference atmospheric pressure (Pa)
advection      = 0            ! Advection (0=off, 1=on -- rarely needed)
alpha          = 0.75         ! Momentum damping coefficient

! Subgrid
sbgfile        = sfincs.sbg   ! Subgrid table file
depfile        = sfincs.dep   ! Bed level file (computational grid)
mskfile        = sfincs.msk   ! Mask file
indexfile      = sfincs.ind   ! Index file

! Boundaries
bndfile        = sfincs.bnd   ! Water level boundary locations
bzsfile        = sfincs.bzs   ! Water level boundary values
srcfile        = sfincs.src   ! Discharge source locations
disfile        = sfincs.dis   ! Discharge source values

! Precipitation
netprecipfile  = sfincs.precip  ! NetCDF precipitation file
precipfile     = sfincs.precip  ! Uniform precipitation time series

! Output
outputformat   = net           ! Output format: "net" (NetCDF) or "bin" (binary)
obsfile        = sfincs.obs    ! Observation points
```

### Output Files

| File | Format | Description |
|------|--------|-------------|
| `sfincs_map.nc` | NetCDF | Gridded output: water depth (zs), water level (zsmax), velocity, discharge, cumulative precipitation |
| `sfincs_his.nc` | NetCDF | Time series at observation points |
| `sfincs.log` | Text | Runtime log (progress, warnings, errors) |
| `sfincs_zsmax.nc` | NetCDF | Maximum water depth map (for flood extent) |

### CLI Usage

SFINCS is a simple command-line executable with no arguments. It reads `sfincs.inp` from the current working directory:

```bash
cd /path/to/model/directory
/path/to/sfincs        # Reads sfincs.inp from current directory, writes output here
```

No command-line arguments, no GUI dependency. The model directory must contain `sfincs.inp` and all referenced data files. This makes it fully automatable.

For parallel execution (multi-threaded OpenMP):
```bash
export OMP_NUM_THREADS=4
/path/to/sfincs
```

For GPU execution (if compiled with OpenACC/CUDA):
```bash
/path/to/sfincs_gpu    # Separate binary compiled with GPU support
```

---

## Pipeline Stages (Proposed)

The SFINCS pipeline for HydroCraft follows 8 stages, from domain definition to post-processing. HydroMT-SFINCS automates stages 1-5; tools wrap HydroMT calls and add HydroCraft-specific validation.

| Stage | ID | Name | Tools to Build | Description |
|-------|----|------|---------------|-------------|
| 1 | s1_domain | Domain Setup | `setup_sfincs_domain.py` | Define computational grid (extent, resolution, CRS) from basin shapefile or bbox. Compute optimal grid size based on DEM resolution and basin area. |
| 2 | s2_topobathy | Topography & Bathymetry | `build_sfincs_topobathy.py` | Build subgrid tables from high-res DEM (Copernicus GLO-30 or China 90m). For coastal basins, merge with GEBCO bathymetry. Generate sfincs.dep, sfincs.sbg, sfincs.ind, sfincs.msk. |
| 3 | s3_roughness | Roughness | `build_sfincs_roughness.py` | Generate spatially varying Manning's n from AVHRR land cover (same source as VIC). Urban: 0.06-0.10, agriculture: 0.03-0.05, water: 0.02-0.03, forest: 0.10-0.15. |
| 4 | s4_forcing | Forcing Data | `prepare_sfincs_forcing.py`, `prepare_sfincs_coastal_bc.py` | Convert CMFD/MSWX precipitation to SFINCS netprecip format. For coastal basins: generate tidal/surge boundary conditions. For fluvial: convert CaMa-Flood or VIC discharge to SFINCS source points. |
| 5 | s5_structures | Hydraulic Structures | `setup_sfincs_structures.py` | Add thin dams (levees), drainage structures, weirs from GIS data. Optional -- only for urban/engineered domains. |
| 6 | s6_config | Configuration | `generate_sfincs_inp.py` | Generate sfincs.inp with correct timestep, physics options, output settings. Auto-compute dt from grid resolution (CFL condition: dt <= dx / sqrt(g*h_max)). |
| 7 | s7_execution | Execution | `run_sfincs.py` | Run SFINCS solver with preflight checks. Monitor log for convergence. Handle OMP_NUM_THREADS and GPU detection. |
| 8 | s8_postprocess | Post-Processing | `extract_sfincs_results.py`, `plot_sfincs_flood_map.py`, `compute_flood_statistics.py` | Extract flood depth maps, max inundation extent, time series at obs points. Compute flood statistics (area, volume, duration). Generate publication-quality flood maps. |

### Stage Dependencies

```
s1_domain ──┐
             ├──> s2_topobathy ──┐
             │                    ├──> s5_structures ──┐
             ├──> s3_roughness ──┤                     │
             │                    │                     ├──> s6_config ──> s7_execution ──> s8_postprocess
             └──> s4_forcing ────┘                     │
                                                       │
                  [VIC/CaMa-Flood upstream] ───────────┘
```

Stages s2, s3, s4 can run in parallel after s1. Stage s5 is optional. Stage s6 depends on s2+s3+s4+(s5). Stage s7 depends on s6. Stage s8 depends on s7.

---

## Tools to Build (Proposed)

| # | Tool | Stage | Lines (est.) | Purpose |
|---|------|-------|-------------|---------|
| 1 | `setup_sfincs_domain.py` | s1 | ~250 | Define grid from shapefile/bbox, auto-compute resolution from basin area, project to UTM |
| 2 | `build_sfincs_topobathy.py` | s2 | ~400 | Build subgrid tables from DEM. Merge GEBCO bathymetry for coastal domains. Uses HydroMT-SFINCS `setup_dep()` + `setup_subgrid()`. |
| 3 | `build_sfincs_roughness.py` | s3 | ~200 | Map AVHRR land cover to Manning's n. Uses HydroMT-SFINCS `setup_manning_roughness()`. |
| 4 | `prepare_sfincs_forcing.py` | s4 | ~350 | Convert CMFD/MSWX gridded precip to SFINCS NetCDF format. Handle unit conversion (mm/3hr to mm/hr). |
| 5 | `prepare_sfincs_coastal_bc.py` | s4 | ~300 | Generate tidal/surge boundary conditions from FES2014 or user-provided water level data. |
| 6 | `convert_cama_to_sfincs_bc.py` | s4 | ~250 | Convert CaMa-Flood river discharge/stage to SFINCS source/boundary conditions. Key coupling tool. |
| 7 | `convert_vic_to_sfincs_src.py` | s4 | ~200 | Convert VIC runoff to SFINCS discharge source points. For direct VIC-SFINCS coupling without CaMa-Flood. |
| 8 | `setup_sfincs_structures.py` | s5 | ~250 | Add thin dams, weirs, drainage structures from GIS shapefiles. |
| 9 | `generate_sfincs_inp.py` | s6 | ~300 | Generate sfincs.inp with all parameters. Auto-compute timestep from CFL condition. |
| 10 | `run_sfincs.py` | s7 | ~250 | Execute SFINCS with preflight validation, log monitoring, JSON summary output. |
| 11 | `extract_sfincs_results.py` | s8 | ~300 | Read sfincs_map.nc, extract flood depth/extent, compute statistics. |
| 12 | `plot_sfincs_flood_map.py` | s8 | ~350 | Generate flood inundation maps with basemap tiles (consistent with HydroCraft plot style). |
| 13 | `compute_flood_statistics.py` | s8 | ~200 | Compute: flooded area, max depth, flood volume, duration, affected grid cells by depth class. |
| 14 | `validate_sfincs_water_balance.py` | s8 | ~150 | Check mass conservation: precip + inflow = outflow + storage change + infiltration. |
| 15 | `run_sfincs_full_pipeline.py` | all | ~400 | End-to-end wrapper calling stages s1-s8 sequentially with JSON progress reporting. |
| | **Total** | | **~3,650** | **15 tools** |

---

## Skill Documents (Proposed)

| # | Document | Stage(s) | Covers | Est. Words |
|---|----------|----------|--------|-----------|
| 1 | `docs/s1_domain_setup_skill.md` | s1 | Grid resolution selection (area-based heuristic), CRS choice (geographic vs projected), buffer around basin, computational vs subgrid resolution ratio (typically 5-20x) | ~1,500 |
| 2 | `docs/s2_topobathy_skill.md` | s2 | DEM source selection (GLO-30 vs China 90m vs GEBCO), subgrid table construction, bathymetry-topography merging for coastal zones, vertical datum alignment (EGM96 vs EGM2008 vs local), gap filling | ~2,000 |
| 3 | `docs/s3_roughness_skill.md` | s3 | Manning's n lookup table by land cover class, urban roughness (buildings as elevated topography vs increased n), sensitivity analysis guidance | ~1,000 |
| 4 | `docs/s4_forcing_boundary_skill.md` | s4 | Precipitation format (uniform vs gridded), temporal resolution selection, tidal BC generation from harmonic constituents, river BC from CaMa-Flood/VIC, combined forcing for compound events | ~2,500 |
| 5 | `docs/s5_structures_skill.md` | s5 | Thin dam representation (levees, sea walls), weir equations, drainage capacity, when structures matter vs when they can be ignored | ~1,000 |
| 6 | `docs/s6_configuration_skill.md` | s6 | Timestep selection (CFL stability), physics options (advection, viscosity, barometric), output variable selection, observation point placement | ~1,500 |
| 7 | `docs/s7_execution_skill.md` | s7 | Runtime estimation (cells x timesteps / OMP threads), convergence monitoring, GPU vs CPU tradeoffs, memory requirements | ~1,000 |
| 8 | `docs/s8_postprocessing_skill.md` | s8 | Flood map generation, depth classification (0-0.3m, 0.3-1m, 1-3m, >3m), flood duration computation, comparison with satellite/CaMa-Flood, statistical validation | ~1,500 |
| 9 | `docs/coupling_skill.md` | s4 (coupling) | CaMa-Flood-to-SFINCS coupling protocol, VIC-to-SFINCS coupling, SWMM-to-SFINCS coupling, spatial alignment, temporal interpolation, unit conversions, double-counting avoidance | ~2,000 |
| 10 | `docs/calibration_guide.md` | all | Key calibration parameters (Manning's n, infiltration rate, subgrid resolution), sensitivity analysis, validation against observed flood marks/satellite imagery | ~1,500 |
| | **Total** | | | **~15,500** |

---

## Diagnostic Triplets (Anticipated)

Based on patterns from 15 model dissections and SFINCS-specific failure modes.

### Unit Conversion Errors (SILENT -- highest priority)

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_001 | Flood depths 10-100x too high | Precipitation in mm/3hr not converted to mm/hr (SFINCS expects mm/hr) | silent |
| dt_002 | No flooding despite heavy rain | Precipitation in m/s instead of mm/hr (factor of 3.6e6 too small) | silent |
| dt_003 | CaMa-Flood discharge BC produces wrong flood extent | Discharge in mm/day (VIC units) not converted to m^3/s | silent |
| dt_004 | Coastal water levels systematically offset | Vertical datum mismatch: DEM uses EGM96 geoid but tide model uses MSL/chart datum | silent |

### Grid/Spatial Errors

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_005 | SFINCS crashes immediately with "grid error" | CRS mismatch: sfincs.inp uses geographic (deg) but dx/dy are in meters | fatal |
| dt_006 | Flood map displaced from actual terrain | x0/y0 origin does not match DEM origin after reprojection | silent |
| dt_007 | Water flows uphill at domain boundary | Mask file boundary cells set to 3 (active) instead of 2 (outflow) | silent |
| dt_008 | Subgrid artifacts: checkerboard pattern | Subgrid resolution too fine relative to computational grid (ratio > 30x) | degraded |

### Timestep/Stability Errors

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_009 | Model crashes with NaN after N steps | dt too large for dx (CFL violation: dt > dx/sqrt(g*h)) | fatal |
| dt_010 | Very slow convergence, oscillating water levels | Advection enabled with alpha too low for steep terrain | degraded |
| dt_011 | Simulation takes 100x expected time | dt auto-reduced by solver due to instability; grid resolution too fine for domain size | degraded |

### Boundary Condition Errors

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_012 | Water level BC has no effect | Boundary point locations (sfincs.bnd) not aligned to active mask cells | silent |
| dt_013 | Discharge source creates artificial pond | Source point placed on high ground (not in channel), no drainage path | degraded |
| dt_014 | Tidal signal wrong amplitude or phase | FES2014 constituents for wrong location or datum not adjusted | silent |

### Coupling Errors

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_015 | Double flood volume | Same precipitation applied in both VIC and SFINCS (not subtracted from VIC) | silent |
| dt_016 | CaMa-Flood boundary flows in wrong direction | Stage BC should be water level but discharge BC was used, or sign convention mismatch | silent |
| dt_017 | Temporal gap in boundary conditions | CaMa-Flood output at daily step, SFINCS needs sub-hourly; linear interpolation causes artificial ramps | degraded |

### I/O and Path Errors

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_018 | "Cannot open file sfincs.dep" | SFINCS reads from CWD only; ran binary from wrong directory | fatal |
| dt_019 | Output file empty or missing | outputformat not set; default may be binary when NetCDF expected | degraded |
| dt_020 | Model runs but output is all zeros | msk file has no active cells (all values 0) | silent |

### Summary

| Category | Count (est.) | % Silent |
|----------|-------------|----------|
| Unit conversion | 4 | 100% |
| Grid/spatial | 4 | 50% |
| Timestep/stability | 3 | 0% |
| Boundary conditions | 3 | 67% |
| Coupling | 3 | 67% |
| I/O and path | 3 | 33% |
| **Total** | **20** | **50%** |

**Note**: 50% silent error rate is consistent with SFINCS being a Fortran solver with binary I/O -- the same class of problems seen in CaMa-Flood (STOP 10 exits with code 0) and WRF-Hydro (D8 encoding wrong = silent). The coupling triplets (dt_015-017) draw directly from cross-model patterns cm_011 (double-counting) and cm_004 (unit mismatch).

---

## Coupling Points with HydroCraft

SFINCS integrates with 4 existing HydroCraft models across 7 coupling pathways.

### Upstream Couplings (data flows INTO SFINCS)

| # | Coupling | Direction | Data Flow | Unit Conversion | Tool |
|---|----------|-----------|-----------|-----------------|------|
| c1 | CaMa-Flood --> SFINCS (discharge) | upstream | CaMa-Flood `outflw` (m^3/s) at river-SFINCS domain boundary --> SFINCS discharge source (sfincs.dis) | None (both m^3/s) but temporal interpolation needed (daily to sub-hourly) | `convert_cama_to_sfincs_bc.py` |
| c2 | CaMa-Flood --> SFINCS (water level) | upstream | CaMa-Flood `sfcelv` (m) at river boundary --> SFINCS water level BC (sfincs.bzs) | Verify vertical datum consistency (both relative to geoid) | `convert_cama_to_sfincs_bc.py` |
| c3 | VIC --> SFINCS (runoff) | upstream | VIC surface runoff + baseflow (mm/day per cell) --> SFINCS distributed source | mm/day x area_m2 / 86400000 = m^3/s at each source point | `convert_vic_to_sfincs_src.py` |
| c4 | CMFD/MSWX --> SFINCS (precipitation) | upstream | Gridded precipitation --> SFINCS NetCDF precip file | mm/3hr to mm/hr (divide by 3) | `prepare_sfincs_forcing.py` |

### Downstream Couplings (data flows FROM SFINCS)

| # | Coupling | Direction | Data Flow | Tool |
|---|----------|-----------|-----------|------|
| c5 | SFINCS --> CaMa-Flood | downstream | SFINCS outflow at domain boundary --> CaMa-Flood lateral inflow (for iterative coupling) | (future tool) |
| c6 | SFINCS --> SWMM | bidirectional | SFINCS surface water depth at urban boundary --> SWMM external inflow; SWMM pipe overflow --> SFINCS surface ponding | (future tool) |

### One-Way vs Two-Way Coupling

For most HydroCraft applications, **one-way coupling** is sufficient and much simpler:

1. **Standard workflow**: VIC --> CaMa-Flood --> SFINCS (one-way, cascade)
   - VIC produces watershed runoff
   - CaMa-Flood routes to river channels, produces discharge/stage at SFINCS boundary
   - SFINCS simulates local flood inundation at high resolution
   - No feedback needed (local flood doesn't significantly affect upstream hydrology)

2. **Urban compound flooding**: VIC --> CaMa-Flood --> SFINCS <--> SWMM (two-way at urban interface)
   - Only needed when pipe surcharging creates surface flooding that re-enters the 2D domain
   - Complex, defer to Phase 2

### Coupling Avoidance of Double-Counting (CRITICAL)

When coupling VIC/CaMa-Flood with SFINCS, the **same rainfall must NOT be applied twice**:

- **If SFINCS uses gridded precipitation** (`netprecipfile`): Do NOT also apply VIC surface runoff as SFINCS inflow. The SFINCS domain handles its own rainfall-runoff. Use CaMa-Flood discharge only for the river boundary.
- **If SFINCS uses only river boundary conditions** (no precipitation): Then VIC/CaMa-Flood handles ALL rainfall-runoff, and SFINCS only routes the water across the floodplain. This avoids double-counting but misses local pluvial flooding.
- **Recommended approach**: Use SFINCS with its own precipitation for the local domain. Exclude the SFINCS domain area from VIC grid cells to avoid double-counting. Use CaMa-Flood discharge as SFINCS river boundary only.

---

## Validation Plan

### Phase 1: Synthetic/Benchmark Test (Week 1)

- Use SFINCS built-in test cases from the GitHub repo (if available) or create a simple flat-plane rainfall test
- Verify: mass conservation, correct flood depth for known analytical solution
- Success: water balance error < 0.1%, depth matches analytical solution within 5%

### Phase 2: Existing HydroCraft Basin -- Chaohe (Week 2)

**Why Chaohe**: Small (8,783 km^2), mountainous, existing VIC + CaMa-Flood + SWAT+ runs, semi-humid with summer monsoon flood events. CaMa-Flood downscaled output already exists for comparison.

- **Domain**: Lower Chaohe floodplain near Miyun Reservoir (~200 km^2 subdomain)
- **Resolution**: 50m computational, 10m subgrid (from China DEM 90m resampled)
- **Forcing**: CaMa-Flood discharge as river BC + CMFD precipitation as rainfall
- **Period**: July-September 2003 (wettest year in simulation)
- **Compare against**:
  - CaMa-Flood 1-arcmin downscaled flood depth
  - Sentinel-1 SAR flood extent (if available for the period)
- **Success criteria**: Flood extent agreement > 70% (critical success index) vs CaMa-Flood, water balance error < 1%

### Phase 3: Coastal Basin Test (Week 3-4)

**Why**: SFINCS's primary differentiator is compound coastal flooding -- must validate this capability.

- **Basin**: Pearl River Delta or Yangtze estuary (existing HydroCraft VIC runs)
- **Forcing**: CaMa-Flood river discharge + FES2014 tidal BC + MSWX precipitation
- **Compare against**: Historical flood records, satellite imagery
- **Success criteria**: Peak water level within 0.3m of observations, flood extent matches satellite within 60%

### Phase 4: Integration Test (Week 4)

- Full pipeline: VIC --> CaMa-Flood --> SFINCS, triggered by single command
- Test `run_sfincs_full_pipeline.py` end-to-end
- Verify JSON progress reporting, error handling, output file generation

---

## Estimated Effort

| Phase | Tasks | Hours |
|-------|-------|-------|
| **Installation** | Binary download, HydroMT-SFINCS pip install, basic test | 4 |
| **Phase 1: Pipeline Mapping** | Map stages, dependencies, milestones | 4 |
| **Phase 2: Knowledge Classification** | Classify procedural/evaluative/debugging per stage | 3 |
| **Phase 3: Tool Extraction** | Build 15 tools (~3,650 lines) | 32 |
| -- Tool 1-3 (domain, topobathy, roughness) | HydroMT-SFINCS wrappers | 8 |
| -- Tool 4-7 (forcing, coastal BC, coupling) | Unit conversion, format bridging | 10 |
| -- Tool 8 (structures) | GIS processing | 3 |
| -- Tool 9-10 (config, execution) | Template generation, preflight | 5 |
| -- Tool 11-14 (post-processing) | NetCDF extraction, flood stats, plotting | 6 |
| **Phase 4: Skill Documents** | Write 10 skill docs (~15,500 words) | 12 |
| **Phase 5: Diagnostic Triplets** | Build 20 triplets, probe for silent errors | 6 |
| **Phase 6: Assembly & Validation** | Cross-reference audit, end-to-end test, SKILL.md | 8 |
| **Validation** | Chaohe + coastal basin + integration test | 16 |
| **Total** | | **85 hours (~2 weeks full-time)** |

---

## Priority & Dependencies

### Prerequisites (must be done first)

1. **Download SFINCS binary** -- blocking for all subsequent work
2. **Install HydroMT-SFINCS** -- blocking for automated model setup (tools 1-3)
3. **Verify NetCDF-Fortran compatibility** -- SFINCS needs the same libnetcdff as WRF-Hydro/CaMa-Flood (likely already satisfied)

### Critical Path

```
Install binary --> Test basic case --> Build s1_domain tool --> Build s2_topobathy tool
    --> Build s6_config tool --> Build s7_execution tool --> End-to-end test
```

This critical path (tools 1, 2, 9, 10) produces a minimal working pipeline. The remaining tools (forcing, coupling, structures, post-processing) can be built in parallel once the critical path is verified.

### Parallelizable Work

These can proceed in parallel once the binary is installed:

| Track | Work |
|-------|------|
| **Track A (core)** | Tools s1, s2, s6, s7 -- minimal pipeline |
| **Track B (forcing)** | Tools s4 (forcing), s4 (coastal BC) -- independent of core tools |
| **Track C (coupling)** | Tools c1 (CaMa-->SFINCS), c3 (VIC-->SFINCS) -- needs CaMa-Flood output from existing runs |
| **Track D (post-processing)** | Tools s8 (results, plot, stats) -- can use any SFINCS output |
| **Track E (documentation)** | Skill documents and triplets -- can proceed once pipeline is mapped |

### Integration with knowledge_infrastructure.yaml

After dissection, register in the central knowledge infrastructure:

```yaml
# In KISSPATH_HOME/LDNDC/knowledge_infrastructure/knowledge_infrastructure.yaml
# Add under models section:
- name: SFINCS
  version: "2.1.1"
  package: hydrocraft-sfincs
  stages: 8
  tools: 15
  skill_documents: 10
  diagnostic_triplets: 20
  couplings:
    - c_sfincs_01: CaMa-Flood discharge --> SFINCS source BC
    - c_sfincs_02: CaMa-Flood water level --> SFINCS water level BC
    - c_sfincs_03: VIC runoff --> SFINCS distributed source
    - c_sfincs_04: CMFD/MSWX precip --> SFINCS gridded rainfall
    - c_sfincs_05: SFINCS outflow --> CaMa-Flood lateral (future)
    - c_sfincs_06: SFINCS <--> SWMM bidirectional (future)
```

### CLAUDE.md Updates

After validation, add SFINCS to the main CLAUDE.md:

- Add to "Supported Models" table under "Flood Inundation" domain
- Add coupling descriptions
- Add to "Platform Numbers" (models: 18, tools: ~257, triplets: ~313)
- Add SFINCS workflow section (similar to CaMa-Flood section)

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Pre-built binary incompatible with server OS (Ubuntu kernel 6.17) | Low | High | Fall back to compilation from source; Fortran + NetCDF already installed |
| HydroMT-SFINCS version conflict with existing Python env | Medium | Medium | Test in venv first; if conflict, create separate conda env |
| Subgrid table generation OOM for large domains | Medium | Medium | Limit subgrid ratio to 10x; process in tiles |
| China DEM 90m too coarse for meaningful subgrid | Low | Low | 90m subgrid with 250m computational grid still adds value vs CaMa-Flood 1.8km |
| GEBCO bathymetry download blocked / license issue | Low | Low | Only needed for coastal applications; fluvial-only works without it |
| FES2014 tidal model requires registration | Medium | Low | Only needed for coastal applications; can use simplified tidal signal as placeholder |

---

## Appendix: SFINCS vs Other 2D Flood Models

| Feature | SFINCS | Delft3D FM | HEC-RAS 2D | LISFLOOD-FP |
|---------|--------|-----------|------------|-------------|
| **Speed** | Very fast (subgrid) | Slow (full SWE) | Medium | Fast (simplified) |
| **Physics** | Reduced-complexity SWE + subgrid | Full SWE (unstructured) | Full SWE | Local inertia / diffusive wave |
| **GPU** | Yes (OpenACC) | Yes (CUDA) | No | No |
| **Grid** | Regular (with subgrid) | Unstructured | Unstructured | Regular |
| **Compound flooding** | Excellent | Excellent | Limited | Limited |
| **Open source** | Yes (GPL-3) | Partial (AGPL) | No (free but closed) | Yes (GPL-3) |
| **Python setup** | HydroMT-SFINCS | dfm_tools | RAS Commander | No official |
| **HydroCraft fit** | Best | Overkill | License issue | Good alternative |

SFINCS is chosen over alternatives because:
1. **Fastest** for the accuracy level needed (subgrid gives near-full-resolution accuracy at fraction of cost)
2. **Open source** with active Deltares development
3. **HydroMT-SFINCS** provides fully automated Python-based model setup (no GUI)
4. **Compound flooding** capability (coastal + fluvial + pluvial in one model)
5. **GPU support** for large domains
6. **Simple CLI** (no arguments, reads from CWD) -- trivially automatable by AI agent

---

## Appendix: Key Publications

1. Leijnse, T., van Ormondt, M., Pronk, M., et al. (2021). "Modeling compound flooding in coastal systems using a computationally efficient reduced-physics solver: Including fluvial, pluvial, tidal, wind- and wave-driven processes." *Coastal Engineering*, 163, 103796.

2. Leijnse, T., et al. (2024). "Global applicability of the SFINCS flood model." NHESS Preprint. -- Validated SFINCS against observations in 100+ basins worldwide, demonstrating global applicability with Copernicus DEM + satellite data.

3. Bates, P. D., et al. (2023). "Combined Modeling of US Fluvial, Pluvial, and Coastal Flood Hazard Under Current and Future Climates." *Water Resources Research*. -- Uses SFINCS for compound flood hazard assessment.

4. van Ormondt, M., et al. (2020). "A comprehensive approach for compound flood modeling in coastal areas." *Nature Communications*.

5. Eilander, D., et al. (2023). "HydroMT: Automated and reproducible model building and analysis." *JOSS*.

---

## Appendix: SFINCS Preflight Checklist (from knowledge-dissection-toolkit)

Classifying SFINCS against the PREFLIGHT.md trap categories:

- [x] **Has Fortran code** --> Watch for path length limits (sfincs.inp references), binary I/O endianness
- [ ] **Reads fixed-width text files** --> sfincs.inp is key-value (flexible), but .bnd/.bzs/.src/.dis are space-delimited tabular (verify column parsing)
- [x] **Will be coupled with other models** --> CaMa-Flood, VIC, SWMM -- see coupling traps (double-counting, datum mismatch, temporal alignment)
- [x] **Has physical units** --> mm/hr (precip), m^3/s (discharge), m (depth/elevation), s (time) -- see unit traps
- [x] **Uses spatial data** --> CRS must match between DEM, grid, and boundary points -- see spatial traps
- [ ] **Is a crop/ecosystem model** --> No
- [ ] **Runs on Linux but was built for Windows** --> Native Linux support, no platform issues expected

**Highest-risk trap categories for SFINCS**: Unit conversion (precipitation, discharge), coupling double-counting, vertical datum mismatch (coastal).
