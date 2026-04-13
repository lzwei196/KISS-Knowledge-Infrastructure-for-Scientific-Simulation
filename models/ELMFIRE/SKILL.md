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

# ELMFIRE (Eulerian Level Set Model of FIRE Spread) — Knowledge Infrastructure

**Package**: `wildfire-elmfire` v1.0.0
**Model**: ELMFIRE 2025.1002
**Created by**: Knowledge Dissection Toolkit
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 20 diagnostic triplets | ~1,500 lines of validated Python
**Validation status**: `tutorial_validated` (Tutorial 01 — Constant Wind)

---

## Overview

This knowledge infrastructure enables autonomous wildfire spread simulation using ELMFIRE on any landscape, **without manual data preparation**. The 4 validated tools replace the standard shell-script workflow with a Python pipeline that generates GeoTIFF inputs, configures Fortran namelists, executes the model, and parses outputs.

**What ELMFIRE does**: 2D Eulerian level-set wildfire spread model. Simulates:
- Fire perimeter propagation (level-set equations on raster grid)
- Surface fire spread (Rothermel model with 304 fuel models)
- Crown fire initiation and spread (Van Wagner / Cruz-Alexander)
- Ember transport and spot fire ignition (UMD physics-based model)
- Fire behavior metrics: rate of spread, flame length, fireline intensity
- Monte Carlo burn probability (hundreds of ensemble members)
- Smoke emissions and PM2.5 yield (optional)
- Suppression / initial attack modeling (optional)

**Key difference from other wildfire models**: ELMFIRE is grid-based (Eulerian), not perimeter-tracking (Lagrangian like FARSITE). It uses level-set methods for robust topology changes (merging fires, islands) and scales efficiently with MPI parallelism.

**Reference**: Lautenberger, C. (2013). Wildland fire modeling with an Eulerian level set method and automated calibration. *Fire Safety Journal*, 62, 289–298. https://doi.org/10.1016/j.firesaf.2013.08.014

---

## Installation

### Binary

```
ELMFIRE:      build/linux/bin/elmfire_2025.1002
Post:         build/linux/bin/elmfire_post_2025.1002
Platform:     Linux x86-64, MPI-parallel (OpenMPI)
Source:       github.com/lautenberger/elmfire
```

### Build from source

```bash
cd build/linux
./make_gnu.sh   # Produces 6 binaries in bin/
```

### Dependencies

```
gfortran >= 9, libopenmpi-dev, openmpi-bin
gdal-bin (gdal_calc.py, gdalwarp, gdal_translate, gdal_contour, gdalinfo)
jq, bc, csvkit, pigz
Python 3: google-api-python-client, grpcio, python-dateutil (for CloudFire)
```

### Docker

```bash
docker build -t elmfire .
docker-compose up
```

### Quick test

```bash
cd tutorials/01-constant-wind
./01-run.sh
# Produces: outputs/time_of_arrival*.tif, spread_rate*.tif, flin*.tif
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 1 | Landscape data | `convert_landscape_to_elmfire.py` | Fuel, topography, canopy GeoTIFFs |
| 2 | Weather forcing | `convert_weather_to_elmfire.py` | Wind speed/dir, fuel moisture GeoTIFFs |
| 3 | Ignition setup | (in namelist) | Point coords, CSV file, or probability mask |
| 4 | Namelist config | `convert_weather_to_elmfire.py` | Generate elmfire.data (Fortran namelist) |
| 5 | Execution | `run_elmfire.py` | Preflight checks → mpirun → output validation |
| 6 | Post-processing | `elmfire_post` binary | Ensemble aggregation, burn probability |
| 7 | Output analysis | `parse_elmfire_output.py` | Extract CSV time series, compute metrics |

---

## Unit Trap Table (CRITICAL — silent errors if wrong)

These are the most dangerous unit mismatches in ELMFIRE. Getting any of these wrong produces plausible but incorrect results with **no error message**.

| Variable | ELMFIRE expects | Common source | Trap | Symptom |
|----------|----------------|---------------|------|---------|
| Wind speed | **mph at 20 ft** | m/s at 10 m | ×2.237 for m/s→mph, ×1.15 for 10m→20ft | Fire too slow (m/s) or too fast (knots) |
| Wind direction | **degrees, met convention** (direction FROM) | math convention (direction TO) | Add 180° if "to" convention | Fire spreads opposite to observed |
| Dead fuel moisture (M1,M10,M100) | **percent** (e.g., 5.0) | fraction (0.05) | ×100 if fraction | No fire (fraction) or instant crown fire (wrong %) |
| Live fuel moisture (MLH,MLW) | **percent** (e.g., 60.0) | fraction (0.60) | ×100 if fraction | Fire too intense or nonexistent |
| Slope | **degrees** (0–90) | percent rise or radians | Convert: degrees = atan(rise/100)×180/π | Wild spread rates on steep terrain |
| Aspect | **degrees** (0=N, 90=E, 180=S) | 0=E mathematical | Rotate: aspect_geo = 90 - aspect_math | Wrong solar heating, affects diurnal |
| Canopy base height | **meters ×10** (integer) | meters | Multiply by 10 when CBH_TIMES_10=.TRUE. | Crown fire threshold wrong |
| Canopy bulk density | **kg/m³ ×100** (integer) | kg/m³ | Multiply by 100 when CBD_TIMES_100=.TRUE. | Crown fire intensity wrong |
| Canopy cover | **percent** (0–100) | fraction (0–1) | ×100 if CC_IN_PERCENT=.TRUE. | No crown fire (fraction treated as %) |
| Canopy height | **meters ×10** (integer) | meters | Multiply by 10 when CH_TIMES_10=.TRUE. | WAF calculation wrong |
| Domain coordinates | **UTM meters** | lat/lon degrees | Must reproject to UTM zone EPSG | Tiny domain or domain in wrong location |
| Simulation time | **seconds** | hours or minutes | ×3600 for hours | Fire stops too early |
| DTDUMP | **seconds** | hours | ×3600 | No output or too many files |
| Cell size | **meters** | feet or km | 1 km = 1000 m | Resolution completely wrong |
| Fireline intensity output | **kW/m** | BTU/ft/s | ×3.46 from BTU/ft/s | Misinterpret severity |
| Spread rate output | **ft/min** | m/s or chains/hr | ×0.3048/60 to m/s | Misinterpret ROS values |
| Flame length output | **feet** | meters | ×0.3048 to meters | Misinterpret for suppression thresholds |

---

## Input File Reference

### Namelist file (elmfire.data)

Fortran 90 namelist format with 10 groups:

```fortran
&INPUTS
FUELS_AND_TOPOGRAPHY_DIRECTORY = './inputs'
ASP_FILENAME  = 'asp'       ! Aspect (degrees, 0=N)
SLP_FILENAME  = 'slp'       ! Slope (degrees)
DEM_FILENAME  = 'dem'       ! Elevation (meters)
FBFM_FILENAME = 'fbfm40'    ! Fuel model code (FBFM40, 0-303)
ADJ_FILENAME  = 'adj'       ! Spread rate adjustment factor (-)
PHI_FILENAME  = 'phi'       ! Level set initial field (1.0=unburned)
CBD_FILENAME  = 'cbd'       ! Canopy bulk density (100*kg/m³)
CBH_FILENAME  = 'cbh'       ! Canopy base height (10*m)
CC_FILENAME   = 'cc'        ! Canopy cover (percent)
CH_FILENAME   = 'ch'        ! Canopy height (10*m)
WEATHER_DIRECTORY = './inputs'
WS_FILENAME   = 'ws'        ! Wind speed (mph at 20ft)
WD_FILENAME   = 'wd'        ! Wind direction (degrees, met convention)
M1_FILENAME   = 'm1'        ! 1-hr dead fuel moisture (percent)
M10_FILENAME  = 'm10'       ! 10-hr dead fuel moisture (percent)
M100_FILENAME = 'm100'      ! 100-hr dead fuel moisture (percent)
LH_MOISTURE_CONTENT = 30.0  ! Live herbaceous moisture (percent)
LW_MOISTURE_CONTENT = 60.0  ! Live woody moisture (percent)
DT_METEOROLOGY = 3600.0     ! Weather update interval (seconds)
/

&OUTPUTS
OUTPUTS_DIRECTORY    = './outputs'
DTDUMP               = 3600.   ! Output interval (seconds)
DUMP_FLIN            = .TRUE.  ! Fireline intensity
DUMP_SPREAD_RATE     = .TRUE.  ! Rate of spread
DUMP_TIME_OF_ARRIVAL = .TRUE.  ! Fire arrival time
DUMP_FLAME_LENGTH    = .FALSE. ! Flame length
DUMP_CROWN_FIRE      = .FALSE. ! Crown fire flag
DUMP_FIRE_SIZE_STATS = .TRUE.  ! Cumulative area CSV
CONVERT_TO_GEOTIFF   = .TRUE.  ! Auto-convert BIL to GeoTIFF
/

&COMPUTATIONAL_DOMAIN
A_SRS = 'EPSG: 32610'                    ! Spatial reference (UTM zone)
COMPUTATIONAL_DOMAIN_CELLSIZE = 30.0      ! Cell size (meters)
COMPUTATIONAL_DOMAIN_XLLCORNER = -6000.0  ! Lower-left X (UTM meters)
COMPUTATIONAL_DOMAIN_YLLCORNER = -6000.0  ! Lower-left Y (UTM meters)
/

&TIME_CONTROL
SIMULATION_DT    = 30.0     ! Time step (seconds, adaptive)
SIMULATION_DTMAX = 600.0    ! Max time step (seconds)
SIMULATION_TSTOP = 21600.0  ! End time (seconds)
TARGET_CFL       = 0.4      ! CFL stability number
/

&SIMULATOR
NUM_IGNITIONS = 1
X_IGN(1) = 0.0       ! Ignition UTM easting (meters)
Y_IGN(1) = 3000.0    ! Ignition UTM northing (meters)
T_IGN(1) = 0.0       ! Ignition time (seconds from start)
/

&MISCELLANEOUS
PATH_TO_GDAL = '/usr/bin'
SCRATCH      = './scratch'
/
```

### Input raster format

- **Format**: GeoTIFF (`.tif`) or ENVI BIL (`.bil` + `.hdr`)
- **Data types**: Float32 for continuous, Int16 for categorical
- **NODATA**: -9999
- **CRS**: Must match `A_SRS` in namelist (typically UTM)
- **Resolution**: Must match `COMPUTATIONAL_DOMAIN_CELLSIZE`
- **Extent**: Must cover computational domain
- **Bands**: Single-band per time step, or multi-band with DT_METEOROLOGY interval

### Fuel models

304 models from `fuel_models.csv`:
- 0: Non-burnable
- 1–13: Original 13 NFFL models (Anderson 1982)
- 101–189: FBFM40 expanded set (Scott & Burgan 2005)
  - GR1–GR9 (101–109): Grass
  - GS1–GS4 (121–124): Grass-shrub
  - SH1–SH9 (141–149): Shrub
  - TU1–TU5 (161–165): Timber-understory
  - TL1–TL9 (181–189): Timber litter
  - SB1–SB4 (201–204): Slash-blowdown

---

## Output File Reference

### GeoTIFF outputs (in OUTPUTS_DIRECTORY)

| File pattern | Variable | Units | Type |
|---|---|---|---|
| `time_of_arrival_*.tif` | Fire arrival time | seconds | Float32 |
| `spread_rate_*.tif` | Rate of spread | ft/min | Float32 |
| `flin_*.tif` | Fireline intensity | kW/m | Float32 |
| `flame_length_*.tif` | Flame length | feet | Float32 |
| `crown_fire_*.tif` | Crown fire flag | 0/1 | Int16 |
| `velocity_*.tif` | Spread velocity | ft/min | Float32 |
| `hourly_isochrones.shp` | Fire contours | polygon | Shapefile |

### Fire size statistics CSV

```csv
Case,Ensemble_Member,Time(sec),Area(acres),Area(hectares),Perimeter(feet),Perimeter(meters)
1,1,0.0,0.0,0.0,0.0,0.0
1,1,3600.0,125.4,50.8,2341.2,714.0
```

### Postprocessing outputs (from elmfire_post)

- `burn_probability.tif` — fraction of ensemble members that burned each pixel
- `time_of_arrival_pNN.tif` — Nth percentile arrival time
- `fire_size_percentiles.csv` — ensemble fire size distribution

---

## Tool Reference

| Tool | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `convert_landscape_to_elmfire.py` | Generate terrain/fuel/canopy GeoTIFFs | LANDFIRE rasters or raw DEMs | slope, aspect, fbfm, canopy TIFs |
| `convert_weather_to_elmfire.py` | Generate weather GeoTIFFs + namelist | RAWS/HRRR/gridded weather | ws, wd, m1, m10, m100 TIFs + elmfire.data |
| `run_elmfire.py` | Execute ELMFIRE with preflight checks | elmfire.data + input TIFs | All output TIFs + fire_size_stats.csv |
| `parse_elmfire_output.py` | Extract results to CSV, compute metrics | Output TIFs + fire_size_stats.csv | Summary CSV + metrics JSON |

---

## Common Execution Patterns

### Single deterministic fire

```bash
# 1. Prepare inputs
python convert_landscape_to_elmfire.py --dem dem.tif --fuel fbfm40.tif --out ./inputs
python convert_weather_to_elmfire.py --ws 15 --wd 0 --m1 3 --m10 4 --m100 5 --out ./inputs

# 2. Run
python run_elmfire.py --namelist ./inputs/elmfire.data --np 4

# 3. Parse
python parse_elmfire_output.py --outputs_dir ./outputs --out results.csv
```

### Monte Carlo burn probability

```bash
# Set NUM_ENSEMBLE_MEMBERS = 100 and RANDOM_IGNITIONS = .TRUE.
python run_elmfire.py --namelist ./inputs/elmfire.data --np 16
# Post-process
elmfire_post_2025.1002 ./outputs/elmfire_post.data
```

### Docker execution

```bash
docker run -v $(pwd)/inputs:/elmfire/inputs \
           -v $(pwd)/outputs:/elmfire/outputs \
           elmfire mpirun -np 4 elmfire_2025.1002 /elmfire/inputs/elmfire.data
```

---

## Verification Checklist

Before any ELMFIRE run, verify:

1. **CRS consistency**: All rasters and namelist `A_SRS` must use the same UTM zone
2. **Resolution match**: All rasters must have the same cell size as `COMPUTATIONAL_DOMAIN_CELLSIZE`
3. **Extent coverage**: Rasters must fully cover the computational domain
4. **Wind speed units**: Must be mph at 20 ft above vegetation (not m/s, not 10 m)
5. **Moisture units**: Must be percent (3.0 = 3%), not fraction (0.03)
6. **Canopy multipliers**: CBD ×100, CBH ×10, CH ×10 when integer flags are set
7. **Fuel model codes**: Must be valid FBFM40 codes (check against fuel_models.csv)
8. **NODATA**: Must be -9999 in all rasters
9. **Ignition location**: Must fall within domain and on a burnable fuel pixel
10. **Time units**: SIMULATION_TSTOP, DTDUMP, DT_METEOROLOGY all in seconds
