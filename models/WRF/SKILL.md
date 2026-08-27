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

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (7 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (23 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (19 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing_to_wrf.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_wrf.py --help` |
| `tools/convert_soil_to_wrf.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_wrf.py --help` |
| `tools/parse_wrfout.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_wrfout.py --help` |
| `tools/run_wrf.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_wrf.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# WRF (Weather Research and Forecasting) Model -- Knowledge Infrastructure Skill Document

> **Version**: 4.7.1
> **Domain**: Mesoscale atmospheric simulation
> **Last updated**: 2026-08-18
> **Validation status**: partial_replacement

---

## 1. Model Identity

### Package Overview

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

## 2. What This Model Does

WRF is a nonhydrostatic mesoscale atmospheric model used for numerical weather prediction and regional climate simulation. This KI describes the real-data ARW workflow from static geography and meteorological forcing through `real.exe`, `wrf.exe`, post-processing, and validation against observable atmospheric fields.

## 3. Input Requirements

Exact I/O shapes live in `docs/format_spec.yaml`, projected from `dag.yaml` and `diagnostics/triplets.yaml`; regenerate that spec after changing either source and do not hand-edit it. Real-data runs require WPS geography, gridded meteorological forcing, WRF namelists, and lookup tables in the run directory.

| Input class | Expected source | Tool or component that prepares it |
|-------------|-----------------|------------------------------------|
| Domain and projection | User configuration in `namelist.wps` | WPS `geogrid.exe` / Stage 0 and Stage 1 tools |
| Static geography | WPS geographical data | WPS `geogrid.exe` |
| Meteorological forcing | GFS, ERA5, NCEP FNL, CMFD/MSWX/NASA POWER through KI helpers where applicable | WPS `ungrib.exe` and `metgrid.exe`; `ki_tools_common.load_forcing` for KI forcing loaders |
| Initial and boundary conditions | `met_em` files | WRF `real.exe` |
| Model configuration | `namelist.input` | Stage 5 namelist assembly |

## 4. Build Instructions

### Installation

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

### Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for boundary condition forcing.


## 5. Execution

### Pipeline Architecture

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

## 6. Output Description

Source of truth: `dag.yaml`. The dag defines the model's observable outputs, units, descriptions, and validation rank; if this body ever disagrees with `dag.yaml`, the dag wins.

**Headline output**: `T2` is the dag's rank-1 variable, the output this model is judged by.

> `T2` -- 2-metre air temperature (diagnosed at the surface; already in Kelvin, no base-state offset needed) (`K`)

| Output variable from dag | Validation rank | Unit | Description restated from dag facts |
|--------------------------|-----------------|------|-------------------------------------|
| `T2` | 1 | `K` | 2-metre air temperature (diagnosed at the surface; already in Kelvin, no base-state offset needed) |
| `RAINC+RAINNC` | dag output | see `dag.yaml` | Named by the dag as an additional output |
| `U10/V10` | dag output | see `dag.yaml` | Named by the dag as an additional output |
| `PSFC` | dag output | see `dag.yaml` | Named by the dag as an additional output |
| `T` | dag output | see `dag.yaml` | Named by the dag as an additional output |
| `SWDOWN` | dag output | see `dag.yaml` | Named by the dag as an additional output |
| `TSLB` | dag output | see `dag.yaml` | Named by the dag as an additional output |
| `SMOIS` | dag output | see `dag.yaml` | Named by the dag as an additional output |

## 7. Tool Inventory

| Tool Script                    | Lines | Purpose                                   |
|--------------------------------|-------|-------------------------------------------|
| `convert_forcing_to_wrf.py`   | ~350  | Global reanalysis GRIB/NC -> WPS intermediate |
| `convert_soil_to_wrf.py`      | ~250  | HWSD/SoilGrids -> WRF geogrid format     |
| `run_wrf.py`                  | ~200  | Execute real.exe + wrf.exe with checks    |
| `parse_wrfout.py`             | ~280  | Extract wrfout variables to CSV/timeseries|

### Shared Utilities

Use shared KI utilities instead of writing raw ad hoc extraction or metric code where the toolchain provides them:

```python
from ki_tools_common.load_forcing import load_daily_forcing
from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_forcing_ranges
from ki_tools_common.units import convert
```

## 8. Unit Table

### Unit Trap Table

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

### Output Unit Table

This table records output-unit facts that an agent reading only this body must know before computing metrics. `T2` is not the same as WRF's 3D `T`; `T2` is already Kelvin and needs no 300 K base-state offset.

| Output variable | Unit | Conversion or handling |
|-----------------|------|------------------------|
| `T2` | `K` | Use directly for 2-metre air temperature; no base-state offset needed. |
| `T` | K perturbation potential temperature | Add the 300 K base state before converting to actual temperature. |
| `RAINC+RAINNC` | mm accumulated | Use `RAINC + RAINNC` for total accumulated precipitation; difference consecutive output times for interval precipitation. |
| `PSFC` | Pa | Surface pressure is total pressure in Pa. |
| `U10/V10` | m s⁻¹ | Compare as 10-metre wind components or derive wind speed after confirming observation convention. |
| `SWDOWN` | W m⁻² | Downward shortwave radiation flux. |
| `TSLB` | K | Soil temperature. |
| `SMOIS` | m³ m⁻³ | Volumetric soil moisture. |

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

## 9. Diagnostic Triplets

Check `diagnostics/triplets.yaml` before debugging any failure. These are the first five high-risk entries to check; the YAML remains the complete source of truth.

| ID | Error / symptom | Diagnosis | Remedy |
|----|-----------------|-----------|--------|
| `dt_001` | Surface temperatures in `wrfout` are about 300 K too cold. | 3D `T` was read directly as actual temperature instead of perturbation potential temperature. | Add 300 K to `T` and use pressure conversion for actual temperature; use `T2` directly because it is already in K. |
| `dt_002` | Surface pressure is about 100x too small. | Pressure was read in hPa, or `P` was used without `PB`. | Convert hPa to Pa and use total pressure `P + PB`; `PSFC` is total surface pressure in Pa. |
| `dt_003` | Mixing ratios are 1000x too large. | Humidity or mixing ratio was supplied in g/kg instead of kg/kg. | Divide g/kg values by 1000 before ingestion. |
| `dt_004` | Geopotential height is about 9.81x too large. | ERA5 geopotential in m2/s2 was used where WRF expects height in meters. | Divide ERA5 geopotential by 9.81 to get geopotential height in meters. |
| `dt_005` | Precipitation totals are zero or look like multi-day accumulations. | `RAINC` and `RAINNC` are accumulated from simulation start. | Use `RAINC + RAINNC`, then difference consecutive outputs for interval precipitation. |

## 10. Coupling Interfaces

WRF is commonly used as an atmospheric driver for land, hydrology, air-quality, and post-processing systems. Confirm the exact exchange fields and units against `dag.yaml`, `docs/format_spec.yaml`, and the downstream model before coupling.

| Upstream model or dataset | Variable exchanged | Unit | Temporal resolution |
|---------------------------|-------------------|------|---------------------|
| GFS / ERA5 / NCEP FNL | Meteorological initial and boundary forcing | Dataset-dependent; convert to WRF/WPS expectations | Hourly to 6-hourly depending on dataset |
| WPS geography | Terrain, land use, soil category, vegetation fields | WPS geogrid conventions | Static |

| Downstream model or workflow | Variable exchanged | Unit | Temporal resolution |
|------------------------------|-------------------|------|---------------------|
| Validation workflow | `T2`, `RAINC+RAINNC`, `U10/V10`, `PSFC`, `SWDOWN`, `TSLB`, `SMOIS` | Use dag and output unit table | `history_interval` from `namelist.input` |
| Hydrology or land-surface post-processing | Precipitation, temperature, radiation, wind, pressure | Convert from WRF output conventions before ingest | Model output interval |

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

## 11. Validated Results

Source of truth for validation bars: `docs/validation_convention.yaml`. This section restates the KI's convention facts; it does not invent achieved run metrics. If a convention band is null, write `no cited threshold`.

### Headline Validation Variable

The dag's rank-1 output is `T2`: 2-metre air temperature (diagnosed at the surface; already in Kelvin, no base-state offset needed), unit `K`.

### Performance Metrics -- judged against the field's bar, not intuition

| Dag variable | Metric | Direction | Convention bar | Citation key |
|--------------|--------|-----------|----------------|--------------|
| `T2` | `rmse` | minimize | very_good <= 1.5; good <= 2.0; satisfactory <= 2.5 | `gilliam2010`, `wyszogrodzki2013` |
| `T2` | `r` | maximize | very_good >= 0.99; good >= 0.97; satisfactory >= 0.95 | `katragkou2015` |
| `RAINC+RAINNC` | `nse` | maximize | satisfactory: no cited threshold | none in convention |
| `RAINC+RAINNC` | `mae` | minimize | satisfactory: no cited threshold | none in convention |

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | Pipeline | Pending per run | Validate source units before WPS conversion. |
| Static geography | WPS geographical data | Pending per run | Check terrain, land use, soil categories, and projection. |
| Initial and boundary conditions | `real.exe` from `met_em` | Pending per run | Confirm `wrfinput_d0N` and `wrfbdy_d01` are produced before `wrf.exe`. |
| Output extraction | `wrfout` history files | Pending per run | Extract `T2` directly in K for headline validation. |
| Validation | `docs/validation_convention.yaml` | Pending per run | Apply cited bars above; do not substitute uncited thresholds. |

## 12. Parameter Selection by Region

WRF physics choices are not universal calibration constants. Use documented scheme behavior, forcing resolution, grid spacing, and the target region's terrain and convection regime as physically informed starting points, then validate against the dag-ranked outputs.

| Region or configuration | Key parameters | Rationale |
|-------------------------|----------------|-----------|
| Convection-permitting nests (`dx < 5 km`) | `cu_physics = 0` | Avoid double-counting parameterized and resolved convection. |
| Coarser parent domains (`dx > 10 km`) | Cumulus scheme such as Kain-Fritsch or New Tiedtke when appropriate | Deep convection is not fully resolved. |
| Noah land-surface runs | `sf_surface_physics = 2`, `num_soil_layers = 4` | Soil-layer count must match the land-surface model. |
| Nested real-data domains | Odd `parent_grid_ratio`, commonly 3 or 5 | WRF interpolation expects odd nesting ratios for real-data cases. |
| Any domain | `time_step <= 6 * dx_km` as an upper-bound rule of thumb | Prevent CFL instability; start more conservatively for complex terrain or aggressive physics. |

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
