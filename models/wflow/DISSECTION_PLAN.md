# wflow (Deltares) — Knowledge Dissection Plan

**Package**: `hydrocraft-wflow` (planned)
**Model**: wflow v1.0.2 (Wflow.jl — Julia-based distributed hydrological model)
**Sub-models**: wflow_sbm (hydrology), wflow_sediment (erosion & transport)
**Author**: Deltares (van Verseveld et al., 2024, GMD 17, 3199-3234)
**Plan created**: 2026-03-21
**Created by**: Jianyun Zhang Research Group, Hohai University

---

## 1. Model Overview

### What is wflow?

wflow is Deltares' open-source distributed hydrological modelling framework, written in Julia. It simulates the complete terrestrial water cycle through interconnected process modules: precipitation, interception, snow/glacier melt, evapotranspiration, soil water dynamics, surface/subsurface routing, and groundwater recharge. Unlike VIC (energy/water balance on regular lat/lon grids), wflow uses a topography-driven approach on any regular grid with multiple routing options.

**License**: MIT (since 2021)
**Language**: Julia (~88%), with ~12% RTF documentation
**Latest release**: v1.0.2 (2025-03-05), 28 releases total, 1,369 commits
**Repository**: https://github.com/Deltares/Wflow.jl
**Paper**: van Verseveld et al. (2024), "Wflow_sbm v0.7.3, a spatially distributed hydrological model", GMD

### Two Model Configurations

#### wflow_sbm (hydrology)

The Soil Budget Model (SBM) vertical concept simulates the complete water balance:

| Process | Method | Key Parameters |
|---------|--------|----------------|
| **Interception** | Gash (daily) / simplified Rutter (sub-daily) | canopy storage capacity, LAI |
| **Snow** | HBV-style degree-day | degree-day factor, temperature threshold |
| **Glacier** | Degree-day melt (optional) | degree-day factor, glacier fraction |
| **Infiltration** | Brooks-Corey / Green-Ampt style | KsatVer, InfiltCapSoil, PathFrac |
| **Soil water** | Multi-layer unsaturated/saturated | SoilThickness, theta_s, theta_r, f (exponential Ksat decay) |
| **Capillary rise** | Texture-dependent lookup | water table depth, soil texture |
| **ET** | Penman-Monteith or De Bruin | LAI, root depth, stomatal resistance |
| **Subsurface flow** | Exponential Ksat profile lateral flow | KsatHorFrac, slope |

Four routing configurations:
1. **SBM + Kinematic Wave** (default) — D8 network routing, Manning's equation
2. **SBM + Kinematic Wave (land) + Local Inertial (river)** — with optional 1D floodplain
3. **SBM + Local Inertial (1D river & 2D land)** — shallow water equations, flood inundation
4. **SBM + Groundwater Flow (sbm_gwf)** — unconfined aquifer with 4-directional GW flow

#### wflow_sediment (erosion & transport)

Operates as a **post-processor** using wflow_sbm hydrological outputs. Two components:

**Land erosion:**
- **Splash erosion**: EUROSEM (physics-based kinetic energy) or ANSWERS (USLE-based empirical)
- **Overland flow erosion**: ANSWERS methodology with USLE C and K factors
- **Parameters**: USLE C factor (land use), USLE K factor (soil erodibility from texture)

**River sediment transport** (5 capacity formulas):
- Simplified Bagnold
- Engelund-Hansen (total load, used in Delft3D-WAQ)
- Kodatie (power relationships by D50 class)
- Yang (sand-bed and gravel-bed)
- Molinas-Wu (large sand-bed rivers)

**Grain size classes**: clay (2 um), silt (10 um), sand (200 um), small aggregates (30 um), large aggregates (50 um)

**Deposition**: Einstein's equation based on settling velocity (Stokes formula)

### Why wflow for HydroCraft?

| Gap Filled | Details |
|------------|---------|
| **Sediment/erosion** | HydroCraft has no sediment transport model. wflow_sediment fills this gap with USLE-based erosion + 5 river transport formulas. |
| **Alternative hydrology** | Modern Julia-based model vs VIC (C) and WRF-Hydro (Fortran). Different soil physics (SBM vs VIC energy balance) for model comparison. |
| **Built-in flood routing** | Local inertial routing (1D+2D) provides flood inundation without needing CaMa-Flood. |
| **HydroMT automation** | The HydroMT-wflow plugin automates model building from global datasets — closest to HydroCraft's "zero manual data prep" philosophy. |
| **Water demand/allocation** | Built-in irrigation, domestic demand, and allocation modules. |
| **Reservoir operations** | Native reservoir and lake modules with simple control rules. |

### Comparison with VIC

| Feature | VIC 5.1.0 | wflow v1.0.2 |
|---------|-----------|--------------|
| Language | C | Julia |
| Grid | Regular lat/lon | Regular grid (any CRS) |
| Soil concept | 3-layer energy/water balance | Multi-layer SBM (bucket + exponential Ksat) |
| Snow | Energy balance | Degree-day (HBV-style) |
| Glacier | None (needs OGGM coupling) | Built-in degree-day glacier module |
| Routing | External (Lohmann/CaMa-Flood) | Built-in (kinematic wave / local inertial) |
| Flood inundation | Needs CaMa-Flood | Local inertial 1D+2D (native) |
| Sediment | None | wflow_sediment (USLE + 5 transport formulas) |
| Config format | Flat text (global_param) | TOML (structured, typed) |
| I/O format | ASCII per cell (forcing), flat binary (output) | NetCDF (forcing + output) |
| Setup automation | HydroCraft tools (18 scripts) | HydroMT-wflow plugin (one command) |
| Parallelism | Serial | Multi-threaded (Julia native) |
| Water demand | None | Built-in allocation module |
| Calibration | External (vic_cali_ai) | External (typically PEST/Optuna) |
| HydroCraft status | **Validated** (7+ basins, NSE=0.90) | **Planned** |

---

## 2. Installation Plan

### The Julia Challenge

wflow is written in Julia, which is a different ecosystem from HydroCraft's Python/C/Fortran stack. Three installation strategies, in order of preference:

#### Strategy A: Julia Package Manager (RECOMMENDED)

```bash
# 1. Install Julia (latest stable, currently 1.11.x)
curl -fsSL https://install.julialang.org | sh
# or download from https://julialang.org/downloads/

# 2. Install Wflow package
julia -e 'using Pkg; Pkg.add("Wflow")'

# 3. Verify
julia -e 'using Wflow; println("Wflow loaded successfully")'
```

**Pros**: Clean dependency management, easy updates, multi-threaded by default
**Cons**: Requires Julia runtime (~500 MB), first-run compilation is slow (5-10 min for precompilation), Julia ecosystem unfamiliar to team

**How HydroCraft calls it**: Subprocess from Python:
```python
import subprocess
result = subprocess.run(
    ["julia", "--project=/path/to/wflow_env", "-e",
     'using Wflow; Wflow.run(toml_path="config.toml")'],
    capture_output=True, text=True
)
```

Or via the `wflow_cli` entry point (if built):
```python
subprocess.run(["julia", "--project=.", "wflow_cli.jl", "config.toml"])
```

#### Strategy B: Pre-compiled Binary (wflow_cli)

Deltares distributes compiled binaries via download.deltares.nl, but **currently Windows only (.msi)**. No official Linux binary.

**Options for Linux binary**:
1. Use Julia's `PackageCompiler.jl` to create a standalone Linux executable:
   ```julia
   using PackageCompiler
   create_app("Wflow", "wflow_app"; executables=["wflow_cli" => "main"])
   ```
2. Check if Deltares releases Linux binaries in future versions
3. Use the Dockerfile in the repository to build a container

**Pros**: No Julia runtime dependency at execution time
**Cons**: Requires Julia for compilation, binary is large (~200-500 MB), harder to update

#### Strategy C: Docker Container

The Wflow.jl repository includes a `Dockerfile`.

```bash
docker build -t wflow:1.0.2 .
docker run -v /data:/data wflow:1.0.2 /data/config.toml
```

**Pros**: Fully isolated, reproducible
**Cons**: Docker overhead, harder to debug, volume mounting for large datasets

#### Recommendation

**Use Strategy A** (Julia package manager) for initial development and validation. Julia's subprocess call from Python is clean and well-tested. The first-run compilation penalty (5-10 min) only occurs once per Julia session. For production deployment, consider Strategy B (PackageCompiler) to eliminate the Julia dependency.

### HydroMT-wflow (Python, for model setup)

HydroMT-wflow is a Python package that automates wflow model building. This integrates cleanly with HydroCraft's Python environment.

```bash
pip install hydromt_wflow
# or
conda install -c conda-forge hydromt_wflow
```

**Dependencies**: hydromt (core), xarray, rioxarray, geopandas, netCDF4, pyflwdir

**What it does**: Takes a basin region + global datasets and produces:
- `staticmaps.nc` — all spatial parameters (DEM, soil, land use, river network, LAI)
- `forcing.nc` (or `inmaps.nc`) — meteorological forcing (P, T, PET)
- `wflow_sbm.toml` — complete configuration file
- `instates.nc` — initial conditions (optional)

### Installation Path Plan

```
model/wflow/
  julia_env/           # Julia project environment (Project.toml, Manifest.toml)
  wflow_cli            # Compiled binary (Strategy B, optional)
  Dockerfile           # Container build (Strategy C, optional)
```

### HydroMT Data Catalogs

HydroMT-wflow can use these global datasets (many already in HydroCraft):

| Dataset | HydroMT Name | HydroCraft Equivalent | Resolution | Action |
|---------|-------------|----------------------|-----------|--------|
| MERIT Hydro DEM | `merit_hydro` | China DEM 90m / Copernicus GLO-30 | 3 arcsec | Download or use existing |
| SoilGrids 2.0 | `soilgrids` | HWSD (already available) | 250m | Download or map from HWSD |
| GlobCover / ESA WorldCover | `globcover` / `esa_worldcover` | AVHRR 1km (already available) | 300m/10m | Download |
| ERA5 | `era5` | CMFD / MSWX (already available) | 0.25 deg | Use existing forcing pipeline |
| GRanD reservoirs | `grand` | Not available | Point | Download |
| RGI glaciers | `rgi` | OGGM uses this | Polygon | Already available |

**Key decision**: Use HydroMT's data catalogs vs HydroCraft's existing datasets. Recommendation: **build a custom HydroMT data catalog** that points to HydroCraft's existing datasets (HWSD, AVHRR, CMFD/MSWX) to avoid downloading duplicates.

---

## 3. Pipeline Stages

### Stage Overview

```
s0_config          Configuration & paths
    |
s1_hydromt_setup   HydroMT model building (DEM, soil, land use, rivers)
    |
s2_forcing         Forcing data preparation (P, T, PET from CMFD/MSWX)
    |
s3_parameters      Parameter adjustment & calibration setup
    |
s4_execution       wflow_sbm execution (Julia subprocess)
    |
s5_postprocess     Output extraction & visualization
    |
s6_sediment_setup  wflow_sediment model building (if sediment requested)
    |
s7_sediment_run    wflow_sediment execution
    |
s8_sediment_post   Sediment output analysis & visualization
    |
s9_coupling        Coupling with CaMa-Flood / SWAT+ / MODFLOW / VIC comparison
```

### Detailed Stage Descriptions

#### s0_config — Configuration & Paths

**Purpose**: Set basin, period, resolution, and model variant.

**Inputs**: Basin name, lat/lon or shapefile, start/end year, resolution, forcing dataset choice

**Outputs**: `wflow_config.yaml` (HydroCraft-style config, NOT the wflow TOML — that is generated by HydroMT)

**Key decisions**:
- Routing method: kinematic wave (fast, default) vs local inertial (flood inundation)
- Sediment: yes/no
- Glacier module: yes/no (for mountain basins)
- Water demand/allocation: yes/no

#### s1_hydromt_setup — HydroMT Model Building

**Purpose**: Use HydroMT-wflow to build the complete static model from global datasets.

**Tool**: `hydromt build wflow` (CLI) or Python API

**CLI example**:
```bash
hydromt build wflow /path/to/model_root \
  -r "{'basin': [outlet_x, outlet_y]}" \
  -i wflow_sbm_build.yml \
  -d data_catalog.yml \
  --opt setup_config.starttime=2000-01-01T00:00:00 \
  --opt setup_config.endtime=2010-12-31T00:00:00
```

**HydroMT build configuration** (`wflow_sbm_build.yml`) specifies which setup methods to call:
```yaml
setup_basemaps:
  hydrography_fn: merit_hydro
  basin_index_fn: merit_hydro_index
  res: 0.008333  # ~1km
setup_rivers:
  hydrography_fn: merit_hydro
  river_geom_fn: rivers_lin2019_v1
  river_upa: 30  # min upstream area km2
setup_soilmaps:
  soil_fn: soilgrids
  usda_soil_fn: soilgrids_usda
setup_lulcmaps:
  lulc_fn: globcover
setup_laimaps:
  lai_fn: modis_lai
setup_glaciers:
  glaciers_fn: rgi
setup_reservoirs_simple_control:
  reservoirs_fn: grand
setup_precip_forcing:
  precip_fn: era5
setup_temp_pet_forcing:
  temp_pet_fn: era5
  press_correction: true
  dem_forcing_fn: era5_orography
setup_cold_states: {}
setup_outlets: {}
setup_gauges:
  gauges_fn: grdc
```

**Outputs**:
- `staticmaps.nc` — all spatial parameters
- `wflow_sbm.toml` — model configuration
- `inmaps.nc` or `forcing.nc` — forcing data (if ERA5 used)
- `instates.nc` — initial conditions
- `geoms/` — GeoJSON geometries (basin, rivers, gauges)

**Critical considerations**:
- HydroMT downloads datasets on first use. Pre-download or use custom catalog pointing to HydroCraft data.
- Resolution must match forcing resolution for optimal results.
- For China basins, a custom data catalog is essential (CMFD instead of ERA5, HWSD instead of SoilGrids).

#### s2_forcing — Forcing Data Preparation

**Purpose**: Prepare meteorological forcing in wflow NetCDF format.

wflow requires 3 forcing variables (minimum):
| Variable | CSDMS Standard Name | Unit | Source |
|----------|-------------------|------|--------|
| Precipitation | `atmosphere_water__precipitation_volume_flux` | mm/timestep | CMFD / MSWX |
| Temperature | `atmosphere_air__temperature` | deg C | CMFD / MSWX |
| Potential ET | `land_surface_water__potential_evaporation_volume_flux` | mm/timestep | Calculated from T, radiation, wind |

**Two pathways**:
1. **HydroMT built-in**: `setup_precip_forcing()` + `setup_temp_pet_forcing()` — uses ERA5 by default
2. **Custom tool** (for CMFD/MSWX): Convert HydroCraft forcing to wflow NetCDF format

The custom tool is essential for HydroCraft integration because:
- CMFD/MSWX are already downloaded and cached
- ERA5 download via HydroMT is slow and requires CDS API key
- PET calculation from CMFD/MSWX variables ensures consistency with VIC runs

**Output**: `forcing.nc` with dimensions (time, y, x) and variables P, T, PET

**Key unit traps**:
- wflow expects precipitation per timestep (mm), not rate (mm/s or mm/hr)
- Temperature in degrees Celsius, not Kelvin
- PET per timestep, not daily rate

#### s3_parameters — Parameter Configuration

**Purpose**: Adjust wflow parameters for calibration or regional tuning.

wflow parameters can be modified in the TOML file using scale/offset:
```toml
[input.static.land.soil.vertical_hydraulic_conductivity]
netcdf_variable_name = "KsatVer"
scale = 1.5    # multiply all values by 1.5
offset = 0.0
```

**Key calibration parameters**:

| Parameter | TOML Path | Unit | Typical Range | Sensitivity |
|-----------|-----------|------|--------------|-------------|
| KsatVer | vertical hydraulic conductivity | mm/day | 10-10000 | High (infiltration) |
| f | exponential Ksat decay | 1/mm | 0.0005-0.005 | High (baseflow) |
| SoilThickness | total soil depth | mm | 500-5000 | High (storage) |
| RootingDepth | root zone depth | mm | 100-2000 | Medium (ET partitioning) |
| PathFrac | impervious fraction | - | 0.0-0.3 | Medium (direct runoff) |
| N_River | Manning's n (river) | s/m^(1/3) | 0.02-0.1 | Medium (routing timing) |
| InfiltCapSoil | infiltration capacity | mm/day | 50-500 | Medium (surface runoff) |

#### s4_execution — wflow_sbm Execution

**Purpose**: Run the wflow_sbm model.

**Command**:
```bash
julia --project=/path/to/julia_env -e '
    using Wflow
    Wflow.run(toml_path="/path/to/wflow_sbm.toml")
'
```

Or with multi-threading:
```bash
julia --project=/path/to/julia_env --threads=auto -e '
    using Wflow
    Wflow.run(toml_path="/path/to/wflow_sbm.toml")
'
```

**Expected runtime**: 1-30 min depending on domain size and period (Julia is fast once compiled)

**First-run penalty**: Julia's JIT compilation means the first run takes 5-10 minutes extra. Subsequent runs in the same Julia session are fast. Consider using `PackageCompiler.jl` sysimage for faster startup.

**Outputs** (configured in TOML):
- `output_grid.nc` — gridded output (Q, ET, soil moisture, snow, etc.)
- `output_scalar.nc` — point/gauge output (discharge at gauges)
- `output.csv` — tabular output at specified locations
- `outstates.nc` — final state for warm-start continuation

#### s5_postprocess — Output Extraction & Visualization

**Purpose**: Extract discharge, spatial fields, and generate plots.

**Key outputs to extract**:
- Discharge at outlet/gauge points (from `output_scalar.nc`)
- Spatial runoff, ET, soil moisture maps (from `output_grid.nc`)
- Snow cover and depth (if snow module enabled)
- Glacier melt contribution (if glacier module enabled)

**Visualization** (using HydroCraft `skills/plot/` scripts):
- Discharge comparison with observed data
- Spatial maps of annual ET, runoff, soil moisture
- Snow cover duration maps
- Water balance closure check

#### s6_sediment_setup — wflow_sediment Model Building

**Purpose**: Build wflow_sediment model using wflow_sbm outputs.

**HydroMT command**:
```bash
hydromt build wflow_sediment /path/to/sediment_model \
  -r "{'basin': [outlet_x, outlet_y]}" \
  -i wflow_sediment_build.yml \
  -d data_catalog.yml
```

**Setup methods**:
```yaml
setup_basemaps:
  hydrography_fn: merit_hydro
setup_rivers:
  hydrography_fn: merit_hydro
setup_lulcmaps:
  lulc_fn: globcover
setup_canopymaps:
  canopy_fn: simard2011
setup_soilmaps:
  soil_fn: soilgrids
setup_riverbedsed:
  bed_sediment_fn: riverbed_d50
setup_outlets: {}
```

**Additional data needs**:
- USLE C factor map (derived from land use)
- USLE K factor map (derived from soil texture: clay, silt, sand fractions)
- Canopy height map (for EUROSEM splash erosion)
- Riverbed sediment D50 (for transport capacity)

#### s7_sediment_run — wflow_sediment Execution

**Purpose**: Run sediment model using wflow_sbm hydrology outputs.

```bash
julia --project=/path/to/julia_env -e '
    using Wflow
    Wflow.run(toml_path="/path/to/wflow_sediment.toml")
'
```

**Outputs**:
- Soil loss per cell (tonnes/ha/yr)
- Sediment yield to rivers per cell
- In-stream sediment concentration by grain size class
- Deposition/erosion patterns along river network

#### s8_sediment_post — Sediment Output Analysis

**Purpose**: Analyze and visualize sediment results.

**Key analyses**:
- Spatial erosion hotspot map
- Sediment yield at outlet (tonnes/yr)
- Grain size distribution of transported sediment
- Comparison with USLE predictions
- Sediment rating curve (Q vs sediment load)

#### s9_coupling — Cross-Model Integration

**Purpose**: Connect wflow outputs with other HydroCraft models.

**Coupling points** (see Section 8 for details):
- wflow discharge vs VIC discharge (model intercomparison)
- wflow runoff -> CaMa-Flood (alternative to VIC as runoff source)
- wflow sediment -> SWAT+ water quality (sediment loading)
- wflow local inertial -> SFINCS (urban flood downscaling)
- wflow GW recharge -> MODFLOW (recharge boundary condition)

---

## 4. Tools to Build

### Estimated: 15-20 tools, ~4,000-6,000 lines

| ID | Tool Name | Stage | Purpose | Est. Lines |
|----|-----------|-------|---------|-----------|
| t01 | `setup_wflow_config.py` | s0 | Generate HydroCraft-style config from user inputs | 200 |
| t02 | `build_data_catalog.py` | s1 | Create HydroMT data catalog pointing to HydroCraft datasets | 350 |
| t03 | `run_hydromt_build.py` | s1 | Wrapper for `hydromt build wflow` with HydroCraft conventions | 400 |
| t04 | `convert_forcing_to_wflow.py` | s2 | Convert CMFD/MSWX forcing to wflow NetCDF format (P, T, PET) | 500 |
| t05 | `calculate_pet.py` | s2 | Calculate PET from CMFD/MSWX variables (Penman-Monteith or Hargreaves) | 300 |
| t06 | `adjust_parameters.py` | s3 | Modify wflow TOML parameters (scale/offset for calibration) | 250 |
| t07 | `run_wflow.py` | s4 | Execute wflow via Julia subprocess with progress monitoring | 350 |
| t08 | `extract_discharge.py` | s5 | Extract discharge timeseries from wflow NetCDF output | 250 |
| t09 | `extract_spatial_output.py` | s5 | Extract gridded fields (runoff, ET, SM) for visualization | 300 |
| t10 | `compare_with_vic.py` | s5/s9 | Compare wflow vs VIC discharge and water balance | 400 |
| t11 | `build_sediment_model.py` | s6 | Wrapper for `hydromt build wflow_sediment` | 350 |
| t12 | `run_wflow_sediment.py` | s7 | Execute wflow_sediment via Julia subprocess | 250 |
| t13 | `analyze_sediment.py` | s8 | Sediment yield analysis and visualization | 400 |
| t14 | `wflow_to_cama.py` | s9 | Convert wflow runoff output to CaMa-Flood input format | 350 |
| t15 | `wflow_recharge_to_modflow.py` | s9 | Extract GW recharge for MODFLOW boundary conditions | 250 |
| t16 | `run_wflow_full_pipeline.py` | all | End-to-end pipeline wrapper (stages s0-s5) | 500 |

**Total estimated**: 16 tools, ~5,400 lines

### Julia Interface Layer

A critical design decision: how Python tools call Julia/wflow.

**Recommended approach**: A thin Julia wrapper script (`wflow_runner.jl`) that:
1. Accepts TOML path as argument
2. Runs `Wflow.run()`
3. Captures stdout/stderr
4. Returns exit code

Python tools call this via `subprocess.run()`:
```python
result = subprocess.run(
    ["julia", "--project=/path/to/julia_env", "--threads=auto",
     "/path/to/wflow_runner.jl", toml_path],
    capture_output=True, text=True, timeout=7200
)
```

**Alternative**: Use `PyJulia` or `juliacall` for direct Python-Julia interop. This avoids subprocess overhead but adds dependency complexity. Not recommended for initial implementation.

---

## 5. Skill Documents

### Estimated: 8 skill documents

| ID | Document | Stage | Key Content |
|----|----------|-------|-------------|
| sd01 | `s0_configuration_skill.md` | s0 | Model variant selection (sbm vs sbm_gwf), routing choice (kinematic vs local inertial), sediment toggle, resolution guidelines |
| sd02 | `s1_hydromt_setup_skill.md` | s1 | HydroMT data catalog construction, build config YAML, dataset selection (MERIT vs HydroCraft DEM, SoilGrids vs HWSD), river threshold tuning |
| sd03 | `s2_forcing_skill.md` | s2 | CMFD/MSWX to wflow conversion, PET calculation methods, unit traps (mm/timestep vs mm/s), temporal alignment |
| sd04 | `s3_parameters_skill.md` | s3 | TOML parameter system (scale/offset), key parameters for calibration, parameter sensitivity by climate zone, comparison with VIC parameters |
| sd05 | `s4_execution_skill.md` | s4 | Julia environment setup, first-run compilation, multi-threading, memory management, warm-start from states |
| sd06 | `s5_output_skill.md` | s5 | Output NetCDF structure, discharge extraction, water balance verification, comparison with VIC output |
| sd07 | `s6_s8_sediment_skill.md` | s6-s8 | Sediment model setup, USLE parameters, transport formula selection, validation against observations |
| sd08 | `s9_coupling_skill.md` | s9 | CaMa-Flood coupling, VIC comparison methodology, MODFLOW recharge coupling, sediment-water quality coupling |

---

## 6. Diagnostic Triplets

### Estimated: 25-35 triplets across 7 failure domains

Based on the PREFLIGHT.md patterns and wflow-specific considerations:

#### Unit Conversion (5-7 triplets)
| ID | Severity | Symptom | Root Cause |
|----|----------|---------|-----------|
| dt_w001 | silent | Runoff much too high/low | Precipitation in mm/s instead of mm/timestep |
| dt_w002 | silent | ET unrealistically high | Temperature in Kelvin instead of Celsius |
| dt_w003 | silent | Zero PET everywhere | PET variable has wrong units or is missing |
| dt_w004 | silent | Snow everywhere in tropics | Temperature offset not applied |
| dt_w005 | silent | Sediment yield 1000x off | USLE K factor in wrong units |

#### Runtime (4-6 triplets)
| ID | Severity | Symptom | Root Cause |
|----|----------|---------|-----------|
| dt_w006 | fatal | Julia "MethodError" on startup | Wflow version mismatch with TOML format |
| dt_w007 | fatal | OutOfMemoryError | Domain too large for available RAM (wflow loads entire grid) |
| dt_w008 | fatal | "DimensionMismatch" | staticmaps.nc dimensions don't match forcing.nc |
| dt_w009 | degraded | Extremely slow first run (~30 min) | Julia JIT compilation, not an error |
| dt_w010 | fatal | "KeyError: variable not found" | TOML references variable not in staticmaps.nc (v1.0 uses CSDMS standard names) |

#### Parameter Format (3-5 triplets)
| ID | Severity | Symptom | Root Cause |
|----|----------|---------|-----------|
| dt_w011 | fatal | TOML parse error | Invalid TOML syntax (missing quotes, wrong brackets) |
| dt_w012 | silent | All cells have same parameter value | scale=0 or offset dominates — intended scale/offset not applied |
| dt_w013 | silent | River routing produces zero flow | River network not properly defined in staticmaps.nc |
| dt_w014 | fatal | "BoundsError: attempt to access" | River cell references non-existent downstream cell |

#### Silent Errors (4-6 triplets)
| ID | Severity | Symptom | Root Cause |
|----|----------|---------|-----------|
| dt_w015 | silent | Discharge timing correct but magnitude 2x off | Wrong upstream area in staticmaps.nc (affects unit conversion) |
| dt_w016 | silent | Glacier melt absent despite glacier flag=true | Glacier fraction map all zeros (dataset doesn't cover region) |
| dt_w017 | silent | Baseflow too high, no peaks | f parameter too low (Ksat doesn't decay, all water percolates) |
| dt_w018 | silent | Sediment model produces zero erosion | USLE C factor = 0 for all cells (forest defaults in GlobCover) |

#### Environment / Julia (3-4 triplets)
| ID | Severity | Symptom | Root Cause |
|----|----------|---------|-----------|
| dt_w019 | fatal | "Package Wflow not found" | Julia environment not activated (--project missing) |
| dt_w020 | fatal | "ERROR: LoadError" during precompilation | NetCDF library version conflict |
| dt_w021 | fatal | Subprocess returns error 1, no output | Julia not in PATH or wrong version |

#### TOML v1.0 Migration (3-4 triplets)
| ID | Severity | Symptom | Root Cause |
|----|----------|---------|-----------|
| dt_w022 | fatal | "Unknown key" in TOML | wflow v1.0 refactored TOML structure with CSDMS standard names; old TOML format won't work |
| dt_w023 | silent | Output variables all NaN | Output variable names changed in v1.0 (e.g., `q_river` -> new standard name) |
| dt_w024 | degraded | HydroMT-wflow generates TOML for wrong version | HydroMT-wflow version must match Wflow.jl version (v1.0 breaking changes) |

#### Coupling (2-3 triplets)
| ID | Severity | Symptom | Root Cause |
|----|----------|---------|-----------|
| dt_w025 | silent | wflow+CaMa-Flood double-counts routing | wflow already routes internally; CaMa-Flood re-routes the routed discharge |
| dt_w026 | silent | VIC vs wflow discharge differ by 3x | Different infiltration physics + different PET methods — expected, not a bug |

---

## 7. Coupling Points with HydroCraft Models

### c_w01: wflow -> CaMa-Flood (Flood Routing)

**Data flow**: wflow surface runoff (mm/day per cell) -> CaMa-Flood runoff input (NetCDF)

**When to use**: When wflow's built-in kinematic wave routing is insufficient and CaMa-Flood's global river network + floodplain dynamics are needed.

**CRITICAL**: wflow must be run **without** internal river routing (land-only mode) to avoid double-counting. Extract `SFCRNOFF` equivalent (overland runoff + subsurface lateral flow) before routing.

**Tool needed**: `t14_wflow_to_cama.py` — converts wflow gridded runoff to CaMa-Flood `_runoff_1d_YYYY.nc` format.

### c_w02: wflow vs VIC (Model Intercomparison)

**Data flow**: Both models run on same basin/period -> compare discharge, ET, soil moisture

**Purpose**: Scientific validation, model uncertainty quantification, ensemble hydrology

**Tool needed**: `t10_compare_with_vic.py` — aligned temporal comparison, correlation, bias, NSE

### c_w03: wflow_sediment -> Water Quality (SWAT+ / RZWQM2)

**Data flow**: wflow_sediment sediment yield per cell -> SWAT+ sediment loading input

**When to use**: Sediment-bound nutrient transport (phosphorus, pesticides)

**Note**: This is the primary value proposition for wflow in HydroCraft — no other model provides spatially distributed sediment yield.

### c_w04: wflow GW Recharge -> MODFLOW

**Data flow**: wflow percolation below root zone -> MODFLOW recharge boundary condition

**When to use**: Coupled surface-groundwater modelling (more physically based than VIC's baseflow)

**Tool needed**: `t15_wflow_recharge_to_modflow.py`

### c_w05: wflow Local Inertial -> SFINCS / SWMM

**Data flow**: wflow 2D flood inundation -> SFINCS/SWMM boundary conditions for urban flood detail

**When to use**: Urban flood risk assessment (wflow provides fluvial flood extent, SWMM handles urban drainage)

### c_w06: wflow + OGGM (Glacier Coupling)

**Data flow**: OGGM glacier mass balance -> wflow glacier module calibration, OR replace wflow's simple glacier module with OGGM's detailed glacier dynamics

**CRITICAL**: Same double-counting trap as VIC+OGGM (see PREFLIGHT.md coupling traps). One model must "own" glacier melt.

---

## 8. Validation Plan

### Phase 1: Smoke Test (1-2 days)

**Basin**: Chaohe (already well-characterized in HydroCraft, ~8,783 km^2)

**Steps**:
1. Install Julia + Wflow.jl
2. Install HydroMT-wflow
3. Build wflow model for Chaohe using HydroMT with default global datasets
4. Run wflow_sbm for 2000-2010
5. Compare discharge with VIC output (already available)
6. Verify water balance closure

**Success criteria**: Model runs to completion, discharge is within 2x of VIC, water balance closes to <5%

### Phase 2: Forcing Integration (2-3 days)

**Basin**: Chaohe (same basin)

**Steps**:
1. Build custom tool to convert CMFD forcing to wflow format
2. Re-run wflow with CMFD forcing (same forcing as VIC)
3. Compare discharge — difference should now be due to model physics only, not forcing
4. Build custom HydroMT data catalog using HydroCraft datasets (HWSD, AVHRR)

**Success criteria**: wflow with CMFD forcing produces physically reasonable discharge, correlation with VIC > 0.5

### Phase 3: Sediment Validation (3-5 days)

**Basin**: A basin with observed sediment data (candidate: Yellow River tributary, or Chaohe)

**Steps**:
1. Build wflow_sediment model using HydroMT
2. Run sediment simulation
3. Compare sediment yield with literature values / USLE estimates
4. Test all 5 transport capacity formulas
5. Analyze grain size distribution output

**Success criteria**: Sediment yield within order of magnitude of literature values

### Phase 4: Multi-Basin Validation (5-7 days)

**Basins**: 3 diverse basins from HydroCraft's validated set

| Basin | Climate | Area | Existing VIC? | Purpose |
|-------|---------|------|--------------|---------|
| Bengbu (Huai River) | Humid subtropical | 121,330 km^2 | Yes (NSE=0.90) | Large basin, well-calibrated VIC reference |
| Heihe Upper | Semi-arid alpine | 8,662 km^2 | Yes | Test glacier module, cold region |
| Koksilah (Canada) | Temperate maritime | 229 km^2 | Yes (NSE=0.43) | Small basin, MSWX forcing, HYDAT obs |

**Success criteria**: wflow produces physically plausible results on all 3 basins without manual intervention

### Phase 5: Production Integration (3-5 days)

1. Full pipeline tool (`run_wflow_full_pipeline.py`) working end-to-end
2. SKILL.md written and verified
3. All diagnostic triplets from validation runs recorded
4. Integration tested with HydroCraft web UI (wflow as a routing option)
5. Coupling with CaMa-Flood verified

---

## 9. Estimated Effort

| Phase | Task | Days | Dependencies |
|-------|------|------|-------------|
| **Setup** | Julia installation, Wflow.jl, HydroMT-wflow | 1 | None |
| **Phase 1** | Pipeline mapping (this plan -> real stages) | 1 | Setup |
| **Phase 2** | Knowledge classification | 0.5 | Phase 1 |
| **Phase 3** | Tool extraction (16 tools) | 5-7 | Phase 2 |
| **Phase 4** | Skill document writing (8 docs) | 2-3 | Phase 3 |
| **Phase 5** | Diagnostic triplet construction | 1-2 | Phase 4 |
| **Phase 6** | Assembly, validation, SKILL.md | 3-5 | Phase 5 |
| **Validation** | 5 phases as described above | 14-22 | Phase 6 |
| **Total** | | **27-42 days** | |

### Effort Comparison with Prior Models

| Model | Tools | Triplets | Validation Days | Total |
|-------|-------|----------|----------------|-------|
| VIC (original) | 18 | 27 | 14 | ~30 days |
| WRF-Hydro | 11 | 35 | 7 | ~15 days |
| SWAT+ | 31 | 23 | 5 | ~12 days |
| DSSAT | 61 | 61 | 10 | ~25 days |
| **wflow (estimate)** | **16** | **25-35** | **14-22** | **27-42 days** |

wflow is estimated to be moderate difficulty — simpler than DSSAT (no Fortran, modern TOML config, NetCDF I/O) but with the Julia ecosystem challenge adding overhead.

---

## 10. Priority & Dependencies

### Priority: **Medium-High**

**Rationale**:
- **Sediment transport** is the primary gap filled — no other HydroCraft model provides spatially distributed erosion/sediment yield
- **Built-in flood routing** (local inertial) reduces dependency on CaMa-Flood for some applications
- **HydroMT automation** aligns with HydroCraft's "zero manual data prep" philosophy
- **Julia ecosystem** is a new dependency but Julia is gaining adoption in scientific computing

### Dependencies

| Dependency | Status | Required For |
|-----------|--------|-------------|
| Julia 1.10+ runtime | **Not installed** | All wflow execution |
| Wflow.jl v1.0.2 | **Not installed** | Model execution |
| HydroMT-wflow | **Not installed** | Automated model setup |
| MERIT Hydro DEM | **Not available** | HydroMT basemaps (can use existing GLO-30/China DEM) |
| SoilGrids 2.0 | **Not available** | HydroMT soil maps (can map from HWSD) |
| HydroCraft Python env | **Available** | Python tools, HydroMT |
| CMFD / MSWX forcing | **Available** | Forcing conversion |
| HWSD soil data | **Available** | Alternative to SoilGrids |
| AVHRR land cover | **Available** | Land use parameters |
| CaMa-Flood | **Available** | Coupling (optional) |
| VIC outputs | **Available** | Model intercomparison |

### Blocking Issues

1. **Julia installation**: Must be approved by sysadmin. Julia requires ~500 MB disk + packages. No root access needed (user-space install via `juliaup`).

2. **MERIT Hydro DEM**: HydroMT-wflow's basemap setup strongly prefers MERIT Hydro (includes pre-computed flow directions). Without it, we need to compute flow directions ourselves (already have tools for this). Download size: ~5 GB for global.

3. **wflow v1.0 breaking changes**: The v1.0 release (Dec 2024) refactored TOML configuration to use CSDMS standard names. HydroMT-wflow must be updated to match. Verify compatibility before starting.

4. **HydroMT data catalog**: Building a custom catalog that maps HydroCraft's existing datasets (HWSD, AVHRR, CMFD) to HydroMT's expected format is non-trivial but essential to avoid downloading duplicate global datasets.

### Recommended Sequence

```
Week 1:  Install Julia + Wflow.jl + HydroMT-wflow
         Smoke test on Chaohe (Phase 1 validation)
         Begin tool extraction (t01-t04)

Week 2:  CMFD forcing integration (t04-t05)
         Parameter tools (t06)
         Execution wrapper (t07)
         Phase 2 validation (CMFD forcing)

Week 3:  Output tools (t08-t10)
         Sediment tools (t11-t13)
         Phase 3 validation (sediment)

Week 4:  Coupling tools (t14-t16)
         Skill documents (sd01-sd08)
         Diagnostic triplets

Week 5:  Multi-basin validation (Phase 4)
         Assembly and SKILL.md

Week 6:  Production integration
         Web UI integration
         Final review
```

---

## 11. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Julia ecosystem unfamiliarity | High | Medium | Start with subprocess calls, avoid PyJulia complexity |
| wflow v1.0 TOML breaking changes | High | High | Pin HydroMT-wflow version, test TOML generation carefully |
| MERIT Hydro download issues | Medium | Low | Use existing HydroCraft DEMs with custom flow direction computation |
| HydroMT data catalog complexity | Medium | Medium | Start with ERA5 (default), then build custom catalog |
| Julia first-run compilation time | Certain | Low | Use PackageCompiler sysimage for production, warn users |
| Sediment validation data scarcity | High | Medium | Use USLE literature values and inter-model comparison |
| Memory issues on large domains | Medium | Medium | wflow loads entire domain; test memory on Bengbu (121K km^2) |

---

## 12. File Structure (Target)

```
models/wflow/
├── knowledge_infrastructure/
│   ├── DISSECTION_PLAN.md          # This file
│   ├── SKILL.md                    # Agent entry point (to be written)
│   ├── knowledge_infrastructure.yaml
│   ├── workflow/
│   │   ├── pipeline.drawio
│   │   └── workflow.md
│   ├── tools/
│   │   ├── s0_config/
│   │   │   └── setup_wflow_config.py
│   │   ├── s1_hydromt/
│   │   │   ├── build_data_catalog.py
│   │   │   └── run_hydromt_build.py
│   │   ├── s2_forcing/
│   │   │   ├── convert_forcing_to_wflow.py
│   │   │   └── calculate_pet.py
│   │   ├── s3_parameters/
│   │   │   └── adjust_parameters.py
│   │   ├── s4_execution/
│   │   │   └── run_wflow.py
│   │   ├── s5_postprocess/
│   │   │   ├── extract_discharge.py
│   │   │   ├── extract_spatial_output.py
│   │   │   └── compare_with_vic.py
│   │   ├── s6_sediment/
│   │   │   ├── build_sediment_model.py
│   │   │   └── run_wflow_sediment.py
│   │   ├── s8_sediment_post/
│   │   │   └── analyze_sediment.py
│   │   ├── s9_coupling/
│   │   │   ├── wflow_to_cama.py
│   │   │   └── wflow_recharge_to_modflow.py
│   │   └── run_wflow_full_pipeline.py
│   ├── docs/
│   │   ├── s0_configuration_skill.md
│   │   ├── s1_hydromt_setup_skill.md
│   │   ├── s2_forcing_skill.md
│   │   ├── s3_parameters_skill.md
│   │   ├── s4_execution_skill.md
│   │   ├── s5_output_skill.md
│   │   ├── s6_s8_sediment_skill.md
│   │   └── s9_coupling_skill.md
│   ├── diagnostics/
│   │   ├── triplets.yaml
│   │   ├── error_log.yaml
│   │   └── episodes.yaml
│   └── julia/
│       ├── wflow_runner.jl          # Thin Julia wrapper script
│       ├── Project.toml             # Julia environment
│       └── Manifest.toml            # Julia lock file
├── test_data/                       # Small test basin for smoke tests
│   ├── wflow_sbm.toml
│   ├── staticmaps.nc
│   └── forcing.nc
└── examples/
    └── chaohe_wflow/                # Example configuration for Chaohe basin
```

---

## 13. Summary

wflow (Deltares) is a strong candidate for HydroCraft's 16th model package. It fills the critical **sediment/erosion gap** and provides an alternative modern hydrology model with built-in routing (kinematic wave + local inertial) and water demand/allocation. The main challenge is the **Julia ecosystem integration**, which is mitigated by using subprocess calls from Python and HydroMT-wflow (Python) for model setup.

**Estimated deliverables**: 16 tools (~5,400 lines), 8 skill documents, 25-35 diagnostic triplets, 9 pipeline stages, 6 coupling points.

**Estimated timeline**: 5-6 weeks from installation to production integration.

**Key value proposition**: After dissection, HydroCraft gains the ability to autonomously run sediment/erosion simulations on any basin worldwide, with zero manual data preparation, using the same "specify location + period" interface as all other models.
