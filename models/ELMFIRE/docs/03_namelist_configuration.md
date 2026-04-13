# Stage 3: Namelist Configuration

## Purpose

Assemble the ELMFIRE Fortran namelist file (`elmfire.data`) that controls all simulation parameters — domain definition, time stepping, fire behavior options, output selection, and ignition specification.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Landscape rasters | Stage 1 output | Location and filenames of terrain/fuel/canopy TIFs |
| Weather rasters | Stage 2 output | Location and filenames of weather TIFs |
| Domain bounds | User specification | UTM coordinates of computational domain |
| Ignition info | User specification | UTM coordinates, time, or probability mask |
| Simulation params | User specification | Duration, time step, output frequency |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `elmfire.data` | Fortran namelist (text) | Complete simulation configuration |

## Procedure

### Step 1: Define the computational domain

The domain is defined by lower-left corner, cell size, and the raster extent:

```fortran
&COMPUTATIONAL_DOMAIN
A_SRS = 'EPSG: 32610'               ! UTM zone — MUST match raster CRS
COMPUTATIONAL_DOMAIN_CELLSIZE = 30.0  ! meters — MUST match raster resolution
COMPUTATIONAL_DOMAIN_XLLCORNER = -6000.0  ! UTM easting of lower-left (meters)
COMPUTATIONAL_DOMAIN_YLLCORNER = -6000.0  ! UTM northing of lower-left (meters)
/
```

**The domain size is determined by the raster extent**, not by explicit width/height parameters. ELMFIRE reads the raster dimensions to determine the grid.

### Step 2: Configure time control

```fortran
&TIME_CONTROL
SIMULATION_DT    = 30.0     ! Initial time step (seconds) — adaptive via CFL
SIMULATION_DTMAX = 600.0    ! Maximum allowed time step (seconds)
SIMULATION_TSTOP = 21600.0  ! 6 hours in seconds (6 × 3600)
TARGET_CFL       = 0.4      ! CFL number (0.2-0.8, lower = more stable)

! Optional diurnal adjustment
USE_DIURNAL_ADJUSTMENT_FACTOR = .FALSE.
OVERNIGHT_ADJUSTMENT_FACTOR = 0.1  ! Reduce ROS to 10% at night
LATITUDE  = 38.5    ! For sunrise/sunset calculation
LONGITUDE = -120.5  ! Degrees (negative for west)
/
```

### Step 3: Specify ignition

Three ignition methods:

```fortran
&SIMULATOR
! Method 1: Point ignitions (UTM meters)
NUM_IGNITIONS = 1
X_IGN(1) = 725000.0   ! UTM easting (meters)
Y_IGN(1) = 4300000.0  ! UTM northing (meters)
T_IGN(1) = 0.0        ! Time (seconds from SIMULATION_TSTART)

! Method 2: CSV file (lon/lat)
! IGNITIONS_CSV_FILENAME = 'ignitions.csv'
! CSV format: lon,lat,time_utc

! Method 3: Random ignitions (Monte Carlo)
! RANDOM_IGNITIONS = .TRUE.
! RANDOM_IGNITIONS_TYPE = 1  ! 1=uniform, 2=ERC-weighted
/
```

### Step 4: Configure outputs

```fortran
&OUTPUTS
OUTPUTS_DIRECTORY    = './outputs'
DTDUMP               = 3600.0    ! Output every 1 hour (seconds)
DUMP_FLIN            = .TRUE.    ! Fireline intensity (kW/m)
DUMP_SPREAD_RATE     = .TRUE.    ! Rate of spread (ft/min)
DUMP_TIME_OF_ARRIVAL = .TRUE.    ! Fire arrival time (seconds)
DUMP_FLAME_LENGTH    = .TRUE.    ! Flame length (feet)
DUMP_CROWN_FIRE      = .FALSE.   ! Crown fire flag (0/1)
DUMP_FIRE_SIZE_STATS = .TRUE.    ! Area/perimeter CSV
CONVERT_TO_GEOTIFF   = .FALSE.   ! Auto BIL→GeoTIFF conversion
/
```

### Step 5: Fire behavior options

```fortran
&SIMULATOR
! Crown fire
CROWN_FIRE_MODEL = 1               ! 1=default Cruz-Alexander
CRITICAL_CANOPY_COVER = 0.39       ! Min CC fraction for crown fire
FOLIAR_MOISTURE_CONTENT = 100.0    ! Crown fire threshold (percent)

! Wind adjustment
WX_BILINEAR_INTERPOLATION = .TRUE. ! Smooth wind spatial interpolation
WSMFEFF_LOW_MULT = 0.011364        ! Low-wind multiplier

! Spotting (if enabled)
ENABLE_SPOTTING = .FALSE.
USE_UMD_SPOTTING_MODEL = .FALSE.
/
```

### Step 6: Monte Carlo ensemble (optional)

```fortran
&MONTE_CARLO
NUM_ENSEMBLE_MEMBERS = 100
RANDOM_IGNITIONS = .TRUE.
SEED = 2024

! Perturb weather inputs
NUM_RASTERS_TO_PERTURB = 2
RASTER_TO_PERTURB(1) = 'WS'
PDF_TYPE(1) = 'UNIFORM'
PDF_LOWER_LIMIT(1) = -5.0    ! ±5 mph wind speed
PDF_UPPER_LIMIT(1) = 5.0
SPATIAL_PERTURBATION(1) = 'GLOBAL'
TEMPORAL_PERTURBATION(1) = 'STATIC'

RASTER_TO_PERTURB(2) = 'WD'
PDF_TYPE(2) = 'UNIFORM'
PDF_LOWER_LIMIT(2) = -30.0   ! ±30° wind direction
PDF_UPPER_LIMIT(2) = 30.0
SPATIAL_PERTURBATION(2) = 'GLOBAL'
TEMPORAL_PERTURBATION(2) = 'STATIC'
/
```

## Verification

1. **A_SRS matches rasters**: `gdalinfo dem.tif | grep EPSG` must match namelist
2. **Cell size matches rasters**: `gdalinfo dem.tif | grep "Pixel Size"` must match
3. **XLLCORNER/YLLCORNER**: Must match raster lower-left origin
4. **All raster files exist**: Check every *_FILENAME entry has a corresponding .tif
5. **Time units**: SIMULATION_TSTOP, DTDUMP, DT_METEOROLOGY all in **seconds**
6. **Ignition inside domain**: X_IGN/Y_IGN must fall within raster extent
7. **Ignition on burnable fuel**: Check FBFM code at ignition point

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| TSTOP in hours | Simulation ends instantly | Multiply by 3600 |
| DTDUMP in hours | No output files | Multiply by 3600 |
| Ignition in lat/lon | Fire at wrong location | Convert to UTM meters |
| Missing namelist group | Model crash or defaults used | Include all 6 required groups |
| Space in "EPSG: 32610" | Depends on version | Match format from tutorials |
| Wrong XLLCORNER | Domain offset from data | Use raster origin from gdalinfo |

## Example

Complete namelist for Tutorial 01 (constant wind grass fire):

```fortran
&INPUTS
FUELS_AND_TOPOGRAPHY_DIRECTORY = './inputs'
ASP_FILENAME = 'asp'
CBD_FILENAME = 'cbd'
CBH_FILENAME = 'cbh'
CC_FILENAME  = 'cc'
CH_FILENAME  = 'ch'
DEM_FILENAME = 'dem'
FBFM_FILENAME = 'fbfm40'
SLP_FILENAME = 'slp'
ADJ_FILENAME = 'adj'
PHI_FILENAME = 'phi'
DT_METEOROLOGY = 3600.0
WEATHER_DIRECTORY = './inputs'
WS_FILENAME  = 'ws'
WD_FILENAME  = 'wd'
M1_FILENAME  = 'm1'
M10_FILENAME = 'm10'
M100_FILENAME = 'm100'
LH_MOISTURE_CONTENT = 30.0
LW_MOISTURE_CONTENT = 60.0
/

&OUTPUTS
OUTPUTS_DIRECTORY    = './outputs'
DTDUMP               = 3600.
DUMP_FLIN            = .TRUE.
DUMP_SPREAD_RATE     = .TRUE.
DUMP_TIME_OF_ARRIVAL = .TRUE.
CONVERT_TO_GEOTIFF   = .FALSE.
/

&COMPUTATIONAL_DOMAIN
A_SRS = 'EPSG: 32610'
COMPUTATIONAL_DOMAIN_CELLSIZE = 30
COMPUTATIONAL_DOMAIN_XLLCORNER = -6000.0
COMPUTATIONAL_DOMAIN_YLLCORNER = -6000.0
/

&TIME_CONTROL
SIMULATION_DT    = 30.0
SIMULATION_TSTOP = 19800.0
/

&SIMULATOR
NUM_IGNITIONS = 1
X_IGN(1) = 0.0
Y_IGN(1) = 3000.0
T_IGN(1) = 0.0
WX_BILINEAR_INTERPOLATION = .TRUE.
WSMFEFF_LOW_MULT = 0.011364
/

&MISCELLANEOUS
PATH_TO_GDAL = '/usr/bin'
SCRATCH      = './scratch'
/
```
