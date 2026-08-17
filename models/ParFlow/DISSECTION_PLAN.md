# ParFlow Knowledge Dissection Plan

**Model**: ParFlow (Parallel Flow)
**Version target**: v3.13+ (latest stable)
**Domain**: Integrated surface-subsurface hydrology (variably saturated 3D Richards equation + overland flow + CLM land surface)
**Role in HydroCraft**: Replaces the VIC + MODFLOW + CaMa-Flood chain with a single physically-coupled model that solves surface and subsurface flow simultaneously
**Author**: Jianyun Zhang Research Group, Hohai University
**Date**: 2026-03-21
**Status**: PLANNING (no installation, no tools built yet)

---

## 1. Model Overview

### 1.1 What ParFlow Is

ParFlow is an open-source, massively parallel integrated hydrological model developed at Lawrence Livermore National Laboratory and collaborating institutions (Colorado School of Mines, Bonn University, Juelich Research Centre). It uniquely solves the **3D variably-saturated Richards equation** coupled with **2D kinematic wave overland flow** in a single nonlinear system, eliminating the artificial separation between surface water, soil water, and groundwater that plagues conventional model chains (like VIC + MODFLOW).

**Key physics**:
- **Subsurface**: 3D Richards equation for variably saturated flow through heterogeneous porous media. Solves pressure head as the primary variable. Uses van Genuchten (1980) or Brooks-Corey relative permeability and saturation-pressure relationships.
- **Overland flow**: 2D diffusive/kinematic wave equation on the terrain surface, directly coupled to the top cell of the 3D subsurface grid through a flux boundary condition. Manning's equation for friction.
- **Land surface (optional)**: CLM (Community Land Model) v4.5 coupled as the top boundary, providing energy balance, evapotranspiration, snow, and vegetation dynamics. Replaces the need for a separate land surface model like Noah-MP (WRF-Hydro) or VIC energy balance.
- **Solver**: Multigrid-preconditioned Newton-Krylov nonlinear solver (from HYPRE). Handles the severe nonlinearity of Richards equation across saturation fronts.

### 1.2 Why ParFlow Fills a Gap in HydroCraft

Currently in HydroCraft:
- **VIC** handles land surface + vadose zone (1D, 3 soil layers, no lateral flow)
- **MODFLOW 6** handles saturated groundwater (3D, but no vadose zone, no overland flow)
- **CaMa-Flood / Lohmann** handles river routing (1D/2D, but disconnected from subsurface)

These three models are loosely coupled via file exchange, creating:
- **Temporal lag**: VIC runs first, then MODFLOW uses VIC percolation as recharge, then routing uses VIC runoff. No feedback within a timestep.
- **Process gaps**: No capillary rise from water table to root zone. No lateral subsurface flow. No groundwater-fed springs or seeps generating overland flow.
- **Double-counting risk**: VIC baseflow and MODFLOW drain discharge may overlap.

ParFlow solves all of these in a single model:
- Variably saturated flow from land surface to deep aquifer in one equation
- Overland flow directly coupled to subsurface through pressure continuity
- Lateral subsurface flow (hillslope interflow, perched water tables)
- Groundwater exfiltration generating overland flow (rejection excess, saturation excess)
- Full feedback at every timestep (CLM ET depletes soil moisture depletes water table affects baseflow)

### 1.3 Key Capabilities

| Feature | ParFlow | VIC+MODFLOW Chain |
|---------|---------|-------------------|
| Subsurface flow | 3D Richards (variably saturated) | 1D VIC vadose + 3D MODFLOW saturated |
| Overland flow | 2D kinematic/diffusive wave, coupled | Separate CaMa-Flood, file-coupled |
| Land surface | CLM 4.5 (energy + water balance) | VIC energy balance |
| Lateral flow | Full 3D (hillslope interflow) | None in VIC, MODFLOW only saturated |
| GW-surface coupling | Pressure continuity at water table | File exchange, 1-way |
| Parallelism | MPI + GPU (CUDA/Kokkos/OpenMP) | Serial (VIC), serial (MODFLOW) |
| Resolution | Uniform or variable (terrain-following grid) | Fixed lat/lon grid per model |
| Solver | Newton-Krylov with multigrid preconditioner | VIC: explicit; MODFLOW: PCG/IMS |
| Global datasets | ParFlow-CONUS (1km), SoilGrids, MERIT DEM | HWSD, GLHYMPS, China DEM |

### 1.4 Foundational References

- Ashby & Falgout (1996): Parallel multigrid preconditioned conjugate gradient algorithm
- Jones & Woodward (2001): Newton-Krylov-multigrid solver for variably saturated flow
- Kollet & Maxwell (2006): Integrated surface-subsurface coupling formulation
- Maxwell (2013): Terrain-following coordinate transformation
- Maxwell et al. (2015): ParFlow user manual (comprehensive)
- Kuffour et al. (2020): ParFlow v3.6 technical description

---

## 2. Installation Plan

### 2.1 Dependencies

| Dependency | Required? | Purpose | HydroCraft Status |
|-----------|-----------|---------|-------------------|
| **CMake >= 3.22** | Required | Build system | Available (system) |
| **C/C++/Fortran compilers** | Required | Core compilation (C11/C++11) | gcc/gfortran available |
| **TCL** | Required | pftools (legacy scripting interface) | Needs `tcl-dev` |
| **MPI** | Required for parallel | Domain decomposition | MPICH available (from WRF-Hydro) |
| **HYPRE** | Strongly recommended | Multigrid preconditioner (critical for performance) | Needs building |
| **SILO** | Optional | Visualization output format (VisIt) | Not needed if using PFB/NetCDF |
| **HDF5** | Optional | NetCDF backend, large file support | Available (from NetCDF4) |
| **NetCDF** | Optional | Standard output format | Available |
| **SUNDIALS** | Optional | ODE solvers (for some CLM configurations) | Needs building |
| **Python >= 3.7** | Optional | pftools Python interface | Available (python_env) |
| **CUDA toolkit** | Optional | GPU acceleration | Not available (no GPU on this server) |

### 2.2 Build Steps (CMake)

```bash
# 1. Clone repository
git clone https://github.com/parflow/parflow.git
cd parflow && git checkout v3.13.0

# 2. Build HYPRE (critical dependency)
cd dependencies
tar xzf hypre-*.tar.gz && cd hypre/src
./configure --prefix=$INSTALL_DIR/hypre --with-MPI
make -j$(nproc) && make install

# 3. Build ParFlow
mkdir build && cd build
cmake .. \
  -DCMAKE_INSTALL_PREFIX=$INSTALL_DIR/parflow \
  -DPARFLOW_ENABLE_TIMING=TRUE \
  -DPARFLOW_HAVE_CLM=ON \
  -DPARFLOW_ENABLE_HYPRE=TRUE \
  -DHYPRE_ROOT=$INSTALL_DIR/hypre \
  -DPARFLOW_ENABLE_HDF5=TRUE \
  -DPARFLOW_ENABLE_NETCDF=TRUE \
  -DPARFLOW_AMPS_LAYER=mpi1 \
  -DPARFLOW_ACCELERATOR_BACKEND=none

make -j$(nproc)
make install

# 4. Install pftools Python package
pip install pftools
```

### 2.3 Installation Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| HYPRE version mismatch | Solver crashes or poor performance | Pin to version shipped with ParFlow |
| TCL version conflict | pftools compilation fails | Use system TCL, not conda |
| MPI library mismatch | Runtime segfault | Use same MPICH as WRF-Hydro |
| No GPU | Cannot use CUDA/Kokkos backends | Use `PARFLOW_ACCELERATOR_BACKEND=none`; MPI parallelism sufficient for basin-scale |
| CLM Fortran compilation | Fortran module path errors | Ensure gfortran matches C compiler version |

### 2.4 Proposed Installation Path

```
KISSPATH_BINARIES/parflow/
  deps/
    hypre-install/
  parflow-v3.13/          # source
  install/                 # installed binaries
    bin/parflow
    bin/pftools
```

### 2.5 Verification Test

Run the included test suite (small 2D hillslope):
```bash
cd parflow/test
make check    # runs ~100 regression tests
```

Or minimal: `default_single.tcl` (10x10x10 box, steady state, serial).

---

## 3. Pipeline Stages

The ParFlow pipeline has **10 stages** from raw basin data to coupled simulation output. This is analogous to the WRF-Hydro 12-stage pipeline but with different domain setup requirements due to the 3D variably-saturated grid.

### Stage Overview

```
S0 Configuration ──> S1 Domain/Grid ──> S2 Subsurface Properties ──> S3 Topography/Slopes
                          │                     │                          │
                          v                     v                          v
                     S4 CLM Setup ──> S5 Forcing Data ──> S6 IC/BC ──> S7 Solver Config
                                                                           │
                                                                           v
                                                                    S8 Execution
                                                                           │
                                                                           v
                                                                  S9 Output Processing
```

### S0: Configuration

**Purpose**: Define basin, period, resolution, and paths. Equivalent to `config_paths.py` in VIC pipeline.

**Key parameters**:
- Basin name, shapefile path, outlet coordinates
- Simulation period (start/end datetime)
- Grid resolution (dx, dy in meters; dz layer thicknesses)
- Number of subsurface layers and their thicknesses
- CLM on/off
- MPI decomposition (P, Q, R topology)

**Outputs**: Configuration file (Python dict or YAML) consumed by all subsequent stages.

### S1: Domain and Grid Definition

**Purpose**: Create the 3D computational domain covering the basin.

**Key decisions**:
- **Horizontal grid**: Uniform structured grid (NX x NY) covering basin extent. ParFlow uses Cartesian (meters), not lat/lon. Must project basin shapefile to UTM or local coordinate system.
- **Vertical grid**: NZ layers with specified thicknesses. Terrain-following coordinate transform maps a flat computational grid to real topography. Bottom layers can be thicker (10-50m for deep aquifer), top layers thin (0.1-1m for root zone).
- **IDOMAIN mask**: Cells outside the basin boundary set to inactive (value 0 in indicator field).
- **Terrain-following grid (TFG)**: ParFlow v3+ supports TFG where grid layers follow surface topography. This is essential for realistic subsurface flow on sloped terrain.

**Inputs**: Basin shapefile, DEM (90m or 30m), desired resolution.
**Outputs**: Domain definition (NX, NY, NZ, dx, dy, dz, origin, CRS), computational mask PFB file.

**Tools needed**:
- `define_parflow_domain.py` — Basin shapefile to ParFlow grid (UTM projection, extent, dimensions)
- `build_domain_mask.py` — Create solid file or indicator field for basin boundary

### S2: Subsurface Properties

**Purpose**: Assign spatially distributed hydraulic properties to each subsurface layer.

**Key parameters** (per grid cell, per layer):
- **Saturated hydraulic conductivity (K)**: Tensor (Kx, Ky, Kz). From GLHYMPS 2.0 (deep) + HWSD pedotransfer (shallow). Units: m/hr (ParFlow default) -- **CRITICAL UNIT: ParFlow uses m/hr, not m/day like MODFLOW**.
- **Porosity**: From GLHYMPS or HWSD. Dimensionless (0-1).
- **van Genuchten alpha**: Inverse of air-entry pressure (1/m). Controls where the saturation-pressure curve transitions. Soil-texture dependent.
- **van Genuchten n**: Shape parameter for the retention curve. Sandy soils n~2-4, clay n~1.1-1.3.
- **Specific storage (Ss)**: Compressibility-related storage (1/m). Typically 1e-4 to 1e-5 for most formations.
- **Relative permeability model**: van Genuchten-Mualem (default) or Brooks-Corey.
- **Manning's n**: For overland flow cells (top layer surface). Varies by land cover: forest 0.15-0.40, cropland 0.03-0.05, urban 0.012-0.015.

**Data sources** (reuse HydroCraft existing):
- HWSD global raster + MDB (shallow soil: 0-2m) via `hwsd_soil_adapter.py`
- GLHYMPS 2.0 (deep subsurface: K, porosity)
- AVHRR land cover (Manning's n lookup)
- SoilGrids 250m (alternative/supplement to HWSD for van Genuchten)
- Rosetta pedotransfer functions (sand/silt/clay to van Genuchten alpha, n)

**Outputs**: PFB files for each property (permeability_x.pfb, permeability_y.pfb, permeability_z.pfb, porosity.pfb, specific_storage.pfb, vangenuchten_alpha.pfb, vangenuchten_n.pfb, mannings.pfb).

**Tools needed**:
- `build_subsurface_properties.py` — HWSD + GLHYMPS + Rosetta to ParFlow property fields
- `build_mannings.py` — AVHRR land cover to Manning's n spatial field
- `write_pfb.py` — Write NumPy arrays to ParFlow Binary format (or use pftools Python API)

### S3: Topography and Slopes

**Purpose**: Process DEM to create slope fields for overland flow routing.

ParFlow overland flow requires x-slope and y-slope fields at every surface cell. These control the direction and speed of surface runoff via the kinematic/diffusive wave equation.

**Processing steps**:
1. Resample DEM to ParFlow grid resolution
2. Fill sinks (critical: unfilled sinks create ponding artifacts)
3. Compute x-direction and y-direction slopes (dz/dx, dz/dy)
4. Apply slope smoothing if needed (noisy slopes cause CFL issues)
5. Set minimum slope (e.g., 0.0001) to prevent zero-velocity ponding

**Inputs**: DEM raster (China 90m or Copernicus 30m), ParFlow grid definition.
**Outputs**: `slope_x.pfb`, `slope_y.pfb`, `elevation.pfb`.

**Tools needed**:
- `build_slopes.py` — DEM to ParFlow slope fields (sink filling + slope computation)
- Reuse WhiteboxTools for DEM processing (already available from basin delineation)

### S4: CLM Land Surface Setup

**Purpose**: Configure CLM 4.5 as the upper boundary condition for energy/water balance.

CLM provides:
- Evapotranspiration (reduces soil moisture in top layers)
- Snow accumulation and melt
- Canopy interception
- Ground heat flux
- Radiation balance

**Key CLM inputs**:
- Land cover / vegetation type map (IGBP classes)
- Leaf area index (LAI) seasonal cycle
- Soil color map
- Optional: irrigation, urban fraction

**CLM files to generate**:
- `drv_clmin.dat` — CLM driver input file (timestep, output control)
- `drv_vegp.dat` — Vegetation parameter file (18 PFTs with LAI, SAI, z0, displacement)
- `drv_vegm.dat` — Vegetation type map (IGBP class per cell)

**Data sources**: AVHRR land cover (already in HydroCraft), MODIS LAI (need to add).

**Tools needed**:
- `build_clm_vegmap.py` — AVHRR/MODIS to CLM vegetation type and parameter files
- `build_clm_driver.py` — Generate drv_clmin.dat with correct timestep and options

### S5: Meteorological Forcing

**Purpose**: Prepare atmospheric forcing data for CLM (when CLM is enabled) or for direct precipitation input (when CLM is disabled).

**CLM forcing variables** (1D forcing file per timestep):
- DSWR: Downward shortwave radiation (W/m^2)
- DLWR: Downward longwave radiation (W/m^2)
- APCP: Precipitation rate (mm/s)
- Tmp: Air temperature (K)
- UGRD: U-component wind (m/s)
- VGRD: V-component wind (m/s)
- Press: Surface pressure (Pa)
- SPFH: Specific humidity (kg/kg)

These are the SAME 8 variables as WRF-Hydro LDASIN, making reuse of CMFD/MSWX pipelines feasible.

**Without CLM**: Only precipitation is needed (applied as a flux boundary condition on the top surface).

**Key differences from VIC/WRF-Hydro forcing**:
- ParFlow CLM reads forcing as **1D distributed fields** in PFB format (not NetCDF like WRF-Hydro, not ASCII per cell like VIC)
- Forcing must be on the **ParFlow grid** (UTM projected), not lat/lon
- Temporal resolution: typically hourly (CLM) or sub-hourly

**Data sources**: CMFD (China), MSWX (global), NASA POWER (online). Same as existing HydroCraft forcing but needs format conversion to PFB on projected grid.

**Tools needed**:
- `convert_forcing_to_pfb.py` — CMFD/MSWX NetCDF to ParFlow CLM forcing PFB files
- Reuse `forcing_1d.py` for initial data extraction, then convert format

### S6: Initial and Boundary Conditions

**Purpose**: Set the initial pressure head field and lateral/bottom boundary conditions.

**Initial conditions**:
- **Pressure head field**: The state variable in Richards equation. Negative = unsaturated (tension), positive = saturated (pressure above atmospheric). Typically initialize from:
  - Constant water table depth (e.g., -5m everywhere, then spin up)
  - Reinecke global water table depth map (already in HydroCraft for MODFLOW)
  - Previous simulation restart file
- **CLM restart**: Soil temperature, moisture, snow depth (if warm-starting CLM)

**Boundary conditions**:
- **Top**: Either CLM fluxes (ET, precip, radiation) or direct precip flux
- **Bottom**: No-flow (impermeable bedrock) is the default and usually correct
- **Lateral**: No-flow at domain boundaries (if basin boundary coincides with domain boundary). For through-flow basins, constant head or flux BC at lateral boundaries.

**Tools needed**:
- `build_initial_pressure.py` — Water table depth map to 3D pressure head field
- `build_boundary_conditions.py` — Set BC types (no-flow, constant head, flux) on domain faces

### S7: Solver Configuration and Run Script

**Purpose**: Configure the ParFlow solver and generate the run script.

**Key solver parameters**:
- **Solver**: `Richards` (for variably saturated) or `Impes` (for fully saturated, simpler)
- **Nonlinear solver**: Newton (default), `MaxIter` (typically 100-500)
- **Linear solver**: PFMG (multigrid from HYPRE), `MaxIter` (typically 50-100)
- **Timestep**: `TimingInfo.BaseUnit` (seconds), `TimingInfo.DumpInterval` (output frequency)
- **CLM coupling**: `Solver.CLM = True`, met forcing file prefix and timing
- **Overland flow**: `OverlandFlowDiffusive` or `OverlandKinematic`
- **Terrain-following grid**: `Solver.TerrainFollowingGrid = True`
- **Convergence**: `Solver.Nonlinear.ResidualTol` (typically 1e-6), `Solver.Linear.Preconditioner` (PFMG or MGSemi)

**Run method**: ParFlow is invoked via TCL script or Python pftools:
```python
from parflow import Run
run = Run("basin_name", __file__)
# ... set all keys ...
run.run(working_directory="./run_dir")
```

Or via command line:
```bash
tclsh run_script.tcl
# or
mpirun -np 4 parflow run_name
```

**Tools needed**:
- `generate_parflow_script.py` — Generate Python pftools run script with all keys configured
- `build_solver_config.py` — Solver parameter selection based on domain size and physics

### S8: Execution

**Purpose**: Run ParFlow, monitor progress, handle errors.

**Execution modes**:
- Serial: `parflow run_name` (for testing, small domains)
- Parallel MPI: `mpirun -np P*Q*R parflow run_name` where P, Q, R are the domain decomposition in x, y, z
- GPU: `mpirun -np N parflow run_name` with CUDA backend compiled

**Expected runtimes** (estimates):
| Domain size | Timestep | Period | Cores | Est. Runtime |
|-------------|----------|--------|-------|-------------|
| 20x20x10 (test) | 1 hr | 1 year | 1 | ~5 min |
| 100x100x15 (small basin) | 1 hr | 1 year | 4 | ~30 min |
| 500x500x20 (medium basin) | 1 hr | 1 year | 16 | ~4-8 hrs |
| 1000x1000x20 (large basin) | 1 hr | 1 year | 32+ | ~1-3 days |

**Output files**: PFB files per timestep for each output variable:
- `run_name.out.press.NNNNN.pfb` — Pressure head (m)
- `run_name.out.satur.NNNNN.pfb` — Saturation (0-1)
- `run_name.out.specific_storage.pfb` — Specific storage
- CLM outputs (if enabled): `run_name.out.clm_output.NNNNN.C.pfb` — CLM diagnostics
- `run_name.out.perm_x.pfb`, `perm_y.pfb`, `perm_z.pfb` — Written once at start

**Monitoring**: Check `run_name.out.kinsol.log` for convergence (nonlinear iterations per timestep). If iterations approach `MaxIter`, the timestep may need reduction.

**Tools needed**:
- `run_parflow.py` — MPI execution wrapper with process monitoring and exit code checking
- `check_convergence.py` — Parse kinsol.log for convergence diagnostics

### S9: Output Processing and Visualization

**Purpose**: Extract hydrological variables from ParFlow PFB output and convert to HydroCraft-standard formats.

**Key derived outputs**:
- **Discharge at outlet**: Sum overland flow velocity * depth at outlet cells. Or compute water balance: P - ET - dS/dt = Q.
- **Water table depth**: For each (x,y) column, find the deepest cell where saturation > 0.99, then depth = surface elevation - cell center elevation.
- **Soil moisture profile**: Saturation * porosity at each depth layer.
- **Evapotranspiration**: From CLM output (latent heat flux / L_v).
- **Overland flow depth**: Pressure head at surface cells where pressure > 0 (ponding depth).
- **Subsurface lateral flow**: Flux between cells (Darcy flux computed from pressure gradient * K).

**Conversion to HydroCraft formats**:
- Discharge timeseries: CSV/txt matching routing output format (date, Q m^3/s)
- Water table depth: NetCDF matching MODFLOW output format
- Soil moisture: NetCDF matching VIC output format
- All spatial fields: GeoTIFF or NetCDF with proper CRS metadata

**Tools needed**:
- `extract_discharge.py` — PFB pressure/saturation to outlet discharge timeseries
- `extract_water_table.py` — PFB saturation to water table depth map
- `extract_soil_moisture.py` — PFB saturation to soil moisture profiles
- `convert_pfb_to_netcdf.py` — Generic PFB to NetCDF converter
- `plot_parflow_results.py` — Visualization (water table map, discharge hydrograph, soil moisture profile)

---

## 4. Tools to Build

### 4.1 Tool Inventory (Estimated 15-20 tools)

| # | Tool ID | Stage | Script Path | Purpose | Est. Lines |
|---|---------|-------|-------------|---------|-----------|
| 1 | `define_parflow_domain` | S1 | `tools/s1_domain/define_parflow_domain.py` | Basin shapefile to ParFlow grid (UTM projection, NX/NY/NZ, origin) | 300 |
| 2 | `build_domain_mask` | S1 | `tools/s1_domain/build_domain_mask.py` | Create indicator field / solid file for basin boundary | 200 |
| 3 | `build_subsurface_properties` | S2 | `tools/s2_subsurface/build_subsurface_properties.py` | HWSD + GLHYMPS + Rosetta pedotransfer to K, porosity, van Genuchten | 500 |
| 4 | `build_mannings` | S2 | `tools/s2_subsurface/build_mannings.py` | AVHRR land cover to Manning's n field | 150 |
| 5 | `build_slopes` | S3 | `tools/s3_topography/build_slopes.py` | DEM to slope_x, slope_y PFB (sink filling + slope computation) | 300 |
| 6 | `build_clm_vegmap` | S4 | `tools/s4_clm/build_clm_vegmap.py` | AVHRR/MODIS to CLM vegetation map and parameter files | 350 |
| 7 | `build_clm_driver` | S4 | `tools/s4_clm/build_clm_driver.py` | Generate drv_clmin.dat with correct timestep and options | 150 |
| 8 | `convert_forcing_to_pfb` | S5 | `tools/s5_forcing/convert_forcing_to_pfb.py` | CMFD/MSWX to ParFlow CLM forcing PFB on projected grid | 500 |
| 9 | `build_initial_pressure` | S6 | `tools/s6_ic_bc/build_initial_pressure.py` | Water table depth to 3D pressure head field | 250 |
| 10 | `build_boundary_conditions` | S6 | `tools/s6_ic_bc/build_boundary_conditions.py` | Configure BC types on domain faces | 200 |
| 11 | `generate_parflow_script` | S7 | `tools/s7_solver/generate_parflow_script.py` | Generate complete pftools Python run script | 400 |
| 12 | `run_parflow` | S8 | `tools/s8_execution/run_parflow.py` | MPI execution wrapper + process monitor | 300 |
| 13 | `check_convergence` | S8 | `tools/s8_execution/check_convergence.py` | Parse kinsol.log for convergence diagnostics | 150 |
| 14 | `extract_discharge` | S9 | `tools/s9_output/extract_discharge.py` | PFB to outlet discharge timeseries | 300 |
| 15 | `extract_water_table` | S9 | `tools/s9_output/extract_water_table.py` | PFB saturation to water table depth | 200 |
| 16 | `extract_soil_moisture` | S9 | `tools/s9_output/extract_soil_moisture.py` | PFB to soil moisture profiles | 200 |
| 17 | `convert_pfb_to_netcdf` | S9 | `tools/s9_output/convert_pfb_to_netcdf.py` | Generic PFB to NetCDF with CRS | 250 |
| 18 | `plot_parflow_results` | S9 | `tools/s9_output/plot_parflow_results.py` | Water table, discharge, soil moisture plots | 350 |
| 19 | `run_parflow_full_pipeline` | all | `tools/run_parflow_full_pipeline.py` | End-to-end wrapper (S0-S9) | 500 |

**Estimated total**: 19 tools, ~5,450 lines of Python code.

### 4.2 Shared Library Code

ParFlow has a Python package (`pftools` / `parflow`) that provides:
- `parflow.Run` — Key-based model configuration
- `parflow.tools.io` — PFB read/write
- `parflow.tools.hydrology` — Water table depth, saturation calculations
- `parflow.tools.fs` — File system utilities

Tools should use `pftools` as the core library rather than reimplementing PFB I/O. This is analogous to using FloPy for MODFLOW.

### 4.3 PFB File Format

ParFlow Binary (PFB) is a custom binary format:
- Header: NX, NY, NZ, x_origin, y_origin, z_origin, dx, dy, dz
- Subgrid headers (one per MPI domain in distributed output)
- Data: 64-bit doubles in column-major order

The `pftools` Python package handles PFB read/write transparently. Tools should use `from parflow.tools.io import read_pfb, write_pfb` rather than implementing binary I/O.

**CRITICAL**: Distributed PFB files (one per MPI rank) must be combined using `pfdist` before post-processing. The Python API handles this automatically if `read_pfb(dist=True)`.

---

## 5. Skill Documents

| # | Stage | Document Path | Covers |
|---|-------|---------------|--------|
| 1 | S1 | `docs/s1_domain_skill.md` | Grid design (resolution, layers, TFG), CRS projection (UTM zone selection), mask creation, terrain-following grid activation |
| 2 | S2 | `docs/s2_subsurface_skill.md` | Van Genuchten parameter selection, Rosetta pedotransfer, K anisotropy (Kz << Kx), unit conversion (m/hr), GLHYMPS logK decoding, Manning's n by land cover |
| 3 | S3 | `docs/s3_topography_skill.md` | Sink filling strategy, slope computation, minimum slope threshold, slope smoothing for stability |
| 4 | S4 | `docs/s4_clm_skill.md` | CLM vegetation types (IGBP), LAI seasonality, CLM timestep alignment, CLM output interpretation |
| 5 | S5 | `docs/s5_forcing_skill.md` | Forcing variable requirements (units!), temporal interpolation, spatial regridding to UTM, CMFD/MSWX to PFB conversion |
| 6 | S6 | `docs/s6_ic_bc_skill.md` | Pressure head initialization (hydrostatic from water table), spinup strategy (10-100 years recommended), lateral BC selection |
| 7 | S7 | `docs/s7_solver_skill.md` | Newton-Krylov settings, PFMG preconditioner, timestep selection, convergence criteria, overland flow diffusive vs kinematic |
| 8 | S8 | `docs/s8_execution_skill.md` | MPI topology (P*Q*R), memory estimation, kinsol.log interpretation, common crashes |
| 9 | S9 | `docs/s9_output_skill.md` | Discharge extraction methods, water table computation, water balance closure check, CRS metadata |
| 10 | -- | `docs/calibration_guide.md` | Key calibration parameters (K, van Genuchten alpha/n, Manning's n, Ds), sensitivity analysis, ParFlow-specific calibration strategies |

**Estimated total**: 10 skill documents, ~15,000 words.

---

## 6. Diagnostic Triplets (Anticipated)

Based on ParFlow documentation, community forums, and analogous errors discovered in MODFLOW/WRF-Hydro dissections.

### 6.1 Unit Conversion Traps (HIGHEST PRIORITY -- silent errors)

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_pf_001 | Permeability appears correct but flow rates are 24x too high/low | ParFlow K units are **m/hr** by default, not m/day (MODFLOW) or m/s (SI). Conversion: K_m_hr = K_m_day / 24 = K_m_s * 3600. | **silent** |
| dt_pf_002 | Precipitation flooding model instantly | CLM precipitation must be in mm/s (= kg/m^2/s). CMFD stores rate correctly but MSWX may need conversion from mm/hr. | **silent** |
| dt_pf_003 | Evapotranspiration unreasonably high/low | Radiation units wrong: CLM expects W/m^2 for DSWR/DLWR, not kJ/m^2/day (WOFOST trap). | **silent** |
| dt_pf_004 | Pressure head values meaningless | Pressure head in meters of water, not Pa or kPa. Conversion: h_m = P_Pa / (rho_w * g). | **silent** |
| dt_pf_005 | Van Genuchten alpha gives wrong retention curve | Alpha units 1/m (ParFlow) vs 1/cm (many soil databases). Factor of 100 difference. | **silent** |

### 6.2 Domain Setup Errors

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_pf_010 | Model crashes with "negative saturation" or NaN | Unfilled DEM sinks create extreme pressure gradients. Must fill sinks before computing slopes. | fatal |
| dt_pf_011 | Overland flow goes in wrong direction | Slope signs inverted (x-slope or y-slope has wrong sign convention). ParFlow expects positive slope in positive coordinate direction. | **silent** |
| dt_pf_012 | Water ponds everywhere, no drainage | All slopes set to zero or below minimum threshold. Set minimum slope ~0.0001 for flat terrain. | degraded |
| dt_pf_013 | CRS mismatch: domain offset from basin | Grid origin in meters (UTM) but coordinates in degrees. Must project consistently. | fatal |
| dt_pf_014 | Terrain-following grid crashes | TFG requires dz values as fractions summing to 1.0 (not absolute thicknesses). Misunderstanding this produces cells with zero or negative volume. | fatal |

### 6.3 Solver/Runtime Errors

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_pf_020 | Nonlinear solver fails to converge (MaxIter reached) | Timestep too large for the physics (sharp wetting front, intense rainfall). Reduce dt or increase MaxIter. | fatal |
| dt_pf_021 | Simulation extremely slow (>100 iterations per timestep) | Poor initial condition far from equilibrium. Need spinup or better IC. | degraded |
| dt_pf_022 | "PFMG: convergence failure" in solver log | HYPRE preconditioner fails on ill-conditioned system. Usually extreme K contrasts (>6 orders of magnitude). Reduce contrast or use different preconditioner. | fatal |
| dt_pf_023 | MPI domain decomposition error (P*Q*R != np) | Number of MPI processes must exactly equal P*Q*R topology. ParFlow does not auto-detect. | fatal |
| dt_pf_024 | Memory exhaustion on large domains | 3D Richards equation stores pressure, saturation, K, porosity, van Genuchten per cell. 500x500x20 = 5M cells * ~200 bytes/cell = ~1 GB minimum. Plus solver workspace. | fatal |

### 6.4 CLM Coupling Errors

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_pf_030 | CLM produces zero ET | Vegetation map all zeros (bare soil). Must set IGBP vegetation types. | **silent** |
| dt_pf_031 | CLM reads wrong forcing timestep | CLM forcing file naming convention mismatch. Files must be named `NLDAS.<run_name>.NNNNN.pfb` with sequential timestep numbers. | fatal |
| dt_pf_032 | Snow never melts / melts too fast | CLM albedo parameters wrong for vegetation type. Verify snow albedo and vegetation albedo in drv_vegp.dat. | degraded |

### 6.5 Output/Post-processing Errors

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_pf_040 | Distributed PFB files unreadable | Output written as distributed (one file per MPI rank). Must combine with `pfdist` or read with `dist=True`. | fatal |
| dt_pf_041 | Water table depth computed wrong | Using pressure head = 0 contour instead of saturation > 0.99 threshold. In coarse grids, the zero-pressure contour may not align with a cell center. | **silent** |
| dt_pf_042 | Discharge at outlet is zero | Outlet cell not on overland flow path. Must identify outlet from slope fields, not from basin shapefile pour point. | degraded |

### 6.6 Coupling Traps (ParFlow <-> HydroCraft)

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_pf_050 | Double-counting surface runoff | If ParFlow handles overland flow, CaMa-Flood routing must NOT also receive VIC surface runoff for the same basin. Only one model routes surface water. | **silent** |
| dt_pf_051 | Spatial mismatch with DSSAT crop grid | ParFlow grid is UTM (meters), DSSAT grid is lat/lon. Area-weighted interpolation needed, not bilinear. | degraded |
| dt_pf_052 | Temporal mismatch with CaMa-Flood | ParFlow outputs hourly, CaMa-Flood expects daily. Must aggregate correctly (mean for flux, instantaneous for state). | **silent** |

**Estimated total**: 25-30 diagnostic triplets across 6 failure domains.

---

## 7. Coupling Points with HydroCraft

### 7.1 Models ParFlow Replaces

When ParFlow is used for a basin, the following models are **not needed** for that basin:
- **VIC** (land surface + vadose zone) -- replaced by ParFlow Richards + CLM
- **MODFLOW 6** (saturated groundwater) -- replaced by ParFlow 3D Richards
- **Lohmann routing** (channel routing) -- partially replaced by ParFlow overland flow
- **CaMa-Flood** (flood routing) -- MAY still be needed for large-scale river routing beyond basin boundaries

### 7.2 Models That Couple WITH ParFlow

| Coupling | Direction | Data Flow | Tool Needed |
|----------|-----------|-----------|-------------|
| **ParFlow -> CaMa-Flood** | Downstream | Overland flow discharge at basin outlet -> CaMa-Flood lateral inflow | `parflow_to_cama.py` |
| **ParFlow -> DSSAT** | Downstream | Soil moisture profile -> DSSAT soil water content | `parflow_to_dssat.py` |
| **ParFlow -> LDNDC** | Downstream | Soil moisture + temperature + water table -> LDNDC soil conditions | `parflow_to_ldndc.py` |
| **ParFlow -> SWAT+** | Downstream | Water table depth + baseflow -> SWAT+ groundwater module override | `parflow_to_swatplus.py` |
| **CMIP6 -> ParFlow** | Upstream | Climate forcing delta-change -> ParFlow CLM forcing | Reuse `climate-projection` skill |
| **OGGM -> ParFlow** | Upstream | Glacier melt -> additional water flux on mountain cells | `oggm_to_parflow.py` |
| **SWMM -> ParFlow** | Bidirectional | Urban drainage <-> subsurface infiltration | `swmm_parflow_coupling.py` |

### 7.3 Coupling Priority

1. **ParFlow standalone** (Phase 1): Run ParFlow with CLM, extract discharge. Compare with VIC+routing.
2. **ParFlow -> CaMa-Flood** (Phase 2): For large river systems where ParFlow handles headwater hydrology and CaMa-Flood routes the main channel.
3. **ParFlow -> DSSAT/LDNDC** (Phase 3): Provide physically-based soil moisture to crop and biogeochemistry models.
4. **ParFlow-CONUS / global datasets** (Phase 4): Leverage community pre-built datasets for rapid setup.

---

## 8. Validation Plan

### 8.1 Validation Basins (Reuse Existing HydroCraft Basins)

| Basin | Area (km^2) | Climate | Existing VIC/MODFLOW? | ParFlow Grid Size | Why |
|-------|------------|---------|----------------------|-------------------|-----|
| **Chaohe** (潮河) | 8,783 | Semi-humid monsoon | VIC+Lohmann done | ~90x90x15 @ 1km | Small, well-characterized, WRF-Hydro comparison available |
| **Heihe Upper** (黑河) | 8,662 | Arid/semi-arid | VIC+CaMa done | ~90x90x20 @ 1km | Arid basin, groundwater-fed oasis, strong GW-SW interaction |
| **Bengbu** (蚌埠/淮河) | 121,330 | Humid subtropical | VIC+CaMa+MODFLOW done | ~350x350x15 @ 1km | Large basin, flood-prone, VIC+WRF-Hydro comparison |
| **Koksilah** | 229 | Maritime temperate | VIC+CaMa done (MSWX) | ~15x15x15 @ 1km | Very small, tests boundary handling |

### 8.2 Validation Metrics

- **Discharge**: NSE, PBIAS, KGE vs observed (GRDC/HYDAT) and vs VIC simulation
- **Water table**: Mean depth vs Reinecke global WTD and vs MODFLOW simulation
- **Soil moisture**: Profile comparison with CLM output vs VIC soil moisture layers
- **Water balance closure**: P - ET - Q - dS/dt should be < 1% of P

### 8.3 Validation Sequence

1. **Box test** (day 1): 10x10x10 box, uniform properties, known analytical solution (Toth problem). Verify ParFlow installation and basic functionality.
2. **Hillslope test** (day 2): 2D hillslope with known water table shape. Verify overland flow + subsurface coupling.
3. **Chaohe 1-year** (week 1): Full basin, 1km resolution, 2005. Compare discharge with VIC.
4. **Chaohe 10-year** (week 2): Extended period with spinup. Calibrate K and van Genuchten.
5. **Bengbu 1-year** (week 3): Large basin test. Performance and scaling assessment.

---

## 9. Estimated Effort

| Phase | Dissection Activity | Est. Time |
|-------|-------------------|-----------|
| **Phase 0** | Installation + compilation + test suite | 1-2 days |
| **Phase 1** | Pipeline mapping (10 stages) | 0.5 day |
| **Phase 2** | Knowledge classification | 0.5 day |
| **Phase 3** | Tool extraction (19 tools, ~5,450 lines) | 5-7 days |
| **Phase 4** | Skill document writing (10 docs, ~15,000 words) | 3-4 days |
| **Phase 5** | Diagnostic triplet construction (25-30 triplets) | 2-3 days |
| **Phase 6** | Assembly + end-to-end validation | 3-5 days |
| **Validation** | 4 basins (box + hillslope + Chaohe + Bengbu) | 5-7 days |
| **Coupling** | ParFlow <-> CaMa-Flood + DSSAT coupling tools | 3-4 days |
| **Total** | | **~24-33 days** |

---

## 10. Priority and Dependencies

### 10.1 Priority: HIGH

ParFlow fills a genuine physics gap that no current combination of HydroCraft models addresses:
- **Variably saturated flow**: Neither VIC (bucket) nor MODFLOW (saturated only) handles the vadose zone physics correctly
- **Lateral subsurface flow**: Critical for hillslope hydrology, perched water tables, springs
- **Integrated GW-SW**: Eliminates the artificial coupling lag between VIC and MODFLOW
- **Performance**: GPU + MPI for large-scale simulations (future CONUS-scale runs)

### 10.2 Dependencies (What Must Exist Before ParFlow Dissection)

| Dependency | Status | Notes |
|-----------|--------|-------|
| HWSD global raster + MDB | Available | Shared soil source for van Genuchten params |
| GLHYMPS 2.0 | Available | Deep subsurface K and porosity |
| Reinecke water table depth | Available | Initial conditions |
| China DEM 90m | Available | Topography and slopes |
| Copernicus GLO-30 | Available (auto-download) | Non-China basins |
| CMFD/MSWX forcing | Available | Meteorological forcing (needs format conversion) |
| AVHRR land cover | Available | CLM vegetation types + Manning's n |
| pftools Python package | Not installed | `pip install pftools` |
| HYPRE | Not installed | Must compile from source |
| ParFlow binary | Not installed | Must compile from source |

### 10.3 Relationship to Existing Models

```
                    ┌─────────────────────────────┐
                    │       ParFlow               │
                    │  (3D Richards + CLM +        │
                    │   overland flow)             │
                    │                             │
                    │  REPLACES:                  │
                    │   - VIC (land surface)       │
                    │   - MODFLOW (groundwater)    │
                    │   - Lohmann (routing)        │
                    │                             │
                    │  COUPLES WITH:              │
                    │   - CaMa-Flood (downstream) │
                    │   - DSSAT (crop soil water)  │
                    │   - LDNDC (biogeochemistry)  │
                    │   - OGGM (glacier melt)      │
                    │   - SWMM (urban drainage)    │
                    └─────────────────────────────┘
```

### 10.4 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| HYPRE compilation fails | Medium | Blocks entire model | Use Docker fallback, or Spack package manager |
| ParFlow too slow without GPU | Low | Limits domain size | MPI parallelism sufficient for basin-scale; GPU for CONUS-scale |
| van Genuchten parameterization inaccurate | High | Poor soil moisture dynamics | Use Rosetta v3 pedotransfer (well-validated), calibrate alpha/n |
| Spinup takes too long (100+ years) | Medium | Delays production runs | Use warm start from MODFLOW water table + VIC soil moisture |
| PFB format unfamiliar to agents | Medium | Post-processing errors | Build robust `convert_pfb_to_netcdf.py` early; all downstream tools use NetCDF |
| CLM version mismatch | Low | Wrong surface fluxes | ParFlow bundles its own CLM; do not mix with standalone CLM builds |

### 10.5 Recommended Dissection Order

1. **Install ParFlow** (Phase 0) -- get a working binary on this server
2. **Run test cases** (Phase 0) -- verify installation with included tests
3. **S1 Domain + S3 Slopes + S9 Output** -- establish the I/O pipeline first
4. **S2 Subsurface** -- the most complex stage (van Genuchten parameterization)
5. **S5 Forcing** -- leverage existing CMFD/MSWX pipelines
6. **S7 Solver + S8 Execution** -- get a minimal running simulation
7. **S4 CLM + S6 IC/BC** -- add CLM coupling and proper initialization
8. **Validation on Chaohe** -- first real basin test
9. **Coupling tools** -- ParFlow <-> CaMa-Flood, DSSAT, LDNDC
10. **Calibration guide** -- document K, alpha, n, Manning's n calibration

---

## 11. File Structure (Target)

```
models/ParFlow/
├── knowledge_infrastructure/
│   ├── DISSECTION_PLAN.md          # This file
│   ├── SKILL.md                     # Agent entry point (Phase 6)
│   ├── knowledge_infrastructure.yaml # Schema-compliant package definition
│   ├── workflow/
│   │   ├── pipeline.drawio          # Visual pipeline diagram
│   │   └── workflow.md              # Agent-readable workflow
│   ├── tools/
│   │   ├── s1_domain/
│   │   │   ├── define_parflow_domain.py
│   │   │   └── build_domain_mask.py
│   │   ├── s2_subsurface/
│   │   │   ├── build_subsurface_properties.py
│   │   │   └── build_mannings.py
│   │   ├── s3_topography/
│   │   │   └── build_slopes.py
│   │   ├── s4_clm/
│   │   │   ├── build_clm_vegmap.py
│   │   │   └── build_clm_driver.py
│   │   ├── s5_forcing/
│   │   │   └── convert_forcing_to_pfb.py
│   │   ├── s6_ic_bc/
│   │   │   ├── build_initial_pressure.py
│   │   │   └── build_boundary_conditions.py
│   │   ├── s7_solver/
│   │   │   └── generate_parflow_script.py
│   │   ├── s8_execution/
│   │   │   ├── run_parflow.py
│   │   │   └── check_convergence.py
│   │   ├── s9_output/
│   │   │   ├── extract_discharge.py
│   │   │   ├── extract_water_table.py
│   │   │   ├── extract_soil_moisture.py
│   │   │   ├── convert_pfb_to_netcdf.py
│   │   │   └── plot_parflow_results.py
│   │   └── run_parflow_full_pipeline.py
│   ├── docs/
│   │   ├── s1_domain_skill.md
│   │   ├── s2_subsurface_skill.md
│   │   ├── s3_topography_skill.md
│   │   ├── s4_clm_skill.md
│   │   ├── s5_forcing_skill.md
│   │   ├── s6_ic_bc_skill.md
│   │   ├── s7_solver_skill.md
│   │   ├── s8_execution_skill.md
│   │   ├── s9_output_skill.md
│   │   ├── calibration_guide.md
│   │   └── model_couplings.yaml
│   └── diagnostics/
│       ├── triplets.yaml
│       ├── error_log.yaml
│       └── episodes.yaml
└── (model binary installed separately in model/parflow/)
```

---

## 12. ParFlow vs. Existing HydroCraft Models -- Decision Guide

**When to use ParFlow instead of VIC + MODFLOW:**

| Criterion | Use ParFlow | Use VIC + MODFLOW |
|-----------|-------------|-------------------|
| **GW-SW interaction** is the research question | Yes | No (coupling lag) |
| **Lateral subsurface flow** matters (hillslope, springs) | Yes | No (VIC is 1D) |
| **Water table dynamics** drive surface hydrology | Yes | Maybe (manual coupling) |
| Basin is **small-medium** (<50,000 km^2) | Yes (feasible grid size) | Either |
| Basin is **very large** (>100,000 km^2) | Only with HPC/GPU | Yes (faster) |
| Need **quick uncalibrated estimate** | No (setup is more complex) | Yes (VIC is simpler) |
| Need to couple with **CaMa-Flood for downstream flood routing** | Yes (ParFlow handles headwater, CaMa handles main channel) | Yes (existing workflow) |
| **GPU available** for acceleration | Yes (major advantage) | No (both serial) |
| **Community datasets** available (ParFlow-CONUS) | Yes (US continental) | Yes (global) |

---

## 13. Global Datasets and Community Resources

### 13.1 ParFlow-CONUS

The ParFlow community maintains a continental US (CONUS) domain setup at 1km resolution:
- **ParFlow-CONUS 2.0**: Pre-built subsurface properties, topography, CLM parameters for the entire CONUS
- **Source**: https://hydroframe.org/parflow-conus2
- **Resolution**: 1 km x 1 km, ~3,342 x 1,888 cells, 5 subsurface layers
- **Data**: SoilGrids-derived van Genuchten parameters, NWM-derived Manning's n, MERIT DEM slopes
- **Limitation**: US only. For HydroCraft (primarily China + global), we need our own setup pipeline using HWSD/GLHYMPS/China DEM.

### 13.2 SoilGrids 250m

- Global soil property maps at 250m resolution (sand/silt/clay/SOC by depth)
- Can supplement HWSD for van Genuchten parameterization via Rosetta pedotransfer
- Download: https://soilgrids.org/

### 13.3 MERIT DEM

- Global DEM at 3 arcsec (~90m), hydrologically conditioned (sinks removed)
- Better than raw SRTM/Copernicus for slope computation (fewer sinks to fill)
- Partially overlaps with China DEM 90m already in HydroCraft

### 13.4 HydroFrame / PFGIS-Tool

- Web-based tool for extracting ParFlow subsets from CONUS domain
- Not directly useful for China basins, but useful reference for pipeline design

---

## 14. Open Questions (To Resolve During Dissection)

1. **pftools Python API stability**: Is the Python API mature enough to replace TCL for all setup tasks? Some ParFlow examples still use TCL. Need to verify Python API coverage.

2. **CLM version**: ParFlow bundles CLM 4.5. Is this compatible with the vegetation data and forcing pipelines already in HydroCraft? Or does it need its own vegetation parameter files?

3. **Terrain-following grid dz specification**: Documentation suggests dz values are fractions of total depth when TFG is enabled. Need to verify: absolute thickness vs fraction, and how to map real soil layers to TFG layers.

4. **Output variable naming**: What exactly is in the CLM output PFB files? Need to map CLM output variables to VIC-equivalent variables for comparison.

5. **Spinup strategy**: ParFlow community recommends 10-100 year spinup to reach water table equilibrium. Can we shortcut this using MODFLOW steady-state results as initial conditions?

6. **MPI topology constraints**: P, Q, R must divide NX, NY, NZ exactly. This constrains grid dimensions. Need to handle this in domain setup tool.

7. **Discharge extraction**: ParFlow does not have a built-in "outlet discharge" variable like WRF-Hydro CHRTOUT. How to robustly extract discharge at a specified outlet from pressure/velocity fields?

---

*This dissection plan was prepared using the Knowledge Dissection Toolkit v1.0 methodology (Jianyun Zhang Research Group, Hohai University). No installation or building was performed -- this is a research and planning document only.*
