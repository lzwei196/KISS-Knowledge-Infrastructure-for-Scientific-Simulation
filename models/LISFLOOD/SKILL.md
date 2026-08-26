---
name: lisflood
description: >-
  EC-JRC LISFLOOD (Van Der Knijff et al. 2010; Burek et al. 2013 Revised User Manual, JRC
  EUR 26162 EN) — distributed rainfall-runoff core of…. Covers Spatially distributed
  catchment-scale water balance and rainfall-runoff simulation; Snow accumulation, melt
  and glacier icemelt over sub-pixel elevation zones. Use when the task involves running,
  configuring, calibrating or interpreting LISFLOOD.
---

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

# LISFLOOD — Knowledge Infrastructure

**Package**: `hydrocraft-lisflood` v1.0.0
**Model**: LISFLOOD (EC-JRC spatially distributed hydrological model)
**Domain**: Large-scale rainfall-runoff, flood forecasting, water resources
**Language**: Python (with Numba JIT-compiled soil loop and routing)
**Last updated**: 2026-03-25
**Stats**: 4 tools | 5 skill documents | 18 diagnostic triplets | ~1,800 lines of validated Python
**Validation status**: `test_case_validated` (LF_ETRS89_UseCase cold run)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## Overview

LISFLOOD is a spatially distributed, physically-based rainfall-runoff model developed by the European Commission Joint Research Centre (EC-JRC). It is the core hydrological model behind the European Flood Awareness System (EFAS) and the Global Flood Awareness System (GloFAS). The model simulates the full terrestrial water cycle including snow accumulation/melt, soil moisture dynamics (3-layer Van Genuchten), groundwater (2-box), surface and channel routing (kinematic wave), lake/reservoir operations, and water use/abstraction.

**What LISFLOOD simulates**:
- Snow accumulation, melt, and frost (3 elevation zones per pixel)
- Rainfall interception by vegetation canopy (LAI-based)
- Soil moisture in 3 layers (Van Genuchten water retention)
- Surface runoff (Xinanjiang saturation excess) and preferential flow
- Groundwater: upper zone (quick response) and lower zone (baseflow)
- Channel routing via kinematic wave (Manning's equation)
- Lake outflow (Modified Puls) and reservoir operations (3-zone rule curves)
- Water abstraction (domestic, industrial, livestock, energy, irrigation)
- Rice paddy irrigation, polder management
- Open water and sealed surface evaporation

**Key difference from other HydroCraft models**: LISFLOOD operates on a gridded domain (PCRaster/NetCDF maps) with a drainage network (LDD). It uses sub-daily to daily timesteps (typically 6-hourly, `DtSec=21600`) with sub-stepping for channel routing (`DtSecChannel=3600`).

---

## Installation

### From PyPI

```bash
# Create conda environment (PCRaster + GDAL required)
conda create --name lisflood python=3.9 -c conda-forge
conda activate lisflood
conda install -c conda-forge pcraster gdal

# Install LISFLOOD
pip install lisflood-model
```

### From Source

```bash
git clone https://github.com/ec-jrc/lisflood-code.git
cd lisflood-code
conda install -c conda-forge pcraster gdal
pip install -r requirements.txt
pip install -e .
```

### Key Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pcraster` | >=3.0 | Spatial raster operations, LDD routing |
| `gdal` | >=3.2 | Geospatial I/O |
| `numpy` | >=1.21 | Array operations |
| `numba` | >=0.54 | JIT compilation for soil loop |
| `netCDF4` | 1.5.3-1.6.4 | NetCDF I/O |
| `xarray` | >=0.20 | Labeled multi-dimensional arrays |
| `dask` | >=2021.10 | Lazy/parallel I/O |
| `pandas` | <2.0 | Time series |
| `lisflood-utilities` | >=0.12.19 | Custom LISFLOOD utilities |
| `lxml`, `beautifulsoup4` | — | XML settings parsing |

### Test Example

```
tests/data/LF_ETRS89_UseCase/     # ETRS89-projected test catchment
  settings/cold.xml                # Cold start settings
  settings/warm.xml                # Warm start (from saved state)
  maps/                            # Static maps (DEM, soil, land use)
  forcings/                        # Meteorological forcing (NetCDF)
  init/                            # Initial conditions
  out/                             # Output directory
```

**Quick test**:
```bash
mkdir -p tests/data/LF_ETRS89_UseCase/out
lisflood tests/data/LF_ETRS89_UseCase/settings/cold.xml
# Or: python src/lisf1.py tests/data/LF_ETRS89_UseCase/settings/cold.xml
```

---

## Pipeline (8 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 1 | Forcing preparation | `convert_forcing_to_lisflood` | Global met data → LISFLOOD NetCDF forcing (pr, ta, et0, e0) |
| 2 | Soil/parameter maps | `convert_soil_params` | HWSD/SoilGrids → Van Genuchten parameters per layer |
| 3 | Domain setup | (manual/GIS) | MaskMap, LDD, channel network, elevation, land use |
| 4 | Settings XML | (manual) | Configure lisfloodSettings.xml with paths and options |
| 5 | Calibration params | (manual) | Set calibration multipliers and thresholds |
| 6 | Execution | `run_lisflood` | Run LISFLOOD with preflight checks |
| 7 | Output analysis | `parse_lisflood_output` | Extract discharge, soil moisture, water balance to CSV |
| 8 | Validation | (manual) | Compare simulated vs observed discharge (NSE, KGE) |

### Parallelism

Stages 1, 2, 3 can run in parallel.
Stage 4 depends on 1-3 (paths must exist).
Stage 6 depends on 4-5.
Stages 7-8 depend on 6.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `convert_forcing_to_lisflood` | s1 | `tools/convert_forcing.py` | ~350 | Global forcing to LISFLOOD NetCDF (unit conversions) |
| `convert_soil_params` | s2 | `tools/convert_soil_params.py` | ~300 | Soil database to Van Genuchten maps |
| `run_lisflood` | s6 | `tools/run_lisflood.py` | ~250 | Execute LISFLOOD with preflight validation |
| `parse_lisflood_output` | s7 | `tools/parse_output.py` | ~300 | Parse NetCDF output to CSV/diagnostics |

**Total**: 4 tools, ~1,200 lines of validated Python code.

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated. Each has a corresponding diagnostic triplet.

### 1. Precipitation units: mm/day, NOT m/day (dt_001)

LISFLOOD expects precipitation in **mm/day** (or mm/timestep after internal scaling by `DtDay`). The internal variable `PrScaling` converts from the input unit. CMFD gives mm/3hr; ERA5 gives m/timestep. Wrong units cause either flooding (too much) or drought (too little) with no error message.

### 2. Temperature: Kelvin vs Celsius (dt_002)

LISFLOOD can accept temperature in either Kelvin or Celsius. Set option `TemperatureInKelvin` to `1` if input is Kelvin. If this flag is wrong, snow thresholds (`TempSnow`, `TempMelt`) are off by 273.15°C — snow either never forms or never melts.

### 3. ET0/E0 are POTENTIAL, not actual (dt_003)

The forcing variables `et0` (reference evapotranspiration) and `e0` (open water evaporation) must be **potential** rates in mm/day. LISFLOOD internally reduces these to actual ET using soil moisture stress. Providing actual ET instead of potential ET will underestimate water loss.

### 4. Soil parameters use Van Genuchten, NOT Brooks-Corey (dt_005)

LISFLOOD uses the Van Genuchten water retention model:
- `Lambda` = pore-size distribution index (NOT Brooks-Corey lambda)
- `GenuAlpha` = Van Genuchten alpha [1/cm]
- `ThetaSat`, `ThetaRes` = saturated/residual water content [m³/m³]
- N = 1 + Lambda, M = Lambda/(1+Lambda)

Using Brooks-Corey parameters directly will produce wrong field capacity and wilting point.

### 5. LDD format: PCRaster convention (dt_006)

Local Drainage Direction uses PCRaster encoding (1-9, where 5=pit/outlet). This is NOT the same as ArcGIS D8 (1,2,4,8,16,32,64,128). Using ArcGIS LDD directly crashes LISFLOOD or routes water incorrectly.

### 6. SoilDepth is in mm, NOT m (dt_007)

Soil layer depths (`SoilDepth1`, `SoilDepth2`, `SoilDepth3`) are in **millimeters**. Typical values: SoilDepth1=50-300 mm, SoilDepth2=300-1500 mm, SoilDepth3=300-1500 mm. Using meters (0.3 instead of 300) gives a 1000x error in soil water storage.

### 7. Channel Manning's n is modified by CalChanMan (dt_009)

The calibration parameter `CalChanMan` is a **multiplier** on Manning's n, not the value itself. Effective n = ChanManMaps * CalChanMan. Setting CalChanMan=0.04 (thinking it's n) instead of 1.0 (multiplier) gives n ≈ 0.001, producing unrealistically fast flow.

### 8. StepStart/StepEnd can be dates OR step numbers (dt_010)

`StepStart` and `StepEnd` accept either calendar dates (`02/01/1990 06:00`) or integer step numbers. The format depends on `CalendarDayStart`. Mixing formats causes wrong simulation periods or crashes.

### 9. Reservoir lookup tables must match IDs exactly (dt_013)

Lake and reservoir lookup tables (`TabLakeArea`, `TabTotStorage`, etc.) must contain entries for every lake/reservoir ID in the spatial map. Missing IDs cause silent NaN propagation or crashes.

---

## Unit Trap Table

| Variable | LISFLOOD expects | Common source unit | Conversion | Trap ID |
|----------|-----------------|-------------------|------------|---------|
| Precipitation | mm/day (or mm/timestep) | mm/3hr (CMFD), m/s (ERA5) | ×8 (3hr→day), ×86400×1000 (m/s→mm/day) | dt_001 |
| Temperature | °C (or K with flag) | K (ERA5, CMFD) | −273.15 or set `TemperatureInKelvin=1` | dt_002 |
| ET0 / E0 | mm/day (potential) | mm/day, W/m² | If W/m²: ÷(2.45×10⁶)×86400×1000 | dt_003 |
| Soil depth | mm | m (SoilGrids), cm (HWSD) | ×1000 (m→mm), ×10 (cm→mm) | dt_007 |
| KSat | mm/day | cm/day (HWSD), m/s | ×10 (cm→mm), ×86400×1000 (m/s→mm/day) | dt_008 |
| GenuAlpha | 1/cm | 1/m (some DBs) | ÷100 (1/m → 1/cm) | dt_005 |
| Channel slope | m/m | % | ÷100 | dt_009 |
| ChanLength | m | km | ×1000 | dt_009 |
| Manning's n | s/m^(1/3) | — | Use CalChanMan as multiplier | dt_009 |
| Lat/Lon | decimal degrees | DMS | Convert to decimal | — |

---

## Calibration Parameters (Priority Order)

| Parameter | XML element | Range | Controls | Sensitivity |
|-----------|-------------|-------|----------|-------------|
| `UpperZoneTimeConstant` | `<textvar>` | 1-100 days | Quick baseflow response | HIGH |
| `LowerZoneTimeConstant` | `<textvar>` | 10-5000 days | Slow baseflow / recession | HIGH |
| `b_Xinanjiang` | `<textvar>` | 0.01-1.0 | Saturation excess runoff shape | HIGH |
| `PowerPrefFlow` | `<textvar>` | 1.0-4.0 | Preferential flow nonlinearity | MEDIUM |
| `CalChanMan` | `<textvar>` | 0.1-10.0 | Channel routing speed (n multiplier) | MEDIUM |
| `SnowMeltCoef` | `<textvar>` | 1.0-10.0 mm/°C/day | Snowmelt rate | MEDIUM (snow basins) |
| `GwPercValue` | `<textvar>` | 0.1-10.0 mm/day | Max UZ→LZ percolation | MEDIUM |
| `GwLoss` | `<textvar>` | 0.0-5.0 mm/day | Groundwater loss to deep aquifer | LOW |
| `LZThreshold` | `<textvar>` | 0-100 mm | Baseflow cutoff threshold | LOW |
| `LakeMultiplier` | `<textvar>` | 0.1-10.0 | Lake outflow scaling | LOW (lake basins) |

---

## Input/Output Summary

### Inputs

| Category | Format | Key Variables |
|----------|--------|---------------|
| Meteorological forcing | NetCDF stack or PCRaster maps | pr (mm/day), ta (°C), et0 (mm/day), e0 (mm/day) |
| Static maps | NetCDF or PCRaster | MaskMap, Ldd, Elevation, ChannelNetwork, soil properties |
| Land use | NetCDF or PCRaster | OtherFraction, ForestFraction, IrrigationFraction |
| LAI | NetCDF or PCRaster | Monthly LAI per land use class |
| Channel geometry | NetCDF or PCRaster | ChanBottomWidth, ChanGrad, ChanLength, ChanManMaps |
| Lake/reservoir tables | Tab-separated text | TabLakeArea, TabTotStorage, outflow parameters |
| Settings | XML | lisfloodSettings.xml (all paths, options, parameters) |

### Outputs

| Variable | File | Unit | Description |
|----------|------|------|-------------|
| dis | dis.nc | m³/s | Discharge at every channel pixel |
| rain | rain.nc | mm | Rainfall (liquid precipitation) |
| snow | snow.nc | mm | Snowfall |
| snowcov | snowcov.nc | mm | Snow water equivalent |
| theta1/2/3 | theta*.nc | m³/m³ | Soil moisture per layer |
| uz, lz | uz.nc, lz.nc | mm | Upper/lower zone storage |
| gwperc | gwperc.nc | mm | Groundwater percolation |
| surfr | surfr.nc | mm | Surface runoff |
| twb | twb.nc | mm | Total water balance residual |
| Gauge TSS | *.tss | m³/s | Time series at gauge points |

---

## Execution Modes

### Deterministic Run
```bash
lisflood settings.xml
# or: python src/lisf1.py settings.xml
```

### Cold Start (spin-up)
Set `InitLisflood = 1` in settings. This writes end-state maps to `PathInit` that can be used as initial conditions for the warm start.

### Warm Start
Set `InitLisflood = 0` and point initial condition paths to cold-run output.

### Monte Carlo
```bash
lisflood settings.xml -m 100  # 100 Monte Carlo realizations
```

### Ensemble Kalman Filter
```bash
lisflood settings.xml -e 50   # 50 ensemble members for EnKF
```

---

## Settings XML Structure

The settings XML has these main sections:

1. **`<lfoptions>`** — Boolean switches for model features:
   - `simulateLakes`, `simulateReservoirs`, `wateruse`, `SplitRouting`
   - `readNetcdfStack`, `writeNetcdfStack`, `writeNetcdf`
   - `TemperatureInKelvin`, `gridSizeUserDefined`

2. **`<lfuser>`** — User-defined text variables:
   - Paths: `PathRoot`, `PathOut`, `PathMeteo`, `PathMaps`, `PathInit`
   - Domain: `MaskMap`, `Gauges`, `Outlets`
   - Time: `CalendarDayStart`, `StepStart`, `StepEnd`, `DtSec`
   - Calibration: all calibration parameters

3. **`<lfbinding>`** — Bindings between internal variable names and file paths:
   - Maps meteorological prefixes to file paths
   - Maps soil parameter names to map files
   - Maps output variable names to output files

---

## Data Requirements

| Data | Source | Format | Path Convention |
|------|--------|--------|----------------|
| Meteorological forcing | ERA5/CMFD/MSWX | NetCDF | `PathMeteo/{prefix}YYYYMMDD.nc` |
| DEM & derivatives | SRTM/MERIT | PCRaster/NetCDF | `PathMaps/` |
| Soil properties | HWSD/SoilGrids | PCRaster/NetCDF | `PathMaps/` |
| Land use | CLC/GlobCover | PCRaster/NetCDF | `PathMaps/` |
| Channel network | Derived from DEM | PCRaster | `PathMaps/` |
| LAI | MODIS/Copernicus | NetCDF | `PathLAI/` |

---

## Quick Start

```bash
# 1. Install
conda create --name lisflood python=3.9 -c conda-forge
conda activate lisflood
conda install -c conda-forge pcraster gdal
pip install lisflood-model

# 2. Prepare test case
mkdir -p tests/data/LF_ETRS89_UseCase/out

# 3. Run cold start
lisflood tests/data/LF_ETRS89_UseCase/settings/cold.xml

# 4. Check output
python -c "
import netCDF4 as nc
ds = nc.Dataset('tests/data/LF_ETRS89_UseCase/out/dis.nc')
print('Discharge shape:', ds['dis'].shape)
print('Max Q:', ds['dis'][:].max(), 'm3/s')
ds.close()
"
```

---

## File Structure

```
LISFLOOD/ki/
  SKILL.md                          # This file (agent entry point)
  tools/
    convert_forcing.py              # Forcing converter (ERA5/CMFD → LISFLOOD NetCDF)
    convert_soil_params.py          # Soil parameter converter (HWSD → Van Genuchten)
    run_lisflood.py                 # Execution wrapper with preflight checks
    parse_output.py                 # Output parser (NetCDF → CSV/diagnostics)
  docs/
    01_forcing_preparation.md       # Meteorological forcing preparation
    02_soil_parameter_setup.md      # Soil and land use parameter setup
    03_domain_configuration.md      # Domain, LDD, channel network setup
    04_model_execution.md           # Running LISFLOOD (cold/warm start)
    05_output_analysis.md           # Output parsing, validation, calibration
  diagnostics/
    triplets.yaml                   # 18 diagnostic triplets

source/repo/
  src/lisf1.py                      # Entry point
  src/lisflood/main.py              # Main execution module
  src/lisflood/Lisflood_initial.py  # Initialization
  src/lisflood/Lisflood_dynamic.py  # Time-stepping loop
  src/lisflood/hydrological_modules/
    readmeteo.py                    # Met forcing reader
    snow.py                         # Snow model (3 elevation zones)
    frost.py                        # Frost index
    soil.py                         # Soil water balance
    soilloop.py                     # JIT-compiled soil loop
    groundwater.py                  # 2-box groundwater
    routing.py                      # Kinematic wave channel routing
    lakes.py                        # Lake model (Modified Puls)
    reservoir.py                    # Reservoir operations
    waterabstraction.py             # Water use/demand
    surface_routing.py              # Surface runoff routing
    evapowater.py                   # Open water evaporation
    riceirrigation.py               # Rice paddy irrigation
    transmission.py                 # Channel transmission loss
    waterbalance.py                 # Mass balance check
  src/lisfloodSettings_reference.xml # Full reference settings (144 KB)
```

---

## Diagnostic Triplets

18 triplets covering 5 failure domains. See `diagnostics/triplets.yaml` for full details.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | **silent** | unit_conversion | Precipitation units wrong (mm/day vs m/day) |
| dt_002 | **silent** | unit_conversion | Temperature K/C flag mismatch |
| dt_003 | **silent** | unit_conversion | ET0 actual instead of potential |
| dt_004 | **silent** | unit_conversion | Forcing timestep not matching DtSec |
| dt_005 | **silent** | unit_conversion | Van Genuchten alpha units (1/cm vs 1/m) |
| dt_006 | fatal | parameter_format | LDD encoding mismatch (PCRaster vs ArcGIS) |
| dt_007 | **silent** | unit_conversion | SoilDepth in m instead of mm |
| dt_008 | **silent** | unit_conversion | KSat units wrong |
| dt_009 | **silent** | parameter_format | CalChanMan used as n instead of multiplier |
| dt_010 | fatal | parameter_format | StepStart/StepEnd format mismatch |
| dt_011 | fatal | path_resolution | MaskMap path not found |
| dt_012 | fatal | path_resolution | Forcing file path/prefix mismatch |
| dt_013 | fatal | runtime | Lake/reservoir ID missing from lookup table |
| dt_014 | **silent** | silent_error | SnowMeltCoef too high — no snow accumulation |
| dt_015 | **silent** | silent_error | GwLoss drains all groundwater — baseflow=0 |
| dt_016 | **silent** | silent_error | b_Xinanjiang near 0 — all rainfall becomes runoff |
| dt_017 | degraded | runtime | Numba compilation failure — falls back to slow Python |
| dt_018 | **silent** | silent_error | WriteNetcdf off — no spatial output produced |

**Silent error count**: 11/18 (61%) — dominated by unit conversion traps.
