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

# WRF (Weather Research and Forecasting) Model - Knowledge Infrastructure

## Package Overview

| Field          | Value                                              |
|----------------|----------------------------------------------------|
| Model          | WRF (Advanced Research WRF / ARW)                  |
| Version        | 4.7.1                                              |
| Domain         | Mesoscale atmospheric simulation                   |
| Developer      | NCAR / UCAR / NOAA / AFWA community               |
| License        | Public domain                                      |
| Language       | Fortran 90/2003 with C utilities                   |
| Build System   | CMake (primary) / configure+compile (legacy)       |
| I/O Format     | NetCDF (default), GRIB1/2, HDF5, pnetCDF           |
| Parallelism    | MPI (distributed) + OpenMP (shared memory)         |

## Installation

### Prerequisites

```
# Required
sudo apt-get install -y gfortran gcc g++ cmake make \
  libnetcdf-dev libnetcdff-dev netcdf-bin \
  libopenmpi-dev openmpi-bin \
  libpng-dev libjasper-dev zlib1g-dev m4 csh

# Optional (for parallel I/O and GRIB2)
sudo apt-get install -y libhdf5-openmpi-dev libpnetcdf-dev
```

### CMake Build (Recommended)

```bash
cd /path/to/WRF/source/repo
mkdir _build && cd _build
cmake .. -DCMAKE_INSTALL_PREFIX=../install \
  -DUSE_MPI=ON -DUSE_OPENMP=OFF \
  -DWRF_CASE=EM_REAL -DWRF_NESTING=BASIC
make -j$(nproc)
make install
```

### Legacy Build

```bash
cd /path/to/WRF/source/repo
./configure        # Select compiler + parallelism option
./compile em_real  # Build for real-data case
```

### Executables Produced

| Binary      | Purpose                                           |
|-------------|---------------------------------------------------|
| `wrf.exe`   | Main model integration                            |
| `real.exe`  | Real-data initialization (met_em -> wrfinput/bdy) |
| `ideal.exe` | Idealized-case initialization                     |
| `ndown.exe` | One-way nesting / downscaling utility             |
| `tc.exe`    | Tropical cyclone bogus vortex initialization      |

---

## Pipeline Architecture

The WRF real-data workflow has **9 stages** from raw global data to verified output.

```
Stage 0: Domain Configuration
  |
Stage 1: Geographical Data (geogrid)       [WPS]
  |
Stage 2: Meteorological Forcing (ungrib)   [WPS]
  |
Stage 3: Horizontal Interpolation (metgrid)[WPS]
  |
Stage 4: Vertical Interpolation (real.exe) [WRF]
  |
Stage 5: Namelist Assembly                 [Config]
  |
Stage 6: Model Execution (wrf.exe)         [WRF]
  |
Stage 7: Output Extraction & Analysis      [Post]
  |
Stage 8: Validation & Diagnostics          [Post]
```

### Stage 0 -- Domain Configuration
Define the simulation domain(s): projection, grid spacing, nesting, and time period.
Produces `namelist.wps` for WPS.

### Stage 1 -- Geographical Data (geogrid)
Interpolates static terrestrial fields (terrain, land use, soil type, vegetation) to the model grid.
Produces `geo_em.d0N.nc` files.

### Stage 2 -- Meteorological Forcing (ungrib)
Extracts meteorological fields from GRIB files (GFS, ERA5, NCEP-FNL, etc.) into WPS intermediate format.
Produces `FILE:YYYY-MM-DD_HH` intermediate files.

### Stage 3 -- Horizontal Interpolation (metgrid)
Interpolates meteorological fields horizontally onto the WRF grid.
Produces `met_em.d0N.YYYY-MM-DD_HH:MM:SS.nc` files.

### Stage 4 -- Vertical Interpolation (real.exe)
Interpolates met_em fields vertically onto WRF eta levels, computes base state, and generates boundary conditions.
Produces `wrfinput_d0N` and `wrfbdy_d01`.

### Stage 5 -- Namelist Assembly
Configure `namelist.input` with physics options, dynamics settings, domain dimensions, and output control.

### Stage 6 -- Model Execution (wrf.exe)
Run the atmospheric simulation. Time integration using Runge-Kutta 2nd/3rd order, with time-split acoustic modes.
Produces `wrfout_d0N_YYYY-MM-DD_HH:MM:SS` history files.

### Stage 7 -- Output Extraction & Analysis
Extract variables from wrfout NetCDF files. Compute derived quantities (wind speed, relative humidity, precipitation accumulation).

### Stage 8 -- Validation & Diagnostics
Compare simulated fields against observations. Compute skill metrics (RMSE, bias, correlation).

---

## Unit Trap Table

These are the most dangerous silent-error unit mismatches when preparing WRF input data.

| Variable            | WRF Internal Unit    | Common External Unit   | Trap                                      | Severity |
|---------------------|----------------------|------------------------|--------------------------------------------|----------|
| Temperature         | K (perturbation θ)   | C or F                 | Must convert to potential temp θ-300       | CRITICAL |
| Pressure            | Pa                   | hPa (mb)               | 100x error if hPa not converted to Pa     | CRITICAL |
| Wind (u, v)         | m s⁻¹               | kt, km/h, mph          | Staggered grid: u on X-face, v on Y-face  | HIGH     |
| Mixing ratio (qv)   | kg kg⁻¹             | g kg⁻¹                 | 1000x error if g/kg not divided by 1000   | CRITICAL |
| Geopotential (ph)   | m² s⁻²              | m (height)             | Must multiply height by g=9.81            | CRITICAL |
| Precipitation       | mm (accumulated)     | mm/hr, kg m⁻² s⁻¹     | RAINC+RAINNC for total; reset at intervals| HIGH     |
| Soil moisture       | m³ m⁻³              | mm, % saturation       | Volumetric fraction required              | HIGH     |
| Soil temperature    | K                    | C                      | +273.15 conversion required               | MEDIUM   |
| Latitude            | degrees_north        | radians                | Must be degrees, south is negative        | HIGH     |
| Longitude           | degrees_east         | radians                | Must be degrees, west is negative         | HIGH     |
| Terrain height      | m (MSL)              | ft, km                 | Must be meters above mean sea level       | MEDIUM   |
| Radiation fluxes    | W m⁻²               | MJ m⁻² day⁻¹          | Divide by 86400 then multiply by 1e6      | HIGH     |
| SST                 | K                    | C                      | +273.15; wrflowinp must also be in K      | HIGH     |
| Grid spacing dx/dy  | m                    | km, degrees            | Must be meters for real-data cases        | HIGH     |
| Time step           | s                    | min                    | CFL: dt <= 6*dx(km) for stability         | CRITICAL |

---

## Key Physical Constants (module_model_constants.F)

```fortran
g       = 9.81          ! gravitational acceleration       [m s⁻²]
r_d     = 287.0         ! gas constant dry air             [J K⁻¹ kg⁻¹]
r_v     = 461.6         ! gas constant water vapor         [J K⁻¹ kg⁻¹]
cp      = 1003.5        ! specific heat at const pressure  [J K⁻¹ kg⁻¹]
xlv     = 2.5e6         ! latent heat of vaporization      [J kg⁻¹]
xls     = 2.85e6        ! latent heat of sublimation       [J kg⁻¹]
xlf     = 3.50e5        ! latent heat of fusion            [J kg⁻¹]
p0      = 100000.0      ! reference pressure               [Pa]
t0      = 300.0         ! base-state temperature           [K]
karman  = 0.4           ! von Karman constant              [-]
```

---

## Namelist Reference (namelist.input)

### &time_control
| Parameter             | Type     | Example             | Description                          |
|-----------------------|----------|---------------------|--------------------------------------|
| run_days              | integer  | 3                   | Simulation duration (days)           |
| run_hours             | integer  | 0                   | Simulation duration (hours)          |
| start_year            | integer  | 2020                | Start year (per domain)              |
| start_month           | integer  | 6                   | Start month                          |
| start_day             | integer  | 15                  | Start day                            |
| start_hour            | integer  | 0                   | Start hour (UTC)                     |
| interval_seconds      | integer  | 21600               | Boundary update interval (s)        |
| history_interval      | integer  | 60                  | Output interval (minutes, per domain)|
| io_form_history       | integer  | 2                   | 2=netCDF, 11=pnetCDF                 |
| io_form_input         | integer  | 2                   | Input file format                    |
| io_form_boundary      | integer  | 2                   | Boundary file format                 |

### &domains
| Parameter             | Type     | Example             | Description                          |
|-----------------------|----------|---------------------|--------------------------------------|
| max_dom               | integer  | 2                   | Number of domains                    |
| e_we                  | integer  | 150, 220            | West-east grid points (per domain)   |
| e_sn                  | integer  | 130, 190            | South-north grid points              |
| e_vert                | integer  | 45                  | Vertical levels                      |
| dx                    | real     | 12000., 4000.       | Grid spacing x (meters)             |
| dy                    | real     | 12000., 4000.       | Grid spacing y (meters)             |
| time_step             | integer  | 60                  | Integration timestep (s)            |
| parent_grid_ratio     | integer  | 1, 3                | Nesting ratio (must be odd)          |

### &physics
| Parameter             | Type     | Example | Description                              |
|-----------------------|----------|---------|------------------------------------------|
| mp_physics            | integer  | 8       | Microphysics (8=Thompson)                |
| ra_lw_physics         | integer  | 4       | Longwave radiation (4=RRTMG)            |
| ra_sw_physics         | integer  | 4       | Shortwave radiation (4=RRTMG)           |
| sf_sfclay_physics     | integer  | 1       | Surface layer (1=MM5 similarity)         |
| sf_surface_physics    | integer  | 2       | Land surface (2=Noah LSM)                |
| bl_pbl_physics        | integer  | 1       | PBL scheme (1=YSU)                       |
| cu_physics            | integer  | 1       | Cumulus (1=Kain-Fritsch, 0=off for dx<5km)|
| radt                  | integer  | 15      | Radiation call interval (minutes)        |
| num_soil_layers       | integer  | 4       | Soil layers (must match LSM)             |

### &dynamics
| Parameter             | Type     | Example  | Description                             |
|-----------------------|----------|----------|-----------------------------------------|
| rk_ord                | integer  | 3        | Runge-Kutta order (2 or 3)             |
| diff_opt              | integer  | 2        | Diffusion (1=simple, 2=full)            |
| km_opt                | integer  | 4        | Eddy coefficient (4=horizontal Smagorinsky)|
| non_hydrostatic       | logical  | .true.   | Non-hydrostatic mode                    |
| hybrid_opt            | integer  | 2        | Hybrid vertical coordinate              |

---

## Tool Reference

| Tool Script                    | Lines | Purpose                                   |
|--------------------------------|-------|-------------------------------------------|
| `convert_forcing_to_wrf.py`   | ~350  | Global reanalysis GRIB/NC -> WPS intermediate |
| `convert_soil_to_wrf.py`      | ~250  | HWSD/SoilGrids -> WRF geogrid format     |
| `run_wrf.py`                  | ~200  | Execute real.exe + wrf.exe with checks    |
| `parse_wrfout.py`             | ~280  | Extract wrfout variables to CSV/timeseries|

---

## Critical Domain Knowledge

### 1. Potential Temperature Perturbation
WRF stores perturbation potential temperature `T' = θ - 300 K`. To recover actual temperature:
```
θ = T' + 300
T_actual = θ * (P / P0)^(R_d / c_p)
```
Forgetting the 300 K offset produces temperatures ~300 K too cold.

### 2. Staggered Grid (Arakawa C-grid)
- `u` is on west-east cell faces (staggered in X)
- `v` is on south-north cell faces (staggered in Y)
- `w` and `ph` are on vertical cell faces (staggered in Z)
- Mass variables (T, p, q) are at cell centers
Failing to destagger before comparison causes half-grid-cell spatial shifts.

### 3. Eta Vertical Coordinate
WRF uses terrain-following η levels where η=1 at surface, η=0 at model top.
Pressure at level k: `p(k) = η(k) * (p_sfc - p_top) + p_top`
With hybrid_opt=2, upper levels become isobaric (reduces noise over steep terrain).

### 4. CFL Stability Criterion
Time step must satisfy: `dt <= 6 * dx_km` (rule of thumb).
For dx=12 km, dt should be ~72 s or less. Exceeding this causes model blow-up.

### 5. Cumulus Parameterization at Fine Resolution
Cumulus schemes (cu_physics) should be turned OFF (=0) when dx < 5 km,
as convection becomes grid-resolved. Keeping it on causes double-counting of precipitation.

### 6. Boundary Condition Update Interval
`interval_seconds` in namelist must match the temporal resolution of the driving data.
ERA5 hourly = 3600, GFS 6-hourly = 21600, FNL 6-hourly = 21600.
Mismatch causes interpolation artifacts or runtime crash.

### 7. Nesting Grid Ratio
`parent_grid_ratio` must be an odd integer (3, 5, 7) for real-data cases.
Even ratios cause interpolation errors at nest boundaries.

### 8. Soil Layer Mismatch
`num_soil_layers` must match the land surface model:
Noah=4, RUC=6/9, Noah-MP=4, CLM4=10.
Mismatch causes segfault or garbage soil temperatures.

### 9. Restart File Precision
Restart files must use the same precision (single/double) as the run that created them.
Mixing precisions corrupts the model state silently.

---

## Quick Start (Idealized Baroclinic Wave)

```bash
cd /path/to/WRF/source/repo
mkdir _build && cd _build
cmake .. -DWRF_CASE=EM_B_WAVE
make -j$(nproc)

cd test/em_b_wave/
ln -sf ../../run/*.TBL ../../run/RRTM* .
./ideal.exe
./wrf.exe

# Check output
ncdump -h wrfout_d01_0001-01-01_00:00:00
```

---

## Data Requirements

### Meteorological Forcing (for real-data runs)
- GFS (0.25deg, 6-hourly): https://nomads.ncep.noaa.gov
- ERA5 (0.25deg, hourly): https://cds.climate.copernicus.eu
- NCEP FNL (1deg, 6-hourly): https://rda.ucar.edu

### Static Geographic Data
- WPS geographical data (topo, landuse, soil): https://www2.mmm.ucar.edu/wrf/users/download/get_sources_wps_geog.html
- Resolution options: 30s (~1km), 2m (~4km), 5m (~10km), 10m (~20km)

### Lookup Tables (in run/ directory)
- `LANDUSE.TBL` - Land use categories and parameters
- `VEGPARM.TBL` - Vegetation parameters
- `SOILPARM.TBL` - Soil type parameters
- `GENPARM.TBL` - General land-surface parameters
- `RRTM_DATA` / `RRTMG_*_DATA` - Radiation lookup tables

---

## File Structure

```
ki/
  SKILL.md                          # This file
  tools/
    convert_forcing_to_wrf.py       # Reanalysis -> WPS intermediate format
    convert_soil_to_wrf.py          # Soil/terrain data -> geogrid format
    run_wrf.py                      # Execute real.exe + wrf.exe
    parse_wrfout.py                 # Extract wrfout to CSV
  docs/
    s0_domain_configuration.md      # Domain setup skill
    s1_geographical_data.md         # Geogrid skill
    s2_meteorological_forcing.md    # Ungrib skill
    s4_vertical_interpolation.md    # real.exe skill
    s5_namelist_assembly.md         # Namelist configuration skill
    s6_model_execution.md           # wrf.exe skill
    s7_output_extraction.md         # Post-processing skill
  diagnostics/
    triplets.yaml                   # Symptom-diagnosis-remedy triplets
```
