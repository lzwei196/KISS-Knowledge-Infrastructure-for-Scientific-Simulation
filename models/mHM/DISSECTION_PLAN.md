# Knowledge Dissection Plan: mHM (mesoscale Hydrological Model)

**Model**: mHM v5.13.2 (latest release: October 2025)
**Repository**: https://git.ufz.de/mhm/mhm (mirror: https://github.com/mhm-ufz/mHM)
**Developers**: Helmholtz Centre for Environmental Research (UFZ), Leipzig, Germany
**License**: LGPL-3.0
**Language**: Fortran (76.5%), Python (15.5%), CMake (3.7%)
**Key Publications**:
- Samaniego, L., Kumar, R., & Attinger, S. (2010). Multiscale parameter regionalization of a grid-based hydrologic model at the mesoscale. *Water Resources Research*, 46, W05523.
- Kumar, R., Samaniego, L., & Attinger, S. (2013). Implications of distributed hydrologic model parameterization on water fluxes at multiple scales and locations. *Water Resources Research*, 49, 360-379.
- Samaniego, L., et al. (2017). Toward seamless hydrologic predictions across spatial scales. *Hydrology and Earth System Sciences*, 21, 4323-4346.

**Prepared by**: Jianyun Zhang Research Group, Hohai University
**Date**: 2026-03-23
**Status**: PLANNING (pre-dissection)

---

## 1. Model Overview

### 1.1 What is mHM?

mHM is a **grid-based distributed hydrological model** developed at UFZ that simulates the terrestrial water cycle at the mesoscale (10-100,000 km2). Its defining innovation is **Multiscale Parameter Regionalization (MPR)** -- a methodology that derives spatially distributed model parameters from high-resolution physiographic data (soil, geology, land cover, topography) through **transfer functions** with a small set of **global parameters** (~50-70 parameters). Because the global parameters are location-independent, they can be calibrated on gauged basins and transferred directly to ungauged basins -- provided the same physiographic data sources are used.

### 1.2 What Makes mHM Unique vs. Existing HydroCraft Models

| Feature | VIC | WRF-Hydro | Raven | wflow | **mHM** |
|---------|-----|-----------|-------|-------|---------|
| Parameter regionalization | No (per-cell) | No (lookup tables) | No (per-HRU) | No (per-cell) | **Yes (MPR)** |
| Transfer to ungauged basins | Requires recalibration | Requires recalibration | Requires recalibration | Requires recalibration | **Direct transfer** |
| Calibration parameters | 6 (per cell) | ~15 (per cell) | 5-20 (per model) | 10-20 (per cell) | **~50-70 global** |
| Multi-basin simultaneous | No | No | No | No | **Yes (native)** |
| Built-in optimization | No | No | No | No | **Yes (DDS, SCE)** |
| Spatial resolution flexibility | Fixed | Fixed | Semi-lumped | Fixed | **Multi-resolution** |
| Integrated routing | External | Internal | Internal | Internal | **MRM (internal)** |

**Strategic value for HydroCraft**: mHM enables a "calibrate once, apply everywhere" paradigm. Calibrate on well-gauged basins in a region, then predict discharge for any ungauged basin using the same global parameters + local physiographic data. This is transformative for data-sparse regions (most of the world).

### 1.3 Core Hydrological Processes

mHM implements a complete water balance with configurable process representations:

| Process | Default Method | Options |
|---------|---------------|---------|
| **Canopy interception** | LAI-based maximum interception | Case 1 |
| **Snow** | Degree-day with land-use differentiation | Case 1 (degree-day), Case 3 (enhanced) |
| **Soil moisture** | Feddes equation, multi-layer infiltration | Case 1 (standard), Case 2-4 (variants) |
| **Evapotranspiration** | Hargreaves-Samani or Penman-Monteith | 5 PET options |
| **Direct runoff** | Impervious area + infiltration excess | Case 1 |
| **Interflow** | Storage reservoir with slope dependence | Case 1 |
| **Percolation** | Linear groundwater reservoir | Case 1 |
| **Baseflow** | Recession curve with geology dependence | Case 1 |
| **Routing (MRM)** | Muskingum or adaptive celerity | Case 1 (Muskingum), Case 3 (adaptive) |

### 1.4 Multiscale Parameter Regionalization (MPR) -- The Core Innovation

**Problem**: Traditional distributed models calibrate parameters per grid cell, making them non-transferable to ungauged basins.

**MPR Solution** (three levels):

1. **Level 0 (L0)** -- Highest resolution: Raw physiographic data (DEM 90m, soil 1:1M, land cover 1km, geology 1:5M). These are NOT calibrated -- they are observed properties (sand%, clay%, bulk density, slope, land cover class, geology class).

2. **Transfer Functions** -- Pedotransfer functions and empirical relationships that convert Level 0 properties to effective hydrological parameters. Example:
   - Porosity = f(sand%, clay%, bulk_density; **a1, a2, a3**) where a1, a2, a3 are **global parameters**
   - Ksat = f(sand%, clay%, organic_matter; **b1, b2, b3**)
   - Interception capacity = f(LAI; **c1**)
   - Degree-day factor = f(land_cover_class, elevation; **d1, d2**)
   - Baseflow recession = f(geology_class; **e1, e2, ...**)

3. **Level 1 (L1)** -- Model resolution: The L0 properties are upscaled to the model grid resolution through the transfer functions + spatial averaging. The resulting L1 parameters are the actual model inputs.

**Key insight**: The **global parameters** (a1, a2, a3, b1, b2, ...) are the ONLY things calibrated. There are ~50-70 of them. They encode **process understanding** (how soil texture maps to hydraulic conductivity), not location-specific values. Once calibrated, they can be applied to ANY basin where the same L0 data sources are available.

**Why this matters for HydroCraft**: With HWSD soil + AVHRR land cover + DEM + GLiM geology all available globally in HydroCraft, we can calibrate mHM global parameters on gauged basins and predict discharge for any ungauged basin worldwide.

### 1.5 Multi-Basin Capability

mHM natively supports simultaneous multi-basin simulation:
- Configure multiple domains in `mhm.nml` (set `nDomains > 1`)
- Each domain has its own morphological data, forcing, and gauges
- All domains share the SAME global parameters
- Calibration optimizes global parameters across ALL domains simultaneously
- This is the standard workflow for MPR -- calibrate on multiple basins at once for robust transfer

---

## 2. Installation Plan

### 2.1 Dependencies

| Dependency | Version | Purpose | Ubuntu Package |
|-----------|---------|---------|----------------|
| gfortran | >= 9.0 | Fortran compiler | `gfortran` |
| CMake | >= 3.14 | Build system | `cmake` |
| NetCDF-Fortran | >= 4.5 | I/O library | `libnetcdff-dev` |
| NetCDF-C | >= 4.7 | NetCDF base | `libnetcdf-dev` |
| HDF5 | >= 1.10 | NetCDF backend | auto (via CPM) |
| zlib | any | Compression | auto (via CPM) |
| FORCES library | >= 0.4.0 | UFZ Fortran library | auto (via CPM) |
| Git | any | Version control | `git` |

### 2.2 Build Steps

```bash
# 1. Install system dependencies
sudo apt-get install -y git gfortran netcdf-bin libnetcdf-dev libnetcdff-dev cmake make

# 2. Clone repository
cd KISSPATH_BINARIES/
git clone https://git.ufz.de/mhm/mhm.git mhm_v5.13
cd mhm_v5.13

# 3. Checkout latest stable release
git checkout v5.13.2

# 4. Build with CMake
export FC=gfortran
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel $(nproc)

# 5. Verify
./build/mhm --version

# 6. Optional: install to known location
cmake --install build --prefix KISSPATH_BINARIES/mhm_v5.13/install
```

### 2.3 Expected Binary Path

```
KISSPATH_BINARIES/mhm_v5.13/build/mhm
```

### 2.4 Potential Build Issues

| Issue | Likelihood | Mitigation |
|-------|-----------|-----------|
| FORCES library download fails (behind firewall) | Medium | Clone manually: `git clone https://git.ufz.de/chs/forces.git`, pass `-DCPM_forces_SOURCE=../forces` |
| NetCDF-Fortran not found | Medium | Set `-DNetCDF_ROOT=/path/to/netcdf` |
| gfortran version too old | Low | Ubuntu 22.04+ has gfortran 11+, sufficient |
| fypp preprocessor missing | Low | `pip install fypp` in Python venv |

---

## 3. Input/Output Data Architecture

### 3.1 Input Directory Structure (per domain)

```
input/
  morph/                  # Level 0 physiographic data
    dem.asc               # Digital Elevation Model (ESRI ASCII grid)
    slope.asc             # Terrain slope
    aspect.asc            # Terrain aspect
    fdir.asc              # Flow direction (D8)
    facc.asc              # Flow accumulation
    soil_class.asc        # Soil type classification
    soil_class_horizon_01.asc  # Soil class per horizon
    soil_class_horizon_02.asc
    soil_classdefinition.txt   # Soil class -> properties lookup
    geology_class.asc     # Geology classification
    geology_classdefinition.txt
    LAI_class.asc         # LAI class map
    LAI_classdefinition.txt
    idgauges.asc          # Gauge location grid
  luse/                   # Land use/cover maps (time-varying)
    lc_1981.asc           # Land cover for period 1
    lc_1991.asc           # Land cover for period 2
  meteo/                  # Meteorological forcing
    pre/                  # Precipitation (NetCDF, per timestep)
    tavg/                 # Average temperature
    pet/                  # Potential ET (or tmin/tmax for Hargreaves)
  gauge/                  # Observed discharge
    00398.txt             # Tab-separated: date, Q (m3/s)
  lai/                    # Optional: gridded LAI time series
  latlon/                 # Geographic coordinate files
  optional_data/          # Optional additional inputs
```

### 3.2 Configuration Files (Namelists)

| File | Purpose | Key Parameters |
|------|---------|---------------|
| `mhm.nml` | Main configuration | nDomains, resolution, time period, process selection, data paths, optimization settings |
| `mhm_parameter.nml` | MPR global parameters | ~70 parameters with (lower, upper, value, flag, scaling) |
| `mhm_outputs.nml` | Hydrological output config | 21 output variables (states + fluxes), frequency, compression |
| `mrm_outputs.nml` | Routing output config | Streamflow, river temperature, frequency |

### 3.3 Output Format

All outputs are **NetCDF** with:
- Dimensions: `(time, northing, easting)` or `(time, nGauges)`
- Compression: deflate level 6
- Double precision available
- Daily or monthly frequency (configurable)

Key output variables:

| Variable | Description | Unit |
|----------|-------------|------|
| L1_total_runoff | Total cell runoff | mm/T |
| L1_baseflow | Baseflow | mm/T |
| L1_fastRunoff | Fast interflow | mm/T |
| L1_slowRunoff | Slow interflow | mm/T |
| L1_runoffSeal | Sealed surface runoff | mm/T |
| aET | Actual evapotranspiration | mm/T |
| PET | Potential evapotranspiration | mm/T |
| L1_soilMoist | Soil moisture per layer | mm |
| L1_snowpack | Snow water equivalent | mm |
| L1_satSTW | Saturated zone storage | mm |
| L1_percol | Groundwater recharge | mm/T |
| Qrouted | Routed streamflow (MRM) | m3/s |

### 3.4 Input Format: ESRI ASCII Grid

mHM reads morphological data as ESRI ASCII grids (`.asc`):
```
ncols         10
nrows         8
xllcorner     6.000
yllcorner     49.000
cellsize      0.25
NODATA_value  -9999
1 2 3 4 5 6 7 8 9 10
...
```

This is straightforward to generate from any raster using GDAL/rasterio.

### 3.5 Input Format: Meteorological Forcing

Forcing is in **NetCDF** format with dimensions `(time, lat, lon)`:
- One file per variable per time chunk (daily files or monthly files)
- Variables: precipitation (pre), average temperature (tavg), PET or tmin/tmax
- Resolution: must match the L0 (highest resolution) grid, mHM handles upscaling internally
- Time: daily or sub-daily

---

## 4. Pipeline Stages

### Stage Overview

```
s0_config         Configuration & basin definition
    |
s1_domain         Domain grid setup (L0, L1, L11 grids)
    |
s2_morphology     Morphological data preparation (DEM, soil, geology, land cover)
    |
s3_mpr            MPR parameter file setup (transfer function coefficients)
    |
s4_forcing        Meteorological forcing preparation (CMFD/MSWX -> mHM NetCDF)
    |
s5_gauge          Observed discharge preparation
    |
s6_namelist       Namelist assembly (mhm.nml + mhm_parameter.nml + outputs)
    |
s7_execute        Model execution
    |
s8_postprocess    Output extraction & analysis
    |
s9_calibrate      Calibration (built-in DDS/SCE or external)
    |
s10_regionalize   Transfer to ungauged basins (THE KEY STAGE)
    |
s11_validate      Cross-validation & performance assessment
```

### Stage Details

#### s0_config: Configuration

**Purpose**: Define basin, resolution, time period, data sources.
**Knowledge type**: Evaluative (decisions about resolution, forcing dataset, PET method)

**Key decisions**:
- L0 resolution (highest, for morphological data; typically DEM native resolution)
- L1 resolution (model grid; 1-25 km, specified in meters in mhm.nml as `resolution_Hydrology`)
- L11 resolution (routing grid; can differ from L1, set by `resolution_Routing`)
- Forcing dataset: CMFD (China) vs MSWX (global)
- PET method: Hargreaves (needs tmin/tmax), Priestley-Taylor, Penman-Monteith
- Number of soil horizons (default 2)
- Time step (default 1 hour)

**Tools to build**: 1
- `configure_mhm_basin.py` -- generates directory structure and initial config

**Estimated lines**: ~150

---

#### s1_domain: Domain Grid Setup

**Purpose**: Define the three spatial grids (L0, L1, L11) and their nesting relationship.
**Knowledge type**: Procedural

mHM operates on three grids:
- **L0**: Highest resolution (e.g., 100m). All morphological/physiographic data lives here.
- **L1**: Model resolution (e.g., 1000-24000m). Hydrological processes simulated here.
- **L11**: Routing resolution (typically = L1 or coarser). River routing (MRM) operates here.

L1 and L11 must be integer multiples of L0.

**Tools to build**: 2
- `setup_mhm_domain.py` -- compute grid extents from shapefile, generate header files (~200 lines)
- `generate_latlon_files.py` -- create lat/lon NetCDF for the domain (~100 lines)

**Estimated lines**: ~300

---

#### s2_morphology: Morphological Data Preparation

**Purpose**: Convert HydroCraft global datasets to mHM ASCII grid format at L0 resolution.
**Knowledge type**: Procedural (format conversion) + Evaluative (classification schemes)

This is the **most complex stage** because mHM uses a class-based system for soil, geology, and land cover (not continuous values). Each class has a lookup table defining its properties.

**Sub-tasks**:

| Sub-task | HydroCraft Source | mHM Target | Notes |
|----------|------------------|------------|-------|
| DEM | China DEM 90m / Copernicus GLO-30 | `dem.asc` | Clip + reproject + ASCII export |
| Slope & Aspect | Derived from DEM | `slope.asc`, `aspect.asc` | WhiteboxTools or GDAL |
| Flow direction | Derived from DEM | `fdir.asc` | D8 encoding. **CAUTION**: mHM may use a different D8 convention than WhiteboxTools -- must verify |
| Flow accumulation | Derived from DEM | `facc.asc` | Standard D8 accumulation |
| Soil classes | HWSD global raster + MDB | `soil_class.asc`, `soil_class_horizon_*.asc`, `soil_classdefinition.txt` | Map HWSD MU_GLOBAL to mHM soil classes; extract sand/clay/silt/BD/OM per horizon |
| Geology classes | GLiM lithology | `geology_class.asc`, `geology_classdefinition.txt` | Map GLiM classes to mHM geology classes (controls baseflow recession) |
| Land cover | AVHRR 1km | `lc_YYYY.asc` | Reclassify to mHM land use classes (forest, agriculture, urban, etc.) |
| LAI classes | AVHRR or MODIS | `LAI_class.asc`, `LAI_classdefinition.txt` | Monthly LAI lookup per class |
| Gauge locations | Basin outlet | `idgauges.asc` | Grid with gauge ID at gauge location, 0 elsewhere |

**Tools to build**: 8
- `dem_to_mhm_ascii.py` -- DEM clip + slope/aspect + ASCII (~200 lines)
- `generate_flow_grids.py` -- flow direction + accumulation with correct D8 encoding (~250 lines)
- `hwsd_to_mhm_soil.py` -- HWSD -> mHM soil classes + classdefinition.txt (~350 lines) **CRITICAL**
- `glim_to_mhm_geology.py` -- GLiM -> mHM geology classes (~200 lines)
- `landcover_to_mhm_luse.py` -- AVHRR -> mHM land use classes (~200 lines)
- `generate_lai_classes.py` -- LAI classification + monthly lookup table (~200 lines)
- `generate_gauge_grid.py` -- gauge location ASCII grid (~100 lines)
- `validate_morph_consistency.py` -- check all grids align (ncols, nrows, cellsize, extent) (~150 lines)

**Estimated lines**: ~1,650

**Key pitfalls**:
- All ASCII grids MUST have identical headers (ncols, nrows, xllcorner, yllcorner, cellsize)
- D8 flow direction encoding must match mHM's expected convention (verify against source code)
- Soil classdefinition format is strict: columns must be tab-separated with exact header
- HWSD -> mHM soil mapping requires careful handling of NODATA and water bodies
- Two soil database formats exist: classical (flag=0) vs new (flag=1) -- we should use classical initially

---

#### s3_mpr: MPR Parameter File Setup

**Purpose**: Configure the transfer function global parameters in `mhm_parameter.nml`.
**Knowledge type**: Evaluative (parameter range selection) + Procedural (file generation)

The `mhm_parameter.nml` file contains ~70 global parameters organized by process:

| Process Group | Parameters | Count | Notes |
|--------------|-----------|-------|-------|
| Interception | canopyInterceptionFactor | 1 | LAI multiplier |
| Snow | snowThreshold, degreeDayFactor (3 land types), maxDegreeDayFactor (3) | ~8 | Land-use differentiated |
| Soil moisture | PTF coefficients (Zacharias/Cosby), rootFractionCoeff, infiltrationShapeFactor | ~20 | Heart of MPR |
| Direct runoff | imperviousStorageCapacity | 1 | |
| PET | method-specific coefficients | ~10 | Depends on PET choice |
| Interflow | storageCapacityFactor, recession_slope, Ks | 3 | |
| Percolation | rechargeCoefficient, rechargeFactor_karstic | 2 | |
| Baseflow | GeoParam(1-10) | 10 | Geology-dependent, not fully regionalized |
| Routing | travel time, attenuation coefficients | ~8 | Muskingum parameters |

Each parameter has: `lower_bound, upper_bound, value, FLAG, SCALING`
- FLAG=1: eligible for calibration
- FLAG=0: fixed at given value

**Tools to build**: 2
- `generate_mhm_parameters.py` -- create mhm_parameter.nml with literature-informed defaults and HydroCraft-appropriate ranges (~300 lines)
- `update_mpr_params.py` -- modify specific parameters for calibration iterations (~150 lines)

**Estimated lines**: ~450

---

#### s4_forcing: Meteorological Forcing Preparation

**Purpose**: Convert CMFD/MSWX forcing to mHM-compatible NetCDF at L0 resolution.
**Knowledge type**: Procedural

mHM reads forcing as NetCDF with specific variable names and dimensions. Required variables depend on PET method:

| PET Method | Required Forcing Variables |
|-----------|--------------------------|
| Hargreaves-Samani | pre, tmin, tmax |
| Input PET | pre, tavg, pet |
| Penman-Monteith | pre, tavg, wind, humidity, radiation, pressure |

**Strategy**: Use Hargreaves-Samani (simplest, needs only precipitation and temperature min/max) or provide pre-computed PET from CMFD/MSWX data.

**Unit requirements**:
- Precipitation: mm/day (or mm/timestep if sub-daily)
- Temperature: degrees Celsius
- PET: mm/day (if pre-computed)

**Tools to build**: 3
- `cmfd_to_mhm_forcing.py` -- CMFD -> mHM NetCDF with correct variable names, units, time encoding (~350 lines)
- `mswx_to_mhm_forcing.py` -- MSWX -> mHM NetCDF (~350 lines)
- `compute_pet_hargreaves.py` -- compute PET from tmin/tmax if needed (~150 lines)

**Estimated lines**: ~850

**Key pitfalls**:
- mHM expects forcing on the L0 grid (NOT L1). MPR handles the upscaling.
- Time encoding must be CF-compliant (days since reference date)
- Calendar handling: mHM uses standard calendar, must handle leap years correctly
- Variable names in NetCDF must exactly match what mhm.nml expects
- CMFD variables need unit conversion: temperature K -> C, precip mm/3hr -> mm/day

---

#### s5_gauge: Observed Discharge Preparation

**Purpose**: Convert observed Q data to mHM gauge format.
**Knowledge type**: Procedural

mHM gauge format:
- Plain text, one file per gauge
- Columns: date (YYYY MM DD), discharge (m3/s)
- NODATA value: -9999
- Filename: `GGGGG.txt` where GGGGG is the gauge ID (zero-padded)

**Tools to build**: 1
- `prepare_mhm_gauge.py` -- convert GRDC/HYDAT/HydroCraft obs format to mHM gauge format (~150 lines)

**Estimated lines**: ~150

---

#### s6_namelist: Namelist Assembly

**Purpose**: Generate the four namelist files with all paths and settings correct.
**Knowledge type**: Procedural + Evaluative (process selection)

**Tools to build**: 2
- `generate_mhm_namelists.py` -- assemble all four .nml files from config (~400 lines)
- `validate_namelists.py` -- pre-flight check of all paths, parameters, consistency (~200 lines)

**Estimated lines**: ~600

**Key settings in mhm.nml**:
- `iFlag_cordinate_sys = 0` (regular lat/lon) or `1` (Gauss-Krueger)
- `resolution_Hydrology` in METERS (e.g., 24000 for ~0.25 degrees)
- `resolution_Routing` in METERS
- `nDomains` -- number of simultaneous basins
- `processSelection` -- 8-element array choosing process options
- Optimization settings (nIterations, seed, DDS/SCE method)

---

#### s7_execute: Model Execution

**Purpose**: Run mHM and parse output.
**Knowledge type**: Procedural + Debugging

**Tools to build**: 2
- `run_mhm.py` -- execute mHM with progress monitoring, error capture, timeout handling (~200 lines)
- `parse_mhm_output.py` -- read NetCDF output, extract discharge at gauges, compute basic statistics (~200 lines)

**Estimated lines**: ~400

**Expected runtime**:
- Small domain (10 cells, 4 years): ~10 seconds
- Medium domain (100 cells, 10 years): ~2-5 minutes
- Large domain (1000 cells, 10 years): ~20-60 minutes

---

#### s8_postprocess: Output Extraction & Analysis

**Purpose**: Extract key results, compute performance metrics, generate plots.
**Knowledge type**: Procedural

**Tools to build**: 3
- `extract_mhm_discharge.py` -- extract simulated Q at gauge locations, compute NSE/KGE/RMSE/PBIAS (~250 lines)
- `extract_mhm_spatial.py` -- extract spatial fields (ET, soil moisture, runoff) for mapping (~200 lines)
- `compare_mhm_vic.py` -- cross-model comparison with VIC/Raven/wflow outputs (~300 lines)

**Estimated lines**: ~750

---

#### s9_calibrate: Calibration

**Purpose**: Optimize global parameters using built-in or external calibration.
**Knowledge type**: Evaluative + Procedural

mHM has **built-in optimization** (unique among HydroCraft models):
- **DDS** (Dynamically Dimensioned Search) -- recommended
- **SCE** (Shuffled Complex Evolution)
- Objective function: KGE, NSE, or other

Alternatively, can use external calibration (e.g., HydroCraft's AI calibration framework).

**Multi-basin calibration** (the MPR way):
1. Select 2-5 gauged basins in the target region
2. Configure all as domains in a single mhm.nml
3. Optimize global parameters against all gauges simultaneously
4. The resulting parameters are regionalized -- they encode process understanding, not location-specific tuning

**Tools to build**: 3
- `setup_mhm_calibration.py` -- configure calibration namelists, set parameter flags (~250 lines)
- `run_mhm_calibration.py` -- manage calibration runs (built-in or external loop) (~300 lines)
- `analyze_calibration.py` -- convergence plots, parameter sensitivity, Pareto front (~250 lines)

**Estimated lines**: ~800

---

#### s10_regionalize: Transfer to Ungauged Basins (THE KEY STAGE)

**Purpose**: Apply calibrated global parameters to new (ungauged) basins.
**Knowledge type**: Evaluative (critical decisions about transferability)

**This is what makes mHM uniquely valuable.** The workflow:

1. Take the calibrated global parameters from s9 (from gauged basins)
2. Set up a NEW basin (s1-s6) with its own L0 physiographic data
3. Copy the calibrated `mhm_parameter.nml` to the new basin
4. Run mHM -- the MPR transfer functions automatically derive local parameters from the new basin's soil/geology/land cover + the calibrated global coefficients
5. Validate against any available data (remote sensing ET, GRACE water storage, etc.)

**Critical requirements for successful transfer**:
- Same L0 data sources (HWSD soil, GLiM geology, AVHRR land cover) must be used for BOTH calibration and prediction basins
- If different data sources are used, the transfer functions may not be valid
- Climate similarity helps but is not strictly required (the physics is encoded in transfer functions)
- Larger calibration basin sets (more diverse) produce more robust global parameters

**Tools to build**: 3
- `transfer_mpr_params.py` -- copy calibrated parameters to new basin, validate consistency (~200 lines)
- `setup_ungauged_basin.py` -- automated pipeline for new basin setup (calls s1-s7) (~300 lines)
- `validate_regionalization.py` -- cross-validation framework (leave-one-out, split-sample) (~350 lines)

**Estimated lines**: ~850

---

#### s11_validate: Cross-Validation & Performance Assessment

**Purpose**: Rigorously test regionalization performance.
**Knowledge type**: Evaluative

**Cross-validation approaches**:
1. **Leave-one-out**: Calibrate on N-1 basins, predict the left-out basin, repeat N times
2. **Split-sample**: Calibrate on half the period, validate on the other half
3. **Proxy-basin**: Calibrate on donor basin, validate on receiver basin
4. **Remote sensing validation**: Compare ET with MODIS ET, soil moisture with SMAP/ESA-CCI

**Tools to build**: 2
- `cross_validate_mpr.py` -- automated leave-one-out and split-sample (~400 lines)
- `remote_sensing_validate.py` -- compare mHM spatial outputs with satellite products (~250 lines)

**Estimated lines**: ~650

---

## 5. Tools Summary

| Stage | Tool | Lines (est.) | Priority |
|-------|------|-------------|----------|
| s0 | configure_mhm_basin.py | 150 | P0 (essential) |
| s1 | setup_mhm_domain.py | 200 | P0 |
| s1 | generate_latlon_files.py | 100 | P0 |
| s2 | dem_to_mhm_ascii.py | 200 | P0 |
| s2 | generate_flow_grids.py | 250 | P0 |
| s2 | hwsd_to_mhm_soil.py | 350 | P0 (CRITICAL) |
| s2 | glim_to_mhm_geology.py | 200 | P0 (CRITICAL) |
| s2 | landcover_to_mhm_luse.py | 200 | P0 |
| s2 | generate_lai_classes.py | 200 | P1 |
| s2 | generate_gauge_grid.py | 100 | P0 |
| s2 | validate_morph_consistency.py | 150 | P0 |
| s3 | generate_mhm_parameters.py | 300 | P0 |
| s3 | update_mpr_params.py | 150 | P1 |
| s4 | cmfd_to_mhm_forcing.py | 350 | P0 |
| s4 | mswx_to_mhm_forcing.py | 350 | P0 |
| s4 | compute_pet_hargreaves.py | 150 | P1 |
| s5 | prepare_mhm_gauge.py | 150 | P0 |
| s6 | generate_mhm_namelists.py | 400 | P0 |
| s6 | validate_namelists.py | 200 | P0 |
| s7 | run_mhm.py | 200 | P0 |
| s7 | parse_mhm_output.py | 200 | P0 |
| s8 | extract_mhm_discharge.py | 250 | P0 |
| s8 | extract_mhm_spatial.py | 200 | P1 |
| s8 | compare_mhm_vic.py | 300 | P1 |
| s9 | setup_mhm_calibration.py | 250 | P1 |
| s9 | run_mhm_calibration.py | 300 | P1 |
| s9 | analyze_calibration.py | 250 | P1 |
| s10 | transfer_mpr_params.py | 200 | P0 (KEY) |
| s10 | setup_ungauged_basin.py | 300 | P0 (KEY) |
| s10 | validate_regionalization.py | 350 | P1 |
| s11 | cross_validate_mpr.py | 400 | P2 |
| s11 | remote_sensing_validate.py | 250 | P2 |

**Total**: 32 tools, ~7,450 estimated lines

**Priority key**:
- P0: Required for basic autonomous operation (21 tools, ~4,500 lines)
- P1: Required for calibration and comparison (8 tools, ~2,050 lines)
- P2: Required for full MPR regionalization validation (3 tools, ~900 lines)

---

## 6. Skill Documents

| ID | Title | Stage | Key Content |
|----|-------|-------|-------------|
| sd01 | mHM Configuration Guide | s0 | Resolution selection, PET method choice, coordinate system |
| sd02 | Domain Grid Setup | s1 | L0/L1/L11 relationship, resolution constraints, grid alignment |
| sd03 | Morphological Data Preparation | s2 | ASCII grid format, classification schemes, HWSD-to-mHM mapping, GLiM-to-mHM mapping |
| sd04 | MPR Methodology & Parameters | s3 | **THE MOST IMPORTANT SKILL DOC** -- transfer function theory, parameter ranges by climate zone, sensitivity analysis guidance |
| sd05 | Forcing Data Preparation | s4 | CMFD/MSWX -> mHM conversion, unit requirements, PET computation |
| sd06 | Observed Data & Gauges | s5 | Gauge format, multi-gauge setup, GRDC/HYDAT integration |
| sd07 | Namelist Reference | s6 | Complete mhm.nml reference, process selection guide, optimization settings |
| sd08 | Model Execution | s7 | Runtime expectations, error interpretation, restart capability |
| sd09 | Output Analysis | s8 | NetCDF output structure, performance metrics, spatial diagnostics |
| sd10 | Calibration Strategy | s9 | DDS vs SCE, multi-basin calibration, parameter sensitivity, convergence |
| sd11 | MPR Regionalization Guide | s10 | **CRITICAL** -- transfer protocol, data source consistency, transferability assessment, ungauged basin workflow |
| sd12 | Cross-Validation Protocol | s11 | Leave-one-out, split-sample, proxy-basin, remote sensing validation |

**Total**: 12 skill documents

---

## 7. Diagnostic Triplets (Anticipated)

### Build Errors (5 triplets)

| ID | Symptom | Likely Root Cause |
|----|---------|------------------|
| dt_b01 | `CMake Error: Could not find FORCES` | CPM download failed; need local clone |
| dt_b02 | `undefined reference to _nf90_*` | NetCDF-Fortran not linked; set `-DNetCDF_ROOT` |
| dt_b03 | `Fatal Error: Cannot open module file 'mo_*'` | Build order issue; clean and rebuild |
| dt_b04 | `Error: Rank mismatch in argument` | gfortran version too old; need >= 9.0 |
| dt_b05 | `fypp: command not found` | Install fypp: `pip install fypp` |

### Runtime Errors (10 triplets)

| ID | Symptom | Likely Root Cause |
|----|---------|------------------|
| dt_r01 | `ERROR: Number of rows/columns do not match` | ASCII grid headers inconsistent across morph files |
| dt_r02 | `ERROR: Resolution mismatch` | L1 is not an integer multiple of L0 |
| dt_r03 | `ERROR: No meteorological data found` | Forcing NetCDF path wrong in mhm.nml or variable names wrong |
| dt_r04 | `ERROR: Gauge ID not found in grid` | idgauges.asc has wrong gauge ID or gauge outside domain |
| dt_r05 | Model runs but discharge is zero everywhere | Flow direction grid uses wrong D8 convention |
| dt_r06 | Discharge way too high (100x) | Precipitation units wrong (mm/3hr not converted to mm/day) |
| dt_r07 | Baseflow is zero despite wet climate | Geology class all mapped to class 1 (impervious); check geology_classdefinition.txt |
| dt_r08 | `ERROR: Parameter out of range` | mhm_parameter.nml value outside [lower, upper] bounds |
| dt_r09 | NaN in output fields | NODATA in soil/DEM not handled; check for -9999 propagation |
| dt_r10 | Model extremely slow (10x expected) | L0 resolution too fine relative to domain size; increase cellsize |

### Silent Errors (8 triplets) -- MOST DANGEROUS

| ID | Symptom | Detection Method |
|----|---------|-----------------|
| dt_s01 | Soil parameters physically unreasonable (Ksat=0) | soil_classdefinition.txt has wrong column order or missing classes |
| dt_s02 | ET systematically too high/low | PET method mismatch: Hargreaves expects tmin/tmax, not tavg |
| dt_s03 | Snow persists through summer in warm basin | snowThresholdTemperature calibrated for cold basin, applied to warm without re-calibration |
| dt_s04 | Regionalization degrades performance | Calibration and prediction basins use different L0 data sources (e.g., different soil databases) |
| dt_s05 | Multi-basin calibration biased toward largest basin | Objective function not normalized by basin area or number of timesteps |
| dt_s06 | Aspect values wrong (N/S flipped) | DEM in geographic CRS but aspect computed assuming projected CRS |
| dt_s07 | Interflow always zero | interflowStorageCapacityFactor at lower bound (75) but basin needs higher |
| dt_s08 | Routing lag wrong (peak 2 days early/late) | resolution_Routing in meters mismatch with actual grid spacing |

**Total**: 23 anticipated triplets

---

## 8. Coupling Points with HydroCraft Infrastructure

### 8.1 Data Sources (Input Coupling)

| mHM Input | HydroCraft Source | Tool Required | Complexity |
|-----------|------------------|--------------|-----------|
| DEM | China DEM 90m / Copernicus GLO-30 | `dem_to_mhm_ascii.py` | Low (format conversion) |
| Soil classes | HWSD global raster + MDB | `hwsd_to_mhm_soil.py` | **HIGH** (classification + lookup table generation) |
| Geology | GLiM lithology (global) | `glim_to_mhm_geology.py` | **HIGH** (new data source, mapping to mHM classes) |
| Land cover | AVHRR 1km | `landcover_to_mhm_luse.py` | Medium (reclassification) |
| Forcing (China) | CMFD 0.1 deg, 3-hourly | `cmfd_to_mhm_forcing.py` | Medium (unit conversion + NetCDF restructure) |
| Forcing (Global) | MSWX 0.1 deg, 3-hourly | `mswx_to_mhm_forcing.py` | Medium |
| Observed Q | GRDC-Caravan / HYDAT | `prepare_mhm_gauge.py` | Low (format conversion) |
| LAI | AVHRR or MODIS | `generate_lai_classes.py` | Medium (classification) |

### 8.2 New Data Source Required: GLiM

mHM uniquely requires **geology** data for baseflow parameterization. HydroCraft already has GLiM (Global Lithological Map) mentioned in CLAUDE.md for MODFLOW K validation. The mapping from GLiM lithology classes to mHM geology classes needs to be developed:

| GLiM Class | mHM Geology Interpretation | Baseflow Behavior |
|-----------|---------------------------|-------------------|
| Unconsolidated sediments | High permeability | High baseflow, slow recession |
| Siliciclastic sedimentary | Medium permeability | Moderate baseflow |
| Carbonate sedimentary | Karstic (special handling) | Very high baseflow, rapid recession |
| Mixed sedimentary | Medium permeability | Moderate |
| Volcanic (basic) | Low-medium permeability | Low baseflow |
| Volcanic (acid) | Low permeability | Very low baseflow |
| Plutonic | Very low permeability | Minimal baseflow |
| Metamorphic | Low permeability | Low baseflow |

### 8.3 Cross-Model Comparison

| Comparison | Purpose | Method |
|-----------|---------|--------|
| mHM vs VIC | Process representation difference | Compare Q, ET, SM at same resolution on Bengbu |
| mHM vs Raven | Lumped vs distributed for small basins | Compare on Koksilah (229 km2) |
| mHM vs wflow | Grid-based distributed comparison | Compare on Chaohe (~8,800 km2) |
| mHM ungauged vs VIC calibrated | MPR transfer value | Compare on held-out basin |

### 8.4 Output Coupling

| mHM Output | Downstream Model | Coupling |
|-----------|-----------------|---------|
| Total runoff (L1_total_runoff) | CaMa-Flood | mHM runoff -> CaMa-Flood inundation |
| Soil moisture (L1_soilMoist) | DSSAT/WOFOST | Soil moisture for crop models |
| Actual ET (aET) | MODIS validation | Compare with remote sensing |
| Baseflow (L1_baseflow) | MODFLOW | Recharge for groundwater model |

---

## 9. Validation Plan

### Step 1: Developer Data Test

Run mHM with the included `test_domain` (Mosel basin, Germany):
- Execute: `./mhm` in test_domain directory
- Verify: output_b1/ contains NetCDF files
- Check: simulated Q at gauge 398 matches expected values from test
- Status target: `binary_only`

### Step 2: Progressive Data Replacement on Bengbu

Replace developer data one component at a time with HydroCraft data:

| Replacement Order | Component | HydroCraft Source | Verify After |
|-------------------|----------|------------------|-------------|
| 1 | DEM | China DEM 90m | Flow direction + accumulation physically reasonable |
| 2 | Soil | HWSD global | Soil moisture dynamics reasonable |
| 3 | Land cover | AVHRR 1km | ET partitioning reasonable |
| 4 | Forcing | CMFD | Precipitation/temperature time series correct |
| 5 | Gauge | data/obs/ Bengbu | Performance metrics computable |

Status target: `full_replacement`

### Step 3: Full HydroCraft Data Run -- Bengbu

- Basin: Bengbu (32.94N, 117.35E), ~121,330 km2, humid subtropical
- Period: 2005-2015 (calibration), 2000-2004 (validation)
- Resolution: L0=0.01 deg (~1km), L1=0.25 deg (~25km), L11=0.25 deg
- Forcing: CMFD
- Expected: NSE > 0.5 (uncalibrated), NSE > 0.7 (after calibration)
- Status target: `production_validated`

### Step 4: MPR Transfer Test (The Real Proof)

This is the test that ONLY mHM can do:

1. Calibrate on Bengbu (Huai River) -- get global parameters
2. Apply global parameters to Chaohe (semi-humid North China, ~8,800 km2) WITHOUT recalibration
3. Compare mHM-ungauged vs VIC-uncalibrated on Chaohe
4. If mHM-ungauged outperforms VIC-uncalibrated, MPR transfer is validated

**Stretch goal**: Multi-basin calibration
1. Calibrate simultaneously on Bengbu + Yajiang + Songhua2 (3 diverse basins)
2. Transfer to Chaohe + Heihe (2 ungauged test basins)
3. Compare all 5 basins' performance

---

## 10. Estimated Effort

### Phase 1: Installation & Binary Verification (1 day)
- Install dependencies, build mHM from source
- Run test_domain, verify output
- Document any build issues as triplets

### Phase 2: Pipeline Mapping & Knowledge Classification (1 day)
- Map all 12 stages with dependencies
- Classify knowledge per stage
- Generate pipeline diagram and workflow.md

### Phase 3: Tool Extraction -- P0 tools (5-7 days)
- s2_morphology tools (most complex, 1,650 lines): 3 days
  - hwsd_to_mhm_soil.py is the hardest tool (HWSD class mapping + horizon extraction)
  - glim_to_mhm_geology.py requires understanding GLiM -> mHM mapping
  - D8 flow direction encoding needs source code verification
- s4_forcing tools (850 lines): 1-2 days
- s0/s1/s5/s6/s7 tools (1,900 lines): 1-2 days

### Phase 4: Skill Documents (2-3 days)
- 12 skill documents
- sd04 (MPR methodology) and sd11 (regionalization guide) are the most important

### Phase 5: Diagnostic Triplets (1-2 days)
- Build initial 23 triplets from known patterns
- Add more during validation

### Phase 6: Validation (3-5 days)
- Step 1 (developer test): 0.5 day
- Step 2 (progressive replacement): 2-3 days (most time spent debugging soil/geology mapping)
- Step 3 (full Bengbu run): 1 day
- Step 4 (MPR transfer test): 1 day

### Phase 7: P1/P2 Tools -- Calibration & Regionalization (3-4 days)
- Calibration tools and workflow
- Cross-validation framework
- Multi-basin setup

**Total estimated effort: 16-23 days**

### Effort Breakdown by Deliverable

| Deliverable | Count | Lines/Words | Days |
|------------|-------|-------------|------|
| Validated tools | 32 | ~7,450 lines | 8-11 |
| Skill documents | 12 | ~18,000 words | 2-3 |
| Diagnostic triplets | 23+ | ~1,500 lines | 1-2 |
| Validation runs | 4 steps | -- | 3-5 |
| Pipeline docs | 2 (drawio + md) | -- | 0.5 |
| **Total** | -- | -- | **16-23** |

---

## 11. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| D8 flow direction convention mismatch | High | Fatal (zero discharge) | Read mHM Fortran source for D8 encoding before building tools |
| HWSD -> mHM soil class mapping incorrect | High | Silent error (wrong parameters) | Validate against test_domain soil classes; use mHM's soil_classdefinition format documentation |
| GLiM lithology not available for all basins | Medium | Missing baseflow parameters | Provide fallback geology class for unmapped regions |
| mHM resolution specified in meters, not degrees | Medium | Wrong grid spacing | All tools must handle degree-to-meter conversion (at basin centroid latitude) |
| FORCES library download fails | Medium | Build fails | Pre-clone FORCES repository |
| Multi-basin calibration requires extensive compute | Low | Slow calibration | Start with single-basin, graduate to multi-basin |
| mHM Fortran source incompatible with system gfortran | Low | Build fails | Use conda environment with pinned compiler |

---

## 12. Key Differentiators for HydroCraft Paper

mHM adds these unique capabilities to the HydroCraft platform:

1. **Prediction in Ungauged Basins (PUB)**: No other HydroCraft model can predict discharge in ungauged basins without recalibration. mHM + MPR makes this possible.

2. **Multi-Resolution Flexibility**: mHM handles L0 (1km) to L1 (25km) upscaling internally via transfer functions. No need to pre-process data to model resolution.

3. **Built-In Calibration**: Unlike VIC/WRF-Hydro which need external calibration wrappers, mHM has DDS/SCE built in.

4. **Multi-Basin Simultaneous Calibration**: Calibrate one parameter set across multiple basins -- produces more robust, transferable parameters.

5. **Physics-Based Regionalization**: Unlike statistical regionalization (e.g., regression on catchment attributes), MPR uses pedotransfer functions with physical meaning. This makes it more robust outside the calibration domain.

6. **Cross-Model Benchmarking**: mHM on the same basin as VIC provides a rigorous comparison of parameter approaches (per-cell calibration vs. MPR transfer functions).

---

## Appendix A: Key File Formats Reference

### ESRI ASCII Grid (.asc)
```
ncols         10
nrows         8
xllcorner     113.000
yllcorner     31.000
cellsize      0.01
NODATA_value  -9999
100 102 105 ...
```

### Soil Class Definition (soil_classdefinition.txt)
```
nSoil_Horizons  classID  Bd_1  Bd_2  sand_1  sand_2  clay_1  clay_2  OM_1  OM_2
2  1  1.3  1.4  45  40  20  25  2.0  1.5
2  2  1.5  1.6  60  55  15  20  1.5  1.0
...
```
Where: Bd = bulk density (g/cm3), sand/clay = percentage, OM = organic matter (%)

### Geology Class Definition (geology_classdefinition.txt)
```
classID  Karstic
1  0
2  0
3  1
```

### Gauge Data (GGGGG.txt)
```
1990  1  1  12.5
1990  1  2  15.3
...
```
Columns: YYYY MM DD Q(m3/s), NODATA = -9999

### mhm_parameter.nml Entry Format
```fortran
! parameter_name = lower, upper, value, FLAG, SCALING
canopyInterceptionFactor = 0.15, 0.40, 0.15, 1, 1
```
FLAG: 0=fixed, 1=optimize; SCALING: 1=linear, 2=log

---

## Appendix B: MPR Transfer Function Examples

### Porosity (from Zacharias et al., 2007)
```
porosity = a1 + a2 * sand_fraction + a3 * clay_fraction + a4 * bulk_density
```
Where a1-a4 are global parameters calibrated by mHM.

### Field Capacity
```
FC = b1 + b2 * clay_fraction + b3 * bulk_density + b4 * organic_matter
```

### Permanent Wilting Point
```
PWP = c1 + c2 * sand_fraction + c3 * clay_fraction
```

### Saturated Hydraulic Conductivity
```
log(Ksat) = d1 + d2 * sand_fraction + d3 * clay_fraction + d4 * bulk_density
```

### Degree-Day Factor
```
DDF(x) = e1 * [1 + e2 * (elevation(x) - mean_elevation)] * land_use_factor(x)
```
Where the land_use_factor differs for forest, impervious, and pervious surfaces.

### Baseflow Recession
```
k_baseflow(x) = GeoParam(geology_class(x))
```
Each geology class has its own recession constant (GeoParam array).

**These transfer functions are the heart of MPR.** The global parameters (a1-a4, b1-b3, etc.) are what gets calibrated. The local physiographic data (sand%, clay%, bulk_density, elevation, geology_class) provides spatial heterogeneity. This separation is what enables transferability.

---

## Appendix C: Comparison with Existing Dissected Models

| Metric | VIC | WRF-Hydro | Raven | **mHM (planned)** |
|--------|-----|-----------|-------|-------------------|
| Tools | 18 | 11 | 10 | 32 |
| Skill docs | 7 | 11 | 8 | 12 |
| Triplets | 27 | 31 | ~20 | 23+ |
| Code lines | ~5,300 | ~5,173 | ~3,500 | ~7,450 |
| Unique capability | Energy balance | Coupled LSM | Multi-structure | MPR regionalization |
| Build complexity | Medium | High | Low | Medium |
| Validation basin | Bengbu | Bengbu + Chaohe | Bengbu | Bengbu + ungauged transfer |
