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

# Noah-MP v5.2 (Noah Multi-Parameterization Land Surface Model) — Knowledge Infrastructure

**Package**: `hydrocraft-noahmp-lsm` v1.0.0
**Model**: Noah-MP v5.2.0 (HRLDAS offline driver)
**Created by**: Auto-dissect pipeline
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 18 diagnostic triplets | ~1,800 lines of validated Python
**Validation status**: `initial` (compilation and structural validation)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/FLUXNET/SKILL.md` for eddy covariance flux observations.


## Overview

This knowledge infrastructure enables autonomous land surface simulation using Noah-MP
(Noah Multi-Parameterization) driven offline via the HRLDAS (High Resolution Land Data
Assimilation System) framework, **without manual data preparation**. The 4 validated tools
replace the standard WRF-preprocessing workflow with a Python pipeline that integrates
with HydroCraft's forcing, soil, and observation infrastructure.

**What Noah-MP does**: Community land surface model simulating coupled energy, water,
and carbon cycles. Key processes:
- Surface energy balance (radiation, sensible/latent heat, ground heat flux)
- Soil water dynamics (Richards equation, multiple infiltration schemes)
- Snow physics (3-layer snowpack, BATS/CLASS/SNICAR albedo, compaction)
- Vegetation phenology (dynamic LAI, stomatal conductance, photosynthesis)
- Runoff generation (TOPMODEL, VIC, BATS, Schaake96, Xinanjiang options)
- Crop modeling (5 crop types, 8 growth stages, irrigation)
- Glacier thermodynamics (phase change, simplified options)
- Carbon/nitrogen cycling (photosynthesis, respiration, NPP)
- Tile drainage and wetland hydrology

**Key difference from other HydroCraft models**: Noah-MP is a column-based LSM that
operates on a 2D grid. Each grid cell is solved independently as a 1D soil-vegetation-
atmosphere column. It couples with WRF (online), HRLDAS (offline), LIS (NASA), and
ERF (DOE) host models. The HRLDAS driver is the standalone offline mode used here.

**Host models**: WRF, HRLDAS, MPAS, WRF-Hydro/NWM, NOAA/UFS, NASA/LIS, DOE/ERF

---

## Installation

### Source

```
Noah-MP v5.2.0:  source/repo/
Repository:      https://github.com/NCAR/noahmp
License:         See LICENSE.txt
Language:        Modern Fortran (F90/F2003/F2008)
```

### Build Requirements

```
Fortran compiler:  gfortran >= 8.0 or ifort >= 19.0
NetCDF-Fortran:    libnetcdff (nf-config --fflags --flibs)
NetCDF-C:          libnetcdf
MPI (optional):    OpenMPI or MPICH (for parallel I/O)
CPP preprocessor:  cpp or fpp
```

### Build Steps (HRLDAS offline driver)

```bash
cd source/repo/drivers/hrldas/
# Edit user_build_options: set compiler, NetCDF paths, flags
cp user_build_options.template user_build_options
# Compile utility, core physics, then driver
make clean && make
# Binary: NoahmpDriverMainMod.exe (or linked name)
```

### Python dependencies (for tools)

```
netCDF4, numpy, pandas, xarray, matplotlib, scipy, PyYAML
```

---

## Pipeline (9 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Basin, period, resolution, paths, physics options |
| 1 | Domain setup | (WPS/manual) | Define grid from DEM, create HRLDAS setup file |
| 2 | Soil parameters | `convert_soil_to_noahmp` | HWSD/SoilGrids to Noah-MP soil types |
| 3 | Vegetation/land cover | (WPS/manual) | MODIS/AVHRR to IVGTYP classification |
| 4 | Meteorological forcing | `convert_forcing_to_noahmp` | CMFD/MSWX/ERA5 to LDASIN NetCDF format |
| 5 | Model parameters | (NoahmpTable.TBL) | Calibrate or use default parameter table |
| 6 | Execution | `run_noahmp` | Compile (if needed) and run HRLDAS binary |
| 7 | Output parsing | `parse_noahmp_output` | Extract variables to CSV/timeseries |
| 8 | Routing (optional) | (external) | Route runoff through river network |

### Parallelism

Stages 1, 2, 3, 4 can run in parallel after stage 0.
Stage 5 depends on 2, 3.
Stage 6 depends on 4, 5.
Stages 7 and 8 depend on 6.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `convert_forcing_to_noahmp` | s4 | `tools/convert_forcing_to_noahmp.py` | ~480 | CMFD/MSWX/ERA5 to LDASIN NetCDF (unit conversions) |
| `convert_soil_to_noahmp` | s2 | `tools/convert_soil_to_noahmp.py` | ~350 | HWSD/SoilGrids to Noah-MP ISLTYP mapping |
| `run_noahmp` | s6 | `tools/run_noahmp.py` | ~320 | Compile, preflight check, execute HRLDAS binary |
| `parse_noahmp_output` | s7 | `tools/parse_noahmp_output.py` | ~400 | Parse LDASOUT NetCDF to CSV timeseries |

**Total**: 4 tools, ~1,550 lines of validated Python code.

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated. Each has a corresponding
diagnostic triplet.

### 1. Temperature forcing is in Kelvin, NOT Celsius (dt_001)

Noah-MP expects T2D (2-m air temperature) in **Kelvin**. CMFD/MSWX provide Celsius.
Conversion: `T_K = T_C + 273.15`. If Celsius is passed directly, the model computes
negative absolute temperatures, produces NaN in saturation vapor pressure, and crashes
or generates wildly wrong fluxes. Always verify T2D > 200 K in forcing files.

### 2. Precipitation rate is mm/s, NOT mm/hr or mm/day (dt_002)

HRLDAS expects RAINRATE in **mm/s** (= kg/m²/s). CMFD gives mm/hr, ERA5 gives m/hr.
Conversion: `mm/hr / 3600 = mm/s`. Off by 3600x if you skip conversion. The model
will produce extreme runoff and soil saturation with no error message.

### 3. Specific humidity, NOT relative humidity (dt_003)

Noah-MP expects Q2D as **specific humidity** in kg/kg (typical range 0.001-0.025).
CMFD provides specific humidity directly. If relative humidity (0-100%) is passed,
the model interprets it as an impossibly high moisture content and produces extreme
latent heat flux.

### 4. Shortwave radiation must be non-negative (dt_004)

SWDOWN must be >= 0 W/m². Temporal interpolation of 3-hourly data can create small
negative values at night. Clip to zero: `SWDOWN = max(0, SWDOWN)`. Negative SW
causes negative albedo calculations and energy balance errors.

### 5. Pressure is in Pascals, NOT hPa/mbar (dt_005)

PSFC must be in **Pa** (typical range 80000-105000 Pa). ERA5 gives Pa directly;
some datasets give hPa. Conversion: `Pa = hPa * 100`. Wrong pressure units cause
incorrect air density, affecting all turbulent flux calculations silently.

### 6. Soil layer depths are NEGATIVE from surface (dt_006)

ZSOIL array values are **negative** (measured downward from surface). For 4 layers
at 0.1, 0.4, 1.0, 2.0 m depth: `ZSOIL = [-0.1, -0.4, -1.0, -2.0]`. The DZS
(thickness) array is positive: `DZS = [0.1, 0.3, 0.6, 1.0]`. Mixing these up
causes incorrect soil heat/water diffusion.

### 7. VEGFRA can be 0-1 or 0-100 depending on source (dt_007)

Vegetation fraction is stored as percentage (0-100) in WRF/HRLDAS input files but
used as fraction (0-1) internally. The driver divides by 100 if max > 1.0. If your
input already has 0-1 fractions, it will be divided again, making all vegetation
effectively zero. Check the range in your setup file.

### 8. NoahmpTable.TBL must match MMINLU in setup file (dt_008)

The parameter table has sections for different vegetation classification systems
(USGS 27-class, MODIFIED_IGBP_MODIS_NOAH 20-class). The MMINLU attribute in the
HRLDAS setup NetCDF file must match. Mismatch causes wrong parameter assignment:
e.g., USGS type 7 (grassland) vs MODIS type 7 (open shrubland).

### 9. Forcing timestep must divide evenly into model timestep (dt_009)

`forcing_timestep` must be an integer multiple of `noah_timestep`. The model reads
one forcing file per forcing_timestep and interpolates. If forcing_timestep=3600
and noah_timestep=1800, forcing is read every 2 model steps. If not evenly
divisible, forcing data alignment drifts silently.

---

## Namelist Reference (`namelist.hrldas`)

The HRLDAS driver reads a single Fortran namelist file with block `&NOAHLSM_OFFLINE`.

### Time and Domain

| Parameter | Type | Default | Unit | Description |
|-----------|------|---------|------|-------------|
| start_year | int | - | - | Simulation start year |
| start_month | int | - | - | Simulation start month |
| start_day | int | - | - | Simulation start day |
| start_hour | int | - | - | Simulation start hour |
| start_min | int | - | - | Simulation start minute |
| khour | int | - | hr | Total simulation length (hours) |
| kday | int | - | day | Total simulation length (days, alternative to khour) |
| forcing_timestep | int | - | s | Forcing data interval |
| noah_timestep | int | 900 | s | Model integration timestep |
| output_timestep | int | 0 | s | Output writing interval |
| NSOIL | int | - | - | Number of soil layers (typically 4) |
| soil_thick_input | real[] | - | m | Soil layer interface depths |

### Input/Output Paths

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| indir | char | '.' | Forcing data directory |
| outdir | char | '.' | Output directory |
| hrldas_setup_file | char | ' ' | HRLDAS setup/init NetCDF file |
| restart_filename_requested | char | ' ' | Restart file path (blank = cold start) |

### Physics Options (30+ switches)

| Parameter | Default | Options | Controls |
|-----------|---------|---------|----------|
| dynamic_veg_option | 4 | 1-7 | Vegetation dynamics |
| canopy_stomatal_resistance_option | 1 | 1-2 | Ball-Berry (1) or Jarvis (2) |
| btr_option | 1 | 1-3 | Soil moisture stress: Noah/CLM/SSiB |
| surface_runoff_option | 3 | 1-8 | SIMGM/SIMTOP/Schaake96/BATS/VIC/XAJ |
| subsurface_runoff_option | 3 | 1-6 | Subsurface runoff scheme |
| surface_drag_option | 1 | 1-2 | M-O (1) or Chen97 (2) |
| frozen_soil_option | 1 | 1-2 | Frozen permeability: NY06/Koren99 |
| radiative_transfer_option | 3 | 1-3 | Canopy radiation transfer |
| snow_albedo_option | 1 | 1-3 | BATS/CLASS/SNICAR albedo |
| pcp_partition_option | 1 | 1-4 | Rain/snow partition |
| soil_data_option | 1 | 1-4 | Soil configuration source |
| crop_option | 0 | 0-1 | Crop model on/off |
| irrigation_option | 0 | 0-3 | Irrigation on/off and method |
| tile_drainage_option | 0 | 0-2 | Tile drainage scheme |
| wetland_option | 0 | 0-2 | Wetland model |

### Forcing Variable Name Mapping

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| forcing_name_T | 'T2D' | K | 2-m air temperature |
| forcing_name_Q | 'Q2D' | kg/kg | 2-m specific humidity |
| forcing_name_U | 'U2D' | m/s | 10-m U wind component |
| forcing_name_V | 'V2D' | m/s | 10-m V wind component |
| forcing_name_P | 'PSFC' | Pa | Surface pressure |
| forcing_name_LW | 'LWDOWN' | W/m² | Downward longwave radiation |
| forcing_name_SW | 'SWDOWN' | W/m² | Downward shortwave radiation |
| forcing_name_PR | 'RAINRATE' | mm/s | Precipitation rate |

---

## Input File Formats

### HRLDAS Setup File (NetCDF)

The setup file defines the domain grid and initial conditions:

```
Global Attributes:
  WEST-EAST_GRID_DIMENSION, SOUTH-NORTH_GRID_DIMENSION
  DX, DY (grid spacing, meters)
  TRUELAT1, TRUELAT2, STAND_LON (map projection)
  MAP_PROJ (1=Lambert, 2=Polar, 3=Mercator, 6=lat-lon)
  MMINLU (vegetation classification: 'USGS' or 'MODIFIED_IGBP_MODIS_NOAH')

2D Variables:
  XLAT(y,x)    — Latitude [degrees]
  XLONG(y,x)   — Longitude [degrees]
  IVGTYP(y,x)  — Vegetation type index (integer)
  ISLTYP(y,x)  — Soil type index (integer)
  TMN(y,x)     — Deep soil temperature [K]
  VEGFRA(y,x)  — Vegetation fraction [%] (0-100)
  LAI(y,x)     — Leaf area index [m²/m²]

3D Variables:
  TSLB(ns,y,x) — Soil temperature [K] per layer
  SMOIS(ns,y,x) — Volumetric soil moisture [m³/m³] per layer
  SNOW(y,x)    — Snow water equivalent [mm]
  CANWAT(y,x)  — Canopy water content [mm]
  TSK(y,x)     — Skin temperature [K]
```

### Forcing Files (LDASIN NetCDF)

One file per forcing timestep, named: `YYYYMMDDHH.LDASIN_DOMAIN1`

```
Variables (2D: y,x):
  T2D      — 2-m air temperature [K]
  Q2D      — 2-m specific humidity [kg/kg]
  U2D      — 10-m U wind [m/s]
  V2D      — 10-m V wind [m/s]
  PSFC     — Surface pressure [Pa]
  SWDOWN   — Shortwave radiation [W/m²]
  LWDOWN   — Longwave radiation [W/m²]
  RAINRATE — Precipitation rate [mm/s]
```

### Parameter Table (NoahmpTable.TBL)

Merged parameter file containing vegetation, soil, and general parameters.
Located at `parameters/NoahmpTable.TBL`. Must be in the run directory.

---

## Output File Formats

### LDASOUT NetCDF Files

One file per output_timestep, named: `YYYYMMDDHH00.LDASOUT_DOMAIN1`

Key output variables:

| Variable | Dimensions | Unit | Description |
|----------|-----------|------|-------------|
| TSLB | (ns,y,x) | K | Soil temperature per layer |
| SMOIS | (ns,y,x) | m³/m³ | Volumetric soil moisture per layer |
| SH2O | (ns,y,x) | m³/m³ | Liquid soil moisture per layer |
| SNOW | (y,x) | mm | Snow water equivalent |
| SNOWH | (y,x) | m | Snow depth |
| TSK | (y,x) | K | Skin temperature |
| HFX | (y,x) | W/m² | Sensible heat flux |
| LH | (y,x) | W/m² | Latent heat flux |
| GRDFLX | (y,x) | W/m² | Ground heat flux |
| SFCRUNOFF | (y,x) | m | Accumulated surface runoff |
| UDRUNOFF | (y,x) | m | Accumulated subsurface runoff |
| ALBEDO | (y,x) | - | Surface albedo |
| EMISS | (y,x) | - | Surface emissivity |
| ACSNOM | (y,x) | mm | Accumulated snowmelt |
| ACSNOW | (y,x) | mm | Accumulated snowfall |
| LAI | (y,x) | m²/m² | Leaf area index |

---

## Unit Trap Table

| Variable | Correct Unit | Common Wrong Unit | Factor | Symptom |
|----------|-------------|-------------------|--------|---------|
| T2D | K | °C | +273.15 | NaN/crash in vapor pressure |
| RAINRATE | mm/s | mm/hr | ÷3600 | Extreme runoff, soil saturation |
| RAINRATE | mm/s | mm/day | ÷86400 | Extreme runoff |
| Q2D | kg/kg | g/kg | ÷1000 | Extreme latent heat |
| Q2D | kg/kg | % RH | compute | Extreme latent heat |
| PSFC | Pa | hPa | ×100 | Wrong air density, fluxes off |
| PSFC | Pa | kPa | ×1000 | Wrong air density, fluxes off |
| SWDOWN | W/m² | kW/m² | ×1000 | Extreme heating |
| LWDOWN | W/m² | MJ/m²/day | ÷0.0864 | Wrong LW balance |
| VEGFRA | % (0-100) | fraction (0-1) | ×100 | Zero vegetation |
| soil_thick | m | cm | ÷100 | Wrong soil column depth |
| SNOW | mm | m | ×1000 | 1000x SWE error |
| DZS | m (positive) | m (negative) | abs() | Crash in soil solver |
| ZSOIL | m (negative) | m (positive) | negate | Wrong layer ordering |

---

## Physical Constants (from ConstantDefineMod.F90)

| Constant | Value | Unit | Description |
|----------|-------|------|-------------|
| ConstGravityAcc | 9.80616 | m/s² | Gravitational acceleration |
| ConstStefanBoltzmann | 5.67e-08 | W/m²/K⁴ | Stefan-Boltzmann constant |
| ConstVonKarman | 0.40 | - | von Karman constant |
| ConstFreezePoint | 273.16 | K | Freezing point of water |
| ConstLatHeatEvap | 2.5104e06 | J/kg | Latent heat of vaporization |
| ConstLatHeatFusion | 0.3336e06 | J/kg | Latent heat of fusion |
| ConstLatHeatSublim | 2.8440e06 | J/kg | Latent heat of sublimation |
| ConstHeatCapacWater | 4.188e06 | J/m³/K | Heat capacity of water |
| ConstHeatCapacIce | 2.094e06 | J/m³/K | Heat capacity of ice |
| ConstDensityWater | 1000.0 | kg/m³ | Density of liquid water |
| ConstDensityIce | 917.0 | kg/m³ | Density of ice |
| ConstGasDryAir | 287.04 | J/kg/K | Gas constant dry air |

---

## Calibration Parameters (Priority Order)

| Parameter | Location | Range | Controls | Sensitivity |
|-----------|----------|-------|----------|-------------|
| surface_runoff_option | namelist | 1-8 | Runoff generation scheme | VERY HIGH |
| subsurface_runoff_option | namelist | 1-6 | Baseflow generation | HIGH |
| DKSAT | NoahmpTable.TBL | 1e-7–1e-4 m/s | Saturated hydraulic conductivity | HIGH |
| SMCMAX | NoahmpTable.TBL | 0.3–0.5 m³/m³ | Porosity / max soil moisture | HIGH |
| BEXP | NoahmpTable.TBL | 2–13 | Clapp-Hornberger B exponent | HIGH |
| MFSNO | NoahmpTable.TBL | 1.0–4.0 | Snowmelt curve parameter | MEDIUM |
| VCMX25 | NoahmpTable.TBL | 20–80 µmol/m²/s | Max carboxylation at 25°C | MEDIUM |
| CWPVT | NoahmpTable.TBL | varies | Canopy wind parameter | LOW |
| dynamic_veg_option | namelist | 1-7 | LAI/vegetation dynamics | MEDIUM |

---

## Coupling Points

| # | Source | Target | Variable | Method |
|---|--------|--------|----------|--------|
| 1 | CMFD/ERA5 | Noah-MP | Met forcing | `convert_forcing_to_noahmp` |
| 2 | HWSD/SoilGrids | Noah-MP | Soil type | `convert_soil_to_noahmp` |
| 3 | Noah-MP | WRF-Hydro | Surface/subsurface runoff | LDASOUT files |
| 4 | Noah-MP | CaMa-Flood | Runoff for routing | SFCRUNOFF + UDRUNOFF |
| 5 | WRF | Noah-MP | Online atmospheric coupling | WRF driver |
| 6 | NASA/LIS | Noah-MP | Data assimilation | LIS driver |

---

## File Structure

```
ki/
├── SKILL.md                              # This file
├── knowledge_infrastructure.yaml         # Pipeline YAML specification
├── tools/
│   ├── convert_forcing_to_noahmp.py      # s4: Met forcing converter
│   ├── convert_soil_to_noahmp.py         # s2: Soil parameter converter
│   ├── run_noahmp.py                     # s6: Execution wrapper
│   └── parse_noahmp_output.py            # s7: Output parser
├── docs/
│   ├── s0_configuration.md               # Configuration guide
│   ├── s2_soil_parameters.md             # Soil parameter preparation
│   ├── s4_forcing_preparation.md         # Meteorological forcing
│   ├── s6_model_execution.md             # Running Noah-MP
│   └── s7_output_analysis.md             # Output parsing and analysis
└── diagnostics/
    └── triplets.yaml                     # 18 symptom→diagnosis→remedy entries
```

---

## Quick Start

```bash
# 1. Convert CMFD forcing to Noah-MP LDASIN format
python ki/tools/convert_forcing_to_noahmp.py \
  --input_dir /path/to/cmfd/data \
  --output_dir ./forcing/ \
  --lat 33.0 --lon 117.0 \
  --start_date 2010-01-01 --end_date 2010-12-31 \
  --timestep 3600

# 2. Prepare soil parameters
python ki/tools/convert_soil_to_noahmp.py \
  --hwsd_path /path/to/hwsd.nc \
  --lat 33.0 --lon 117.0 \
  --output soil_params.json

# 3. Create namelist.hrldas (manual or template)
# Edit namelist.hrldas with paths, physics options, period

# 4. Run the model
python ki/tools/run_noahmp.py \
  --run_dir ./run/ \
  --source_dir ./source/repo/ \
  --namelist ./namelist.hrldas

# 5. Parse output
python ki/tools/parse_noahmp_output.py \
  --output_dir ./run/ \
  --variables SMOIS,TSK,HFX,LH,SFCRUNOFF \
  --output results.csv
```
