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

# DNDC (DNDCv.CAN) — DeNitrification-DeComposition Model Knowledge Infrastructure

**Package**: `hydrocraft-dndc-crop` v1.0.0
**Model**: DNDCv.CAN v9.6.0 — Canadian branch of DNDC95
**Developers**: Brian Grant & Ward Smith, Agriculture and Agri-Food Canada
**Source**: https://github.com/BrianBGrant/DNDCv.CAN (binary only; source code proprietary)
**Domain**: Crop growth, soil carbon/nitrogen cycling, greenhouse gas emissions
**Last updated**: 2026-03-28
**Stats**: 4 tools | 7 skill documents | 18 diagnostic triplets | ~2,000 lines of validated Python

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/FLUXNET/SKILL.md` for eddy covariance flux observations.


## Overview

DNDCv.CAN (DeNitrification-DeComposition, Canadian version) is a process-based
biogeochemical model that simulates carbon and nitrogen cycling in agricultural
ecosystems at the field scale on a daily time step. It is derived from the original
DNDC95 codebase (August 2015, University of New Hampshire) and has been independently
developed by Agriculture and Agri-Food Canada for Canadian cropping systems.

**What DNDC simulates**:
- Crop growth and development (phenology, biomass accumulation, C/N partitioning)
- Soil organic carbon decomposition and turnover (multi-pool model)
- Nitrogen cycling (mineralization, nitrification, denitrification, leaching, volatilization)
- Greenhouse gas emissions (N2O, NO, CO2, CH4 from soil processes)
- Soil water balance (infiltration, drainage, tile drainage, evapotranspiration)
- Soil temperature profile (freezing/thawing, frost dynamics, snow cover)
- Ammonia volatilization from fertilizer and manure
- Tillage effects on soil mixing and residue incorporation
- Manure and organic amendment decomposition (including biosolid C pools)
- Cover crop dynamics and frostkill sensitivity
- Preferential flow through soil macropores and cracking

**Key architectural features**:
- Windows PE32 executable (DNDC95.exe), no source code publicly available
- All inputs consolidated into a single `.dnd` text file per site
- Climate forcing via daily text files with 7 meteorological variables
- Soil profile always modeled to 200 cm (2 m) depth
- Batch execution via command-line interface with batch file listing
- Output written to `Result/Record/` directory tree

**What distinguishes DNDCv.CAN from other DNDC variants**:
- Enhanced tile drainage simulation (mechanistic approach)
- Improved snow/frost dynamics and winter-spring N2O burst modeling
- Biosolid carbon pool for organic amendments
- pH-sensitive NH4:NH3 equilibrium
- RUE (radiation use efficiency) sensitivity improvements for crop growth
- Inversion tillage conceptualization
- Dynamic soil layer depth capability
- Preferential flow toggle with soil cracking/retreat sensitivity

---

## Installation

### Windows (Native)

DNDCv.CAN is distributed as a zip archive containing the PE32 executable and
supporting files. No installation is required beyond extraction.

```
1. Download DNDC-Nov2024.zip from GitHub repository
2. Extract to a working directory (e.g., C:\DNDC\)
3. Contents:
   DNDC95.exe          — Main executable (PE32 Windows binary)
   *.dll               — Optional DLL files (DNDC-OptionalDLL.zip)
   Example .dnd files  — Sample input configurations
```

### Linux (via Wine)

Since DNDC95.exe is a Windows PE32 binary, it must be run via Wine on Linux.

```bash
# Install Wine
sudo apt install wine64 wine32

# Verify Wine can run the binary
wine --version
file DNDC95.exe    # should report: PE32 executable (GUI) Intel 80386

# Test execution
wine DNDC95.exe -s batch_file.txt -daily 0 -output ./output/

# For headless batch execution (recommended)
export WINEDEBUG=-all
wine start /wait DNDC95.exe -s batch_file.txt -daily 0 -output ./output/
```

### Directory Structure

```
DNDC_workspace/
├── DNDC95.exe              # Model executable
├── *.dll                   # Optional DLLs
├── batch_file.txt          # Batch run configuration
├── inputs/
│   ├── site1.dnd           # Combined input file (site+climate+soil+crop+mgmt)
│   ├── site2.dnd           # One .dnd per simulation site
│   └── ...
├── climate/
│   ├── climate_station1.txt  # Daily climate forcing
│   └── ...
├── soil/
│   └── profiles.spf        # Soil profile definitions
└── Result/
    └── Record/
        ├── Site/           # Single-run outputs
        └── Batch/          # Batch-run outputs
```

---

## Pipeline (7 Stages)

| # | Stage | ID | Tool(s) | Input | Output |
|---|-------|----|---------|-------|--------|
| 0 | Configuration | `s0_config` | (manual/template) | Site coordinates, simulation dates, model switches | Configuration parameters for DND assembly |
| 1 | Climate Preparation | `s1_domain` | `convert_climate_to_dndc.py` | Global met data (CSV/NetCDF) | DNDC daily climate text file (type 5 format) |
| 2 | Soil Preparation | `s2_data` | `convert_soil_to_dndc.py` | HWSD/SoilGrids/custom soil data | Soil profile block for DND file or .spf file |
| 3 | Crop & Management | `s3_forcing` | (manual/template) | Agronomic calendar, fertilizer plan | Crop and management parameter blocks |
| 4 | DND Assembly | `s4_parameters` | `assemble_dnd_file.py` | Config + climate + soil + crop/mgmt | Complete .dnd input file per site |
| 5 | Execution | `s5_run` | `run_dndc.py` | Batch file + .dnd files + DNDC95.exe | Raw model output in Result/Record/ |
| 6 | Output Analysis | `s6_output` | `parse_dndc_output.py` | Result/Record/ output files | Clean CSV, summary metrics, time series |

---

## Command-Line Execution

### Single Run

The GUI version (DNDC95.exe without flags) opens an interactive Windows application.
For automated batch processing, use the command-line interface:

```bash
# Windows
start /wait DNDC95.exe -s batch_file.txt -daily 0 -output output_dir/

# Linux (Wine)
wine DNDC95.exe -s batch_file.txt -daily 0 -output output_dir/
```

### CLI Flags

| Flag | Description |
|------|-------------|
| `-s <file>` | Batch file path listing .dnd input files |
| `-daily <0\|1>` | Daily output toggle: 0 = off (summary only), 1 = on |
| `-output <dir>` | Output directory path (trailing slash recommended) |

### Batch File Format

The batch file is a plain text file with the following structure:

```
2                            # Number of .dnd files to run
inputs/site1.dnd             # Path to first .dnd file
inputs/site2.dnd             # Path to second .dnd file
```

Line 1: integer count of simulations.
Lines 2+: one .dnd file path per line (relative or absolute).

### Output Directory Structure

```
Result/Record/Batch/         # Batch run outputs
  site1_daily.csv            # Daily time series
  site1_annual.csv           # Annual summary
  site1_crop.csv             # Crop growth outputs
  site1_ghg.csv              # Greenhouse gas emissions
```

---

## Input File Formats

### DND File (.dnd) — Master Input

The `.dnd` file is a single text file containing ALL simulation parameters organized
into named sections. Each section begins with a keyword header and contains key-value
pairs or tabular data. A single .dnd file fully defines one simulation site.

**Major sections**:

| Section | Content |
|---------|---------|
| Site Information | Latitude, longitude, elevation, simulation years |
| Climate | Climate file path, format type, CO2 concentration |
| Soil | Profile depth, layer properties, initial conditions |
| Crop | Crop type selection, growth parameters, C/N ratios |
| Tillage | Tillage type, depth, timing, residue handling |
| Fertilization | Fertilizer type, rate, timing, depth, inhibitors |
| Irrigation | Method, amount, timing |
| Manure | Organic amendment type, rate, timing, C/N ratio |
| Grazing | Grazing intensity, timing (if applicable) |
| Tile Drainage | Drain depth, spacing, coefficient |
| Model Switches | N2O module, CH4 module, preferential flow toggle |
| Extra Parameters | Dynamic layer depth, respiration coefficients |

### Climate File — Daily Forcing

Daily text file with space or tab-delimited columns. The climate format type
(specified in the .dnd file) determines the column layout.

**Climate Format Type 5** (most complete, recommended):

```
Jday  MaxT   MinT   Prec     Radiation  WindSpeed  Humidity
1     -5.2   -12.8  0.00     4.35       3.2        72.0
2     -3.1   -10.5  0.15     5.12       2.8        68.5
3     -1.8   -8.3   0.00     6.88       4.1        65.0
...
365   -4.5   -11.2  0.08     3.92       3.5        74.0
```

**All Climate Format Types**:

| Type | Columns | Description |
|------|---------|-------------|
| 1 | Jday, MaxT, MinT, Prec | Minimum (temperature + precipitation only) |
| 2 | Jday, MaxT, MinT, Prec, Radiation | Adds solar radiation |
| 3 | Jday, MaxT, MinT, Prec, Radiation, WindSpeed | Adds wind speed |
| 4 | Jday, MaxT, MinT, Prec, Radiation, Humidity | Adds humidity (no wind) |
| 5 | Jday, MaxT, MinT, Prec, Radiation, WindSpeed, Humidity | Full 7-variable set |

**Climate Variable Specifications**:

| Column | Variable | Unit | Valid Range | Notes |
|--------|----------|------|-------------|-------|
| Jday | Julian day | 1-365/366 | 1-366 | Day of year |
| MaxT | Maximum temperature | deg C | -60 to +60 | Daily maximum |
| MinT | Minimum temperature | deg C | -60 to +60 | Must be <= MaxT |
| Prec | Precipitation | **cm** | >= 0 | CRITICAL: centimeters, NOT millimeters |
| Radiation | Solar radiation | MJ/m2/day | 0-45 | Daily total, not instantaneous |
| WindSpeed | Wind speed | m/s | 0-50 | Daily mean at reference height |
| Humidity | Relative humidity | % | 0-100 | Percent, not fraction |

### Soil Profile File (.spf)

The `.spf` file defines soil layer properties for the 200 cm profile.

**Format**: One row per soil layer, space-delimited.

| Column | Variable | Unit | Description |
|--------|----------|------|-------------|
| 1 | Thickness | m | Layer thickness |
| 2 | Bulk density | g/cm3 | Dry bulk density |
| 3 | SOC | kgC/kg soil | Soil organic carbon concentration |
| 4 | Texture ID | integer | DNDC texture class index |
| 5 | pH | - | Soil pH (H2O) |
| 6 | Field capacity | WFPS | Water-filled pore space at field capacity |
| 7 | Wilting point | WFPS | Water-filled pore space at wilting point |
| 8 | Porosity | v/v | Total porosity (volume/volume) |
| 9 | Hydraulic conductivity | m/hr | Saturated hydraulic conductivity |
| 10 | Clay fraction | 0-1 | Mass fraction of clay |

**Example .spf layer**:
```
0.10  1.35  0.025  4  6.5  0.65  0.30  0.49  0.005  0.22
```

**DNDC Texture Classes**:

| ID | Texture | Clay% | Silt% | Sand% |
|----|---------|-------|-------|-------|
| 1 | Sand | 3 | 7 | 90 |
| 2 | Loamy Sand | 6 | 12 | 82 |
| 3 | Sandy Loam | 10 | 25 | 65 |
| 4 | Loam | 18 | 40 | 42 |
| 5 | Silt Loam | 15 | 60 | 25 |
| 6 | Sandy Clay Loam | 27 | 13 | 60 |
| 7 | Clay Loam | 34 | 34 | 32 |
| 8 | Silty Clay Loam | 34 | 56 | 10 |
| 9 | Sandy Clay | 42 | 7 | 51 |
| 10 | Silty Clay | 47 | 47 | 6 |
| 11 | Clay | 65 | 18 | 17 |
| 12 | Silt | 6 | 87 | 7 |

---

## Unit Trap Table

These are the most dangerous unit conversion pitfalls when preparing DNDC inputs.
All unit errors are **silent** -- DNDC will run without error messages but produce
physically meaningless results.

| ID | Variable | DNDC Expects | Common Source Unit | Conversion | Severity |
|----|----------|-------------|-------------------|------------|----------|
| UT1 | Precipitation | **cm/day** | mm/day | divide by 10 | **CRITICAL** |
| UT2 | Precipitation | cm/day | m/day | multiply by 100 | CRITICAL |
| UT3 | Precipitation | cm/day | kg/m2/s | multiply by 8640 | CRITICAL |
| UT4 | Solar radiation | MJ/m2/day | W/m2 (daily mean) | multiply by 0.0864 | CRITICAL |
| UT5 | Solar radiation | MJ/m2/day | kJ/m2/day | divide by 1000 | HIGH |
| UT6 | Temperature | deg C | K (Kelvin) | subtract 273.15 | CRITICAL |
| UT7 | Humidity | % (0-100) | fraction (0-1) | multiply by 100 | HIGH |
| UT8 | Wind speed | m/s | km/h | divide by 3.6 | MEDIUM |
| UT9 | SOC | kgC/kg soil | % (g/100g) | divide by 100 | **CRITICAL** |
| UT10 | SOC | kgC/kg soil | g/kg | divide by 1000 | CRITICAL |
| UT11 | Bulk density | g/cm3 | kg/m3 | divide by 1000 | CRITICAL |
| UT12 | Layer thickness | m | cm | divide by 100 | HIGH |
| UT13 | Hydraulic conductivity | m/hr | cm/hr | divide by 100 | HIGH |
| UT14 | Hydraulic conductivity | m/hr | um/s (SSURGO) | multiply by 0.0036 | HIGH |
| UT15 | Clay fraction | 0-1 | percent (0-100) | divide by 100 | HIGH |
| UT16 | Fertilizer rate | kgN/ha | lb N/ac | multiply by 1.121 | MEDIUM |
| UT17 | Porosity | v/v (0-1) | percent | divide by 100 | HIGH |
| UT18 | Field capacity | WFPS (0-1) | volumetric (cm3/cm3) | divide by porosity | HIGH |

**The single most common error**: Precipitation in mm instead of cm. This causes a
10x overestimation of water inputs, leading to waterlogged soils, unrealistic drainage,
excessive denitrification, and inflated N2O emissions.

---

## Crop Library

DNDC includes parameterizations for 18+ crop types. Each crop is defined by growth
parameters, biomass partitioning fractions, C/N ratios, and thermal requirements.

| ID | Crop Name | Typical Yield (kgC/ha) | Thermal Degree Days | C/N Grain | C/N Stover |
|----|-----------|----------------------|--------------------|-----------|-----------|
| 1 | Corn (Grain) | 3000-5000 | 1500-2000 | 40-50 | 50-80 |
| 2 | Winter Wheat | 2000-3500 | 1800-2200 | 35-45 | 60-90 |
| 3 | Spring Wheat | 1500-3000 | 1200-1600 | 35-45 | 60-90 |
| 4 | Soybean | 1200-2500 | 1200-1800 | 15-25 | 30-50 |
| 5 | Barley | 1500-2800 | 1000-1400 | 30-40 | 50-80 |
| 6 | Oats | 1200-2200 | 900-1300 | 30-40 | 50-70 |
| 7 | Alfalfa | 3000-6000 | perennial | 15-20 | 20-30 |
| 8 | Grass (Hay) | 2000-5000 | perennial | 20-30 | 30-50 |
| 9 | Canola | 1000-2000 | 1100-1500 | 25-35 | 50-80 |
| 10 | Potato | 2500-5000 | 1200-1600 | 40-60 | 50-70 |
| 11 | Rice (paddy) | 2000-4000 | 1800-2400 | 35-50 | 50-80 |
| 12 | Cotton | 800-1500 | 1600-2200 | 60-80 | 80-120 |
| 13 | Corn (Silage) | 4000-7000 | 1400-1800 | 40-50 | 30-50 |
| 14 | Sugar Beet | 3000-6000 | 1400-1800 | 50-80 | 40-60 |
| 15 | Sunflower | 1000-2000 | 1300-1700 | 50-70 | 60-90 |
| 16 | Rye | 1500-2500 | 1100-1500 | 30-40 | 50-80 |
| 17 | Cover Crop (generic) | N/A (not harvested) | 600-1000 | 20-30 | 25-40 |
| 18 | Pasture | 1500-4000 | perennial | 20-30 | 25-40 |

**Key crop growth parameters in the DND file**:
- Maximum biomass production (kgC/ha)
- Biomass fraction to grain, leaf, stem, root
- C/N ratio of grain, stover, root
- Thermal degree days for maturity
- Base temperature for growth (deg C)
- Water demand coefficient
- N fixation index (for legumes, 0-1)
- Root depth (fraction of soil profile)
- Root respiration: maintenance and new growth coefficients
- Above-ground respiration: maintenance and new growth coefficients

---

## Common Parameters Reference

### Site Parameters

| Parameter | Unit | Typical Range | Description |
|-----------|------|---------------|-------------|
| Latitude | degrees N | -90 to 90 | Site latitude (negative = south) |
| Longitude | degrees E | -180 to 180 | Site longitude (negative = west) |
| Elevation | m | 0-5000 | Elevation above sea level |
| Simulation years | integer | 1-100 | Number of years to simulate |
| Start year | integer | 1900-2100 | Calendar year of simulation start |
| CO2 concentration | ppm | 280-1000 | Atmospheric CO2 (default ~400) |
| N deposition | kgN/ha/yr | 0-50 | Background atmospheric N deposition |

### Soil Initial Conditions

| Parameter | Unit | Typical Range | Description |
|-----------|------|---------------|-------------|
| SOC at surface | kgC/kg | 0.005-0.10 | Initial soil organic carbon, top layer |
| Soil pH | - | 3.5-9.0 | Initial pH (H2O extraction) |
| NO3 concentration | mgN/kg | 0-50 | Initial nitrate in soil |
| NH4 concentration | mgN/kg | 0-20 | Initial ammonium in soil |
| Water-filled pore space | fraction | 0.3-0.9 | Initial soil moisture (WFPS) |
| Microbial biomass C | kgC/ha | 100-1000 | Initial microbial carbon pool |
| Litter C on surface | kgC/ha | 0-5000 | Surface residue carbon |

### Fertilizer Parameters

| Parameter | Unit | Description |
|-----------|------|-------------|
| Fertilizer type | integer | 1=urea, 2=NH4NO3, 3=anhydrous NH3, etc. |
| Application rate | kgN/ha | Total N applied per event |
| Application depth | cm | Depth of incorporation (0 = surface) |
| Application date | Julian day | Day of year for application |
| Inhibitor type | integer | 0=none, 1=nitrification, 2=urease, 3=both |
| Inhibitor duration | days | Active period of inhibitor product |

### Tillage Parameters

| Parameter | Unit | Description |
|-----------|------|-------------|
| Tillage type | integer | 0=none, 1=conventional, 2=reduced, 3=no-till |
| Tillage depth | cm | Depth of soil disturbance |
| Mixing efficiency | fraction | Residue incorporation efficiency (0-1) |
| Inversion | boolean | Whether tillage inverts the soil profile |

### Tile Drainage Parameters

| Parameter | Unit | Description |
|-----------|------|-------------|
| Drain present | boolean | Whether tile drainage is active |
| Drain depth | cm | Depth of drain tiles |
| Drain spacing | m | Horizontal distance between drains |
| Drain coefficient | 1/day | Drainage rate coefficient |

---

## Key Output Variables

| Variable | Unit | Description |
|----------|------|-------------|
| Crop yield | kgC/ha | Harvested grain carbon |
| Total biomass | kgC/ha | Total above + below-ground biomass carbon |
| N2O emission | kgN/ha | Annual nitrous oxide emission from soil |
| NO emission | kgN/ha | Annual nitric oxide emission |
| NH3 volatilization | kgN/ha | Ammonia loss to atmosphere |
| CO2 emission | kgC/ha | Soil heterotrophic respiration |
| CH4 emission | kgC/ha | Methane emission (relevant for rice/wetland) |
| NO3 leaching | kgN/ha | Nitrate leached below root zone or to tile drains |
| N uptake | kgN/ha | Total plant nitrogen uptake |
| SOC change | kgC/ha | Change in soil organic carbon stock |
| Water drainage | cm | Total water drained from profile or tiles |
| Evapotranspiration | cm | Total ET (soil evaporation + transpiration) |
| Soil temperature | deg C | Profile soil temperature (by layer) |
| WFPS | fraction | Water-filled pore space (by layer) |
| DOC leaching | kgC/ha | Dissolved organic carbon leaching |

---

## Tool Reference

| Tool | Script | Lines | Purpose |
|------|--------|-------|---------|
| Climate Converter | `tools/convert_climate_to_dndc.py` | ~350 | Global forcing data to DNDC type-5 climate file |
| Soil Converter | `tools/convert_soil_to_dndc.py` | ~300 | HWSD/SoilGrids/custom data to DNDC soil profile |
| Execution Wrapper | `tools/run_dndc.py` | ~250 | Assemble batch file and execute DNDC95.exe |
| Output Parser | `tools/parse_dndc_output.py` | ~400 | Parse DNDC output to clean CSV and metrics |

### convert_climate_to_dndc.py

Converts global meteorological datasets to DNDC daily climate format (type 5).

**Key conversions performed**:
- Precipitation: mm/day to cm/day (divide by 10)
- Radiation: W/m2 to MJ/m2/day (multiply by 0.0864)
- Temperature: Kelvin to deg C (subtract 273.15) if needed
- Humidity: fraction to percent (multiply by 100) if needed
- Validates: Jday sequence 1-365/366, MaxT >= MinT, Prec >= 0, Radiation >= 0

**Supported input sources**: NASA POWER, ERA5, CMFD, MSWX, Daymet, GridMET, custom CSV.

### convert_soil_to_dndc.py

Converts soil database information to DNDC soil profile format.

**Key conversions performed**:
- SOC from percent or g/kg to kgC/kg soil
- Bulk density validation (1.0-2.0 g/cm3 range)
- Texture classification to DNDC texture ID (1-12)
- Hydraulic conductivity to m/hr
- Field capacity and wilting point to WFPS units
- Fills 200 cm profile, extrapolating deeper layers if source data is shallow

### run_dndc.py

Assembles batch configuration and executes DNDC95.exe.

**Features**:
- Auto-detects Windows vs Linux (Wine) execution environment
- Generates batch file from list of .dnd file paths
- Monitors execution with timeout protection
- Captures Wine/Windows stderr for error diagnosis
- Validates output directory creation and file generation

### parse_dndc_output.py

Parses DNDC output files into structured pandas DataFrames and CSV files.

**Features**:
- Reads batch output from Result/Record/Batch/ or single-run from Result/Record/Site/
- Extracts annual summaries: yield, GHG emissions, N balance, water balance, SOC
- Extracts daily time series (if -daily 1 flag was used)
- Computes derived metrics: yield-scaled N2O, N use efficiency, water use efficiency
- Generates multi-site comparison tables for batch runs

---

## Version History (DNDCv.CAN)

| Version | Date | Key Changes |
|---------|------|-------------|
| 9.6.0 | 2024 | New biosolid C pool, improved pH sensitivity in NH4:NH3, improved RUE, improved soil temperature on C decomposition, inversion tillage, winter-spring N2O burst, frostkill sensitivity for cover crops |
| 9.5.6 | Sept 2023 | Urea movement removed from water flux, root/AG respiration parameters, dynamic layer depth, preferential flow toggle, soybean pod fraction |

**Known issues (v9.5.6+)**:
- Inhibitor products are globally active during their parameterized timing (not per-event)
- Dynamic layer depth can break simulation if set too small (minimum 1 cm)

---

## Diagnostic Triplets Summary

See `diagnostics/triplets.yaml` for the full set. Key entries:

| ID | Symptom | Root Cause |
|----|---------|------------|
| dt_01 | N2O emissions 10x too high, waterlogged soil | Precipitation in mm instead of cm |
| dt_02 | Zero crop growth, no biomass | Wrong climate format type or missing climate file |
| dt_03 | Model crash on startup | Malformed .dnd file (missing section or wrong line count) |
| dt_04 | Unrealistic soil temperature | Elevation in feet instead of meters |
| dt_05 | SOC depletes to zero in 2-3 years | SOC in percent instead of kgC/kg (100x too high initial decomposition) |
| dt_06 | No tile drainage output | Drain depth/spacing = 0 or drain toggle off |
| dt_07 | Crop yield is zero but biomass grows | Harvest date before crop maturity (insufficient thermal degree days) |
| dt_08 | Radiation-driven variables all wrong | Radiation in W/m2 instead of MJ/m2/day |
| dt_09 | Wine execution fails silently | Missing DLL files or wrong Wine architecture (need 32-bit) |

---

## Quick Start

```bash
# 1. Set up workspace
mkdir -p dndc_workspace/inputs dndc_workspace/climate dndc_workspace/Result
cp DNDC95.exe dndc_workspace/

# 2. Prepare climate file (type 5 format, precipitation in CM)
python tools/convert_climate_to_dndc.py \
    --input forcing_data.csv \
    --output dndc_workspace/climate/mysite_2020.txt \
    --source nasa_power \
    --year 2020

# 3. Prepare soil and assemble DND file
python tools/convert_soil_to_dndc.py \
    --input soil_data.csv \
    --lat 45.5 --lon -75.5 \
    --output dndc_workspace/inputs/mysite.dnd

# 4. Create batch file
echo "1" > dndc_workspace/batch_file.txt
echo "inputs/mysite.dnd" >> dndc_workspace/batch_file.txt

# 5. Run DNDC
cd dndc_workspace
wine DNDC95.exe -s batch_file.txt -daily 0 -output Result/

# 6. Parse outputs
python tools/parse_dndc_output.py \
    --input Result/Record/Batch/ \
    --output results_summary.csv
```

---

## Coupling Points

- **Climate forcing**: ERA5, NASA POWER, CMFD, MSWX, Daymet, GridMET -- convert to type-5 format
- **Soil data**: HWSD, SoilGrids, SSURGO/SDA, ISRIC -- convert to DNDC soil profile
- **Yield comparison**: Statistics Canada CANSIM, USDA NASS, FAO FAOSTAT
- **GHG validation**: Eddy covariance (N2O, CO2), static chamber measurements
- **Water balance**: Lysimeter data, tile drain monitoring, soil moisture sensors
- **Multi-model comparison**: DNDC has been benchmarked against DayCent, EPIC, RZWQM2, APSIM, Holos
