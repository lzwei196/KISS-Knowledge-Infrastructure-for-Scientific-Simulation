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

# Alpine3D Knowledge Infrastructure

- **Package**: hydrocraft-alpine3d-snow
- **Version**: 1.0.0
- **Model**: Alpine3D (with MeteoIO + SNOWPACK)
- **Domain**: Cryosphere — spatially distributed snow, energy balance, and runoff in mountainous terrain
- **Created**: 2026-03-26
- **Tools**: 4 | **Skill Documents**: 5 | **Diagnostic Triplets**: 18 | **Validation**: pending

---

## Overview

Alpine3D is a spatially distributed, three-dimensional model for analyzing and predicting
snow-dominated surface processes in mountainous topography. It couples:

- **MeteoIO** — meteorological data I/O, quality filtering, temporal/spatial interpolation
- **SNOWPACK** — detailed multi-layer snow and soil physics (energy + mass balance)
- **EnergyBalance** — terrain-aware radiation transfer (shading, view factors, terrain reflection)
- **SnowDrift** — wind-driven snow erosion, saltation, suspension, and deposition (optional)
- **Runoff** — integrated surface/soil runoff from snowmelt and rainfall

The model reads meteorological station data (SMET format), a DEM (ARC grid), land-use grids,
and initial snow profiles (.sno), then produces gridded fields of SWE, snow depth, temperature,
radiation, and runoff at configurable time intervals.

Primary applications: snow water resources, avalanche forecasting, climate change impact
assessment, permafrost studies, and ski resort management.

---

## Installation

### Dependencies

| Component | Minimum Version | Purpose |
|-----------|----------------|---------|
| CMake | 3.1+ | Build system |
| C++ compiler | C++11 (g++/clang++) | Compilation |
| MeteoIO | 2.5.1+ | Data I/O and interpolation |
| SNOWPACK | 3.7+ | Snow physics library |
| OpenMP (optional) | — | Shared-memory parallelism |
| MPI (optional) | — | Distributed-memory parallelism |
| Doxygen (optional) | — | Documentation generation |

### Build from Source

The source tree must have MeteoIO, SNOWPACK, and Alpine3D as siblings:

```
Source/
├── meteoio/
├── snowpack/
└── alpine3d/
```

**Build sequence** (MeteoIO → SNOWPACK → Alpine3D):

```bash
# 1. Build MeteoIO
cd Source/meteoio && mkdir build && cd build
cmake .. && make -j$(nproc) && sudo make install

# 2. Build SNOWPACK
cd ../../snowpack && mkdir build && cd build
cmake .. && make -j$(nproc) && sudo make install

# 3. Build Alpine3D
cd ../../alpine3d && mkdir build && cd build
cmake .. -DOPENMP=ON   # add -DMPI=ON for cluster support
make -j$(nproc) && sudo make install
```

### Binary Location

After build: `alpine3d/build/bin/alpine3d`
After install: `$(prefix)/bin/alpine3d` (default `/usr/local/bin/alpine3d`)

### Test

```bash
cd alpine3d/tests/simple
PROG_ROOTDIR=../../build ./run_simple.sh
# Runs 3-month Dischma simulation, compares with reference output
```

---

## Pipeline Stages

| # | Stage | Tool | Description |
|---|-------|------|-------------|
| s0 | Configuration | — | Create working directory structure and io.ini |
| s1 | DEM preparation | — | Prepare ARC-format DEM and land-use grids |
| s2 | Meteorological forcing | `convert_forcing_to_smet.py` | Convert global/reanalysis data to SMET format |
| s3 | Initial snow profiles | `generate_sno_files.py` | Generate .sno files for each grid cell |
| s4 | Spatial interpolation config | — | Configure [Interpolations2D] in io.ini |
| s5 | Execution | `run_alpine3d.py` | Run alpine3d binary with proper options |
| s6 | Output parsing | `parse_alpine3d_output.py` | Extract gridded results to CSV/analysis format |
| s7 | Validation | — | Compare SWE/HS against observations |

**Parallelism notes**: Stages s2 and s3 can run in parallel. Stage s5 supports OpenMP
(shared memory) and MPI (distributed memory) parallelism for the energy balance and
snowpack computations.

---

## Tools Reference

| Tool | Stage | Script | Lines | Purpose |
|------|-------|--------|-------|---------|
| convert_forcing_to_smet | s2 | `tools/convert_forcing_to_smet.py` | ~280 | Convert meteo data to SMET format with unit corrections |
| generate_sno_files | s3 | `tools/generate_sno_files.py` | ~220 | Create initial snow/soil profiles per pixel |
| run_alpine3d | s5 | `tools/run_alpine3d.py` | ~180 | Execution wrapper with config validation |
| parse_alpine3d_output | s6 | `tools/parse_alpine3d_output.py` | ~250 | Parse ARC grid outputs to CSV time series |

---

## Unit Trap Table

**CRITICAL**: Alpine3D uses SI/MKSA units internally. The most common cause of silent model
failure is feeding data in wrong units. The table below documents every conversion trap:

| Variable | Alpine3D Unit | Common Source Unit | Conversion | Trap ID |
|----------|--------------|-------------------|------------|---------|
| Air temperature (TA) | Kelvin (K) | Celsius (°C) | +273.15 | dt_001 |
| Relative humidity (RH) | Fraction (0–1) | Percent (0–100) | ÷100 | dt_002 |
| Wind speed (VW) | m/s | km/h | ÷3.6 | dt_003 |
| Wind direction (DW) | Degrees from N (0–360) | Radians | ×(180/π) | dt_004 |
| Precipitation (PSUM) | kg/m² (mm water equiv.) | m | ×1000 | dt_005 |
| Pressure (P) | Pa | hPa/mbar | ×100 | dt_006 |
| Incoming SW radiation (ISWR) | W/m² | MJ/m²/day | ×11.574 (÷86400×1e6) | dt_007 |
| Incoming LW radiation (ILWR) | W/m² | MJ/m²/day | ×11.574 | dt_008 |
| Snow height (HS) | m | cm | ÷100 | dt_009 |
| Layer thickness (.sno) | m | cm or mm | ÷100 or ÷1000 | dt_010 |
| Grain radius (rg in .sno) | mm | µm | ÷1000 | dt_011 |
| Soil density | kg/m³ | g/cm³ | ×1000 | dt_012 |
| Geothermal heat (GEO_HEAT) | W/m² | mW/m² | ÷1000 | dt_013 |
| Roughness length | m | mm | ÷1000 | dt_014 |
| Timestep (CALCULATION_STEP_LENGTH) | minutes | seconds | ÷60 | dt_015 |

---

## Configuration Reference (io.ini)

### [General]
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| BUFFER_SIZE | int | 370 | Data buffer size in days |
| BUFF_BEFORE | float | 1.5 | Buffer before start date (days) |

### [Input]
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| COORDSYS | string | — | Coordinate system (CH1903, UTM, etc.) |
| TIME_ZONE | float | 0 | Time zone offset from UTC |
| METEO | string | SMET | Meteorological input format |
| METEOPATH | path | — | Path to meteo files |
| STATION1..N | string | — | Station identifiers |
| SNOW | string | SMET | Snow profile format |
| SNOWPATH | path | — | Path to initial .sno files |
| DEM | string | ARC | DEM format |
| DEMFILE | path | — | Path to DEM grid |
| LANDUSE | string | ARC | Land use format |
| LANDUSEFILE | path | — | Path to land use grid |
| POI | string | SMET | Points of interest format |
| POIFILE | path | — | Path to POI file |

### [Output]
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| GRIDS_WRITE | bool | FALSE | Write gridded output |
| GRIDS_DAYS_BETWEEN | float | 1.0 | Grid output interval (days) |
| GRIDS_PARAMETERS | string | — | Space-separated list (HS SWE TA ISWR...) |
| GRID2D | string | ARC | Grid output format |
| GRID2DPATH | path | — | Grid output directory |
| TS_WRITE | bool | FALSE | Write time series at POIs |
| TS_DAYS_BETWEEN | float | 1.0 | Time series interval (days) |
| PROF_WRITE | bool | FALSE | Write snow profiles at POIs |
| PROF_DAYS_BETWEEN | float | 1.0 | Profile interval (days) |
| SNOW_WRITE | bool | FALSE | Write full snow state (for restart) |
| SNOW_DAYS_BETWEEN | float | — | Snow state interval (days) |

### [Snowpack]
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| CALCULATION_STEP_LENGTH | float | 15 | Timestep in minutes |
| ROUGHNESS_LENGTH | float | 0.002 | Surface roughness (m) |
| HEIGHT_OF_METEO_VALUES | float | 2.0 | Measurement height (m) |
| HEIGHT_OF_WIND_VALUE | float | 10.0 | Wind measurement height (m) |
| ATMOSPHERIC_STABILITY | string | MO_MICHLMAYR | Stability scheme |
| CANOPY | bool | FALSE | Enable canopy model |
| SNP_SOIL | bool | FALSE | Enable soil model |
| SOIL_FLUX | bool | TRUE | Enable soil heat flux |
| GEO_HEAT | float | 0.06 | Geothermal heat flux (W/m²) |
| SW_MODE | string | INCOMING | Shortwave mode (INCOMING/BOTH/REFLECTED) |

### [SnowpackAdvanced]
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ALPINE3D | bool | TRUE | **MUST be TRUE for Alpine3D** |
| SNOW_EROSION | bool | TRUE | Enable wind erosion |
| WATERTRANSPORTMODEL_SNOW | string | BUCKET | Water transport model |
| THRESH_RAIN | float | 1.2 | Rain/snow threshold (K above freezing) |
| LB_COND_WATERFLUX | string | FREEDRAINAGE | Lower boundary condition |

### [EBalance]
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| TERRAIN_RADIATION | bool | TRUE | Enable terrain radiation effects |
| TERRAIN_RADIATION_METHOD | string | SIMPLE | Algorithm (SIMPLE/COMPLEX/HELBIG) |

### [Interpolations2D] — Spatial Interpolation

Algorithms per variable: `VAR::algorithms = ALG1 ALG2 ...`

| Variable | Recommended Algorithms | Notes |
|----------|----------------------|-------|
| TA | ODKRIG_LAPSE, IDW_LAPSE, AVG_LAPSE | Lapse rate ~-0.006 K/m |
| RH | LISTON_RH, IDW_LAPSE | Liston preserves dewpoint |
| PSUM | IDW_LAPSE, AVG_LAPSE | Fractional lapse ~0.0005/m |
| PSUM_PH | PPHASE | Threshold-based phase separation |
| VW, DW | LISTON_WIND | Terrain-adjusted wind |
| ISWR | IDW, AVG | Direct interpolation |
| ILWR | AVG_LAPSE | Rate ~-0.03125 W/m²/m |
| P | STD_PRESS | Barometric formula |

### [Filters] — Input QC

Pattern: `VAR::filterN = TYPE` + `VAR::argN::param = value`

Common filters: `min_max`, `rate`, `mad`, `undercatch_wmo`

### [Generators] — Gap Filling

Pattern: `VAR::generatorN = TYPE`

Common generators: `ALLSKY_LW`, `CLEARSKY_LW`, `ISWR_ALBEDO`

---

## Command-Line Options

```
alpine3d [options]

Required:
  -a, --startdate=YYYY-MM-DDTHH:MM    Simulation start date
  -z, --enddate=YYYY-MM-DDTHH:MM      Simulation end date (or use --steps)
  -i, --iofile=<file>                  Configuration file (default: io.ini)

Optional:
  -n, --steps=<N>                      Number of timesteps (alternative to --enddate)
  -b, --np-ebalance=<N>               Workers for energy balance (default: 1)
  -p, --np-snowpack=<N>               Workers for snowpack (default: 1)
  --enable-eb                          Enable energy balance module
  --restart                            Restart from existing .sno files
  -h, --help                           Display help
```

---

## Input File Formats

### SMET (Swiss Meteorological Exchange Text) — Meteo Data

```
SMET 1.1 ASCII
[HEADER]
station_id       = WFJ2
station_name     = Weissfluhjoch
latitude         = 46.829897
longitude        = 9.809315
altitude         = 2540.0
nodata           = -999
tz               = 1
fields           = timestamp TA RH VW DW ISWR ILWR PSUM HS
[DATA]
2014-10-01T00:00  277.25  0.85  3.2  270  0.0  285.0  0.0  0.0
2014-10-01T01:00  276.80  0.87  2.8  265  0.0  282.0  0.5  0.001
```

### SNO (Initial Snow/Soil Profile)

```
SMET 1.1 ASCII
[HEADER]
station_id       = pixel_001
latitude         = 46.8
longitude        = 9.8
altitude         = 2500
ProfileDate      = 2014-10-01T00:00
nSnowLayerData   = 0
nSoilLayerData   = 3
fields           = timestamp Layer_Thick T Vol_Frac_I Vol_Frac_W Vol_Frac_V Vol_Frac_S Rho_S Conduc_S HeatCapac_S rg rb dd sp mk hr CDot metamo
[DATA]
2014-10-01T00:00  0.5  280.15  0.0  0.25  0.25  0.50  1800  1.5  900  0.3  0.2  0.0  1.0  0  0.0  0.0  0.0
2014-10-01T00:00  0.5  281.15  0.0  0.20  0.30  0.50  1800  1.5  900  0.3  0.2  0.0  1.0  0  0.0  0.0  0.0
2014-10-01T00:00  1.0  282.15  0.0  0.15  0.35  0.50  1800  1.5  900  0.3  0.2  0.0  1.0  0  0.0  0.0  0.0
```

### ARC Grid (DEM, Land Use)

Standard ESRI ARC/INFO ASCII grid:
```
ncols         100
nrows         80
xllcorner     782000
yllcorner     180000
cellsize      25
NODATA_value  -9999
1500 1502 1510 ...
```

### POI (Points of Interest)

```
SMET 1.1 ASCII
[HEADER]
fields = easting northing altitude
[DATA]
785360  182255  2520
786100  181900  2350
```

---

## Output File Formats

### Gridded Output (ARC ASCII)

Written to `GRID2DPATH` at `GRIDS_DAYS_BETWEEN` intervals.

Filename pattern: `YYYYMMDDHHMI_PARAM.asc` (e.g., `201412231200_SWE.asc`)

Key output parameters:
- **HS** — Snow depth (m)
- **SWE** — Snow water equivalent (kg/m²)
- **TA** — Air temperature (K)
- **TSS** — Snow surface temperature (K)
- **ISWR** — Incoming shortwave radiation (W/m²)
- **ILWR** — Incoming longwave radiation (W/m²)
- **MS_SNOWPACK_RUNOFF** — Surface runoff (kg/m²)
- **MS_SOIL_RUNOFF** — Bottom runoff (kg/m²)
- **RSNO** — Snow mean density (kg/m³)
- **ET** — Evapotranspiration (kg/m²)

### Time Series (.met SMET)

At each POI, written at `TS_DAYS_BETWEEN` intervals.
Contains full energy/mass balance terms.

### Profiles (.pro)

Full snow stratigraphy at POI locations.

---

## Critical Domain Knowledge

### 1. ALPINE3D = TRUE is mandatory (dt_016)

In [SnowpackAdvanced], `ALPINE3D` must be set to `TRUE`. If left at `FALSE` (Snowpack standalone
default), the model will run but produce incorrect spatial results because the Snowpack library
will not operate in distributed mode.

### 2. Temperature must be in Kelvin (dt_001)

All temperatures in SMET files must be in Kelvin. Feeding Celsius values creates temperatures
near 0 K internally, causing immediate crashes or physically impossible surface energy balance.

### 3. Precipitation accumulation period must match timestep (dt_015)

`PSUM::RESAMPLE1 = ACCUMULATE` with `PSUM::ARG1::PERIOD` must match `CALCULATION_STEP_LENGTH`.
Mismatches cause either double-counting or loss of precipitation.

### 4. DEM and land-use grids must be co-registered (dt_017)

The DEM and land-use grids must have identical ncols, nrows, xllcorner, yllcorner, and cellsize.
Mismatch causes a cryptic segmentation fault.

### 5. Coordinate system must be consistent (dt_018)

`COORDSYS` in [Input] and [Output] must be the same and must match the actual coordinate system
of the DEM file. Using WGS84 lat/lon with a projected DEM (or vice versa) causes all spatial
interpolation to fail silently.

### 6. SMET timestamps must be ISO 8601

Format: `YYYY-MM-DDTHH:MM` or `YYYY-MM-DDTHH:MM:SS`. Any deviation (e.g., spaces instead of T)
causes MeteoIO to fail to read the file.

### 7. Snow file naming convention

Initial .sno files must follow the naming pattern expected by Alpine3D. Each grid cell requires
a matching .sno file named by its pixel coordinates/ID.

### 8. Energy balance workers vs grid size

Setting `--np-ebalance` higher than the number of grid rows causes a crash. The number of
workers must be ≤ number of DEM rows.

### 9. Relative humidity range trap (dt_002)

RH in SMET must be 0–1 (fraction). Values 0–100 (percent) will be clipped to 1.0 by the
min_max filter, making the entire domain saturated and producing unrealistic snowfall.

---

## Calibration Parameters

| Parameter | Section | Range | Controls | Sensitivity |
|-----------|---------|-------|----------|-------------|
| ROUGHNESS_LENGTH | Snowpack | 0.001–0.01 m | Turbulent exchange | High |
| GEO_HEAT | Snowpack | 0.0–0.1 W/m² | Basal melt rate | Medium |
| THRESH_RAIN | SnowpackAdvanced | 0.5–2.5 K | Rain/snow partitioning | High |
| HEIGHT_OF_METEO_VALUES | Snowpack | 1.5–10 m | Turbulent fluxes | Medium |
| ATMOSPHERIC_STABILITY | Snowpack | — | Stability correction | High |
| TA lapse rate | Interpolations2D | -0.003 to -0.009 K/m | Temperature field | High |
| PSUM lapse rate | Interpolations2D | 0.0001–0.001 /m | Precipitation gradient | High |
| TERRAIN_RADIATION_METHOD | EBalance | SIMPLE/COMPLEX/HELBIG | Radiation accuracy | Medium |

---

## Quick Start

```bash
# 1. Build Alpine3D (from source directory)
cd Source/alpine3d && mkdir build && cd build
cmake .. -DOPENMP=ON && make -j$(nproc)

# 2. Create simulation directory
mkdir -p ~/sim/Dischma/{input/{meteo,surface-grids,snowfiles},output/{grids,snowfiles},setup}

# 3. Prepare forcing data
python tools/convert_forcing_to_smet.py \
  --input era5_data.nc --output ~/sim/Dischma/input/meteo/ \
  --stations WFJ2 DAV --start 2014-10-01 --end 2015-09-30

# 4. Generate initial snow profiles
python tools/generate_sno_files.py \
  --dem ~/sim/Dischma/input/surface-grids/dem.asc \
  --output ~/sim/Dischma/input/snowfiles/ \
  --date 2014-10-01T00:00 --n-soil-layers 3

# 5. Run simulation
python tools/run_alpine3d.py \
  --iofile ~/sim/Dischma/setup/io.ini \
  --startdate 2014-10-01T01:00 --enddate 2015-09-30T00:00 \
  --np-ebalance 4 --np-snowpack 4

# 6. Parse output
python tools/parse_alpine3d_output.py \
  --grid-dir ~/sim/Dischma/output/grids/ \
  --params SWE HS TA --output ~/sim/Dischma/results.csv
```

---

## Diagnostic Triplets Summary

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | silent | unit_conversion | Temperature in °C instead of K |
| dt_002 | silent | unit_conversion | RH in % instead of fraction |
| dt_003 | silent | unit_conversion | Wind speed in km/h instead of m/s |
| dt_004 | silent | unit_conversion | Wind direction in radians |
| dt_005 | silent | unit_conversion | Precipitation in m instead of mm |
| dt_006 | silent | unit_conversion | Pressure in hPa instead of Pa |
| dt_007 | silent | unit_conversion | Radiation in MJ/m²/day instead of W/m² |
| dt_008 | silent | unit_conversion | ILWR in MJ/m²/day instead of W/m² |
| dt_009 | silent | unit_conversion | Snow height in cm instead of m |
| dt_010 | silent | unit_conversion | Layer thickness wrong units in .sno |
| dt_011 | silent | unit_conversion | Grain radius in µm instead of mm |
| dt_012 | silent | unit_conversion | Soil density in g/cm³ instead of kg/m³ |
| dt_013 | silent | unit_conversion | Geothermal heat in mW/m² |
| dt_014 | silent | unit_conversion | Roughness length in mm instead of m |
| dt_015 | degraded | parameter_format | Timestep/accumulation mismatch |
| dt_016 | silent | parameter_format | ALPINE3D = FALSE in SnowpackAdvanced |
| dt_017 | fatal | parameter_format | DEM/landuse grid mismatch |
| dt_018 | silent | parameter_format | Coordinate system mismatch |

---

## File Structure

```
ki/
├── SKILL.md                              # This file
├── tools/
│   ├── convert_forcing_to_smet.py        # Meteo data → SMET format
│   ├── generate_sno_files.py             # Initial snow/soil profiles
│   ├── run_alpine3d.py                   # Execution wrapper
│   └── parse_alpine3d_output.py          # Grid output → CSV
├── docs/
│   ├── s0_domain_setup.md                # Domain and DEM preparation
│   ├── s2_meteorological_forcing.md      # Forcing data preparation
│   ├── s3_initial_conditions.md          # Initial snow/soil profiles
│   ├── s5_execution.md                   # Running Alpine3D
│   └── s6_output_analysis.md             # Output parsing and analysis
└── diagnostics/
    └── triplets.yaml                     # 18 symptom→diagnosis→remedy entries
```
