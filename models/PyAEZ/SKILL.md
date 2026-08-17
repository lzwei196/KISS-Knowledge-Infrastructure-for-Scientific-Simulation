---
name: pyaez
description: >-
  FAO/IIASA Agro-Ecological Zoning (AEZ/GAEZ) framework as implemented in PyAEZ 2.2
  (six-module land-evaluation pipeline). Covers Thermal climate and thermal zone
  classification; Length of Growing Period (LGP) via reference-crop soil water balance;
  Penman-Monteith reference evapotranspiration (ETo); Temperature sums/profiles, air frost
  index and permafrost evaluation. Use when the task involves running, configuring,
  calibrating or interpreting PyAEZ.
---

> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/FAOSTAT/SKILL.md` for crop yield observations.
See `data_ki/SPAM/SKILL.md` for gridded yield data.

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

# PyAEZ v2.2 Knowledge Infrastructure

**Package**: hydrocraft-pyaez-crop v1.0.0
**Stats**: 5 tools | 6 skill documents | 15+ diagnostic triplets | 6 pipeline stages

## Overview

PyAEZ is a Python implementation of the FAO Agro-Ecological Zoning (AEZ) framework.
It classifies land into zones of similar agricultural potential by combining climate,
soil, terrain, and economic data to estimate attainable crop yields and suitability.

The model runs as a sequential 6-module pipeline:

1. **Module I – Climate Regime**: Compute thermal climate, thermal zones, LGP, ETo, permafrost
2. **Module II – Crop Simulation**: Simulate biomass accumulation and water-limited yield for 365 planting dates
3. **Module III – Climatic Constraints**: Apply agro-climatic reduction factors (fc3)
4. **Module IV – Soil Constraints**: Apply soil quality reduction factors (fc4) from HWSD
5. **Module V – Terrain Constraints**: Apply terrain/slope erosion factors (fc5) via Fournier Index
6. **Module VI – Economic Suitability**: Net revenue analysis from cost/price data

Final yield = Potential_Yield × fc1 × fc2 × fc3 × fc4 × fc5

**Key characteristics**:
- Pixel-wise iteration over spatial grids (height × width)
- Numba JIT compilation for ETOCalc, LGPCalc, CropWatCalc (10-100× speedup)
- External lookup tables from Excel (xlsx) for all reduction factors
- Supports monthly (interpolated to daily) or daily climate inputs
- Rainfed vs irrigated pathways throughout
- Perennial and annual crop modes

## Installation

```bash
# Create and activate virtual environment
python3 -m venv /path/to/venv
source /path/to/venv/bin/activate

# Install from PyPI
pip install pyaez==2.2

# Or install from source
git clone https://github.com/gicait/PyAEZ.git
cd PyAEZ
pip install -e .

# Dependencies (auto-installed)
# numpy>=1.23, pandas==1.5.3, scipy, GDAL>=3.4.3, numba>=0.56, llvmlite>=0.40.1
```

**GDAL Note**: GDAL pip install often fails. Use conda or system package:
```bash
conda install -c conda-forge gdal
# or: sudo apt install gdal-bin libgdal-dev && pip install GDAL==$(gdal-config --version)
```

**Test installation**:
```python
import pyaez
from pyaez import ClimateRegime, CropSimulation, UtilitiesCalc
print("PyAEZ imported successfully")
```

## Pipeline Stages

| # | Stage | Module | Tool(s) | Description |
|---|-------|--------|---------|-------------|
| 0 | Data Preparation | — | `convert_forcing.py`, `convert_soil.py` | Convert forcing/soil data to NumPy arrays |
| 1 | Climate Regime | Module I | `run_pyaez.py` | Thermal climate, LGP, ETo, permafrost |
| 2 | Crop Simulation | Module II | `run_pyaez.py` | Biomass + water-limited yield per pixel |
| 3 | Climatic Constraints | Module III | `run_pyaez.py` | fc3 reduction via LGP/temperature classes |
| 4 | Soil Constraints | Module IV | `run_pyaez.py` | fc4 from SQ1–SQ7 soil qualities |
| 5 | Terrain Constraints | Module V | `run_pyaez.py` | fc5 from Fournier Index × slope class |
| 6 | Economic Analysis | Module VI | `run_pyaez.py` | Net revenue and suitability classification |
| 7 | Output Parsing | — | `parse_output.py` | Extract results to CSV tables |

### Data Flow

```
Climate data (npy/tif) ─┐
Elevation (tif) ────────┤
Admin mask (tif) ───────┤
                        ▼
              ┌─────────────────┐
              │ Module I:       │
              │ ClimateRegime   │──→ LGP, ETo, thermal zones, profiles
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
Crop params   │ Module II:      │
(xlsx) ───────│ CropSimulation  │──→ yield_rain, yield_irr, fc1, fc2
              └────────┬────────┘
                       ▼
fc3 tables    ┌─────────────────┐
(xlsx) ───────│ Module III:     │──→ climate-adjusted yield
              │ ClimaticConstr. │
              └────────┬────────┘
                       ▼
Soil map +    ┌─────────────────┐
SQ tables     │ Module IV:      │──→ soil-adjusted yield, fc4
(xlsx) ───────│ SoilConstraints │
              └────────┬────────┘
                       ▼
Slope map +   ┌─────────────────┐
terrain       │ Module V:       │──→ terrain-adjusted yield, fc5
tables (xlsx) │ TerrainConstr.  │
              └────────┬────────┘
                       ▼
Cost/price    ┌─────────────────┐
data ─────────│ Module VI:      │──→ net revenue, suitability class
              │ EconomicSuit.   │
              └─────────────────┘
```

## Input Data Requirements

### Climate Data
All arrays: shape `(height, width, 12)` for monthly or `(height, width, 365)` for daily.

| Variable | Name in Code | Unit | Notes |
|----------|-------------|------|-------|
| Min temperature | `min_temp` | °C | NOT Kelvin |
| Max temperature | `max_temp` | °C | NOT Kelvin |
| Precipitation | `precipitation` | mm/day | NOT mm/month, NOT m/day |
| Solar radiation | `short_rad` | W/m² | Shortwave downward |
| Wind speed | `wind_speed` | m/s | At 2m height |
| Relative humidity | `rel_humidity` | 0–1 (fraction) | NOT 0–100 percent |

### Spatial Data
| File | Format | Unit | Notes |
|------|--------|------|-------|
| Elevation | GeoTIFF | meters | DEM |
| Admin mask | GeoTIFF | binary 0/1 | 0 = excluded |
| Slope | GeoTIFF | percent (%) | For Module V |
| Soil map | GeoTIFF | integer SMU codes | Maps to HWSD |

### Crop Parameters (Excel)
| Sheet/Column | Unit | Description |
|-------------|------|-------------|
| LAI | unitless | Leaf Area Index (2–6 typical) |
| HI | 0–1 | Harvest Index |
| adaptability | 1–4 | Crop photosynthesis class |
| min/max_cycle_length | days | Crop cycle bounds |
| height | meters | Canopy height |
| kc (3 values) | unitless | Crop coefficients: initial, mid, end |
| yloss_f (4 values) | 0–1 | Yield loss factors per growth stage |
| est_yield | kg/ha | Reference potential yield |
| D1, D2 | meters | Rooting depths |
| pc | 0–1 | Soil water depletion fraction |

## Output Variables

| Variable | Unit | Module | Description |
|----------|------|--------|-------------|
| thermal_climate | class 1–12 | I | Thermal climate classification |
| thermal_zone | class 1–12 | I | Thermal zone |
| lgp | days | I | Length of Growing Period |
| lgpt5, lgpt10 | days | I | Thermal LGP at 5°C, 10°C thresholds |
| tsum0, tsum5, tsum10 | °C·days | I | Temperature accumulation |
| pet_daily | mm/day | I | Penman-Monteith reference ETo |
| yield_rain | kg/ha | II | Rainfed maximum attainable yield |
| yield_irr | kg/ha | II | Irrigated maximum attainable yield |
| fc1 | 0–1 | II | Thermal screening reduction factor |
| fc2 | 0–1 | II | Moisture/water reduction factor |
| fc3 | 0–1 | III | Agro-climatic constraint factor |
| fc4 | 0–1 | IV | Soil constraint factor |
| fc5 | 0–1 | V | Terrain constraint factor |
| net_revenue | currency/ha | VI | Net revenue map |

## Unit Trap Table

These are the most common silent-failure unit errors when feeding data into PyAEZ:

| # | Variable | PyAEZ Expects | Common Source | Trap | Fix |
|---|----------|--------------|---------------|------|-----|
| 1 | Temperature | °C | Kelvin (CMFD, MSWX) | Values ~300 interpreted as 300°C → NaN yield | Subtract 273.15 |
| 2 | Rel. Humidity | 0–1 fraction | 0–100% (CMFD rhum) | Values >1 → huge ETo → zero yield | Divide by 100 |
| 3 | Precipitation | mm/day | mm/month, m/day | mm/month → 30× too high; m/day → 1000× too low | ÷ days_in_month or × 1000 |
| 4 | Radiation | W/m² | MJ/m²/day (ERA5) | 1 MJ/m²/day = 11.574 W/m² | Multiply by 11.574 |
| 5 | Wind speed | m/s at 2m | m/s at 10m | 10m wind ~1.5× too high → excess ETo | u2 = u10 × 4.87/ln(67.8×10-5.42) |
| 6 | Elevation | meters | feet, km | Affects pressure calc, ETo | Convert to meters |
| 7 | Slope | percent (%) | degrees, radians | 45° = 100%; radians totally wrong | tan(degrees) × 100 |
| 8 | Latitude | decimal degrees | Sign convention | S hemisphere must be negative | Check sign |
| 9 | Precip array axis | (H, W, T) | (T, H, W) | Silent wrong values per pixel | np.transpose |
| 10 | Crop yield | kg/ha | ton/ha | Off by 1000× | Multiply by 1000 |
| 11 | Sa (soil moisture) | mm/m | mm total, cm/m | Wrong soil water capacity | Convert to mm/m |
| 12 | Pressure (internal) | kPa | Pa, hPa, mbar | Auto-calculated from elevation | Verify elevation |
| 13 | Radiation (biomass) | cal/cm²/day | W/m² internally | Conversion factor: 2.06362854686156 | Handled internally |
| 14 | Monthly→daily | 12 values | 365 values | Wrong array length → index error | Check data shape |

## Tools Reference

| Tool | Stage | Script | Purpose |
|------|-------|--------|---------|
| `convert_forcing.py` | 0 | `tools/convert_forcing.py` | Convert CMFD/MSWX → PyAEZ NumPy arrays |
| `convert_soil.py` | 0 | `tools/convert_soil.py` | Convert HWSD raster → soil map + Excel params |
| `run_pyaez.py` | 1–6 | `tools/run_pyaez.py` | Execute full PyAEZ pipeline |
| `parse_output.py` | 7 | `tools/parse_output.py` | Parse GeoTIFF outputs → CSV summary |

## Critical Domain Knowledge

### 1. Temperature MUST be in Celsius (dt_001)
PyAEZ expects °C throughout. CMFD and MSWX provide Kelvin. Feeding Kelvin directly
produces mean temperatures of ~300°C, causing NaN in all calculations.
**Fix**: `temp_C = temp_K - 273.15`

### 2. Relative Humidity is Fraction 0–1, NOT Percentage (dt_002)
The `rel_humidity` array must be 0–1. CMFD `rhum` is 0–100%. Feeding 0–100 directly
causes Penman-Monteith ETo to become extremely large → LGP = 0 everywhere.
**Fix**: `rh_frac = rh_pct / 100.0`

### 3. Precipitation is mm/day, NOT mm/month (dt_003)
Monthly precipitation totals must be divided by days in each month before input.
Otherwise PyAEZ sees 30× too much rain → P/PET ratio inflated → wrong LGP class.
**Fix**: `precip_daily = precip_monthly / days_in_month`

### 4. Climate Arrays Must Be (H, W, T) Order (dt_004)
All 3D climate arrays must have shape (height, width, time). Many NetCDF files store
(time, lat, lon). Transposing incorrectly gives wrong values per pixel with no error.
**Fix**: `np.transpose(data, (1, 2, 0))`

### 5. Latitude Min/Max Controls Interpolation (dt_005)
`lat_min` and `lat_max` define the spatial extent for latitude-dependent calculations
(solar declination, day length). Swapping them or using wrong values silently corrupts
ETo and biomass for every pixel.

### 6. Wind Speed Must Be at 2m Height (dt_006)
Penman-Monteith assumes 2m measurement height. Using 10m wind (CMFD default) without
height correction overestimates ETo by ~20%.
**Fix**: `u2 = u10 * 4.87 / math.log(67.8 * 10 - 5.42)`

### 7. Monthly Data Interpolated via Cubic Spline (dt_007)
When `daily=False`, PyAEZ interpolates 12 monthly values to 365 daily values using
cubic spline at mid-month DOY points (15, 45, 75, ..., 345). This can produce negative
precipitation. The code does NOT clamp negatives automatically.

### 8. Soil Water Parameters Default to Sa=100, D=1.0 (dt_008)
If not explicitly set, soil available moisture = 100 mm/m and rooting depth = 1.0 m.
These defaults strongly affect fc2 (water constraint). Always provide site-specific values.

### 9. Module II Is Extremely Slow Without Numba (dt_009)
CropSimulation iterates 365 planting dates × all pixels. Without Numba JIT compilation,
a 100×100 grid can take hours. Ensure numba is installed and working.

## Validation Results

### Laos Maize Example (Built-in Test Case)
The repository includes a complete Laos maize example with pre-computed outputs.
This serves as the reference validation case.

- **Region**: Laos (13.87°N – 22.59°N)
- **Crop**: Maize (rainfed and irrigated)
- **Climate**: TerraClimate monthly data
- **Soil**: HWSD-derived soil mapping units
- **Pipeline**: Full NB1→NB6 sequence

## Quick Start

```python
import numpy as np
from osgeo import gdal
from pyaez import ClimateRegime, CropSimulation, UtilitiesCalc

# 1. Load data
max_temp = np.load('climate/max_temp.npy')       # (H, W, 12) in °C
min_temp = np.load('climate/min_temp.npy')        # (H, W, 12) in °C
precip   = np.load('climate/precipitation.npy')   # (H, W, 12) in mm/day
humidity = np.load('climate/relative_humidity.npy')# (H, W, 12) in 0-1
wind     = np.load('climate/wind_speed.npy')       # (H, W, 12) in m/s
srad     = np.load('climate/short_rad.npy')        # (H, W, 12) in W/m²

mask = gdal.Open('LAO_Admin.tif').ReadAsArray()
elev = gdal.Open('LAO_Elevation.tif').ReadAsArray()

# 2. Module I: Climate Regime
clim = ClimateRegime.ClimateRegime()
clim.setStudyAreaMask(mask, 0)
clim.setLocationTerrainData(lat_min=13.87, lat_max=22.59, elevation=elev)
clim.setMonthlyClimateData(min_temp, max_temp, precip, srad, wind, humidity)

lgp = clim.getLGP(Sa=100, D=1)
lgp5 = clim.getThermalLGP5()
lgp10 = clim.getThermalLGP10()

# 3. Module II: Crop Simulation
sim = CropSimulation.CropSimulation()
sim.setStudyAreaMask(mask, 0)
sim.setLocationTerrainData(lat_min=13.87, lat_max=22.59, elevation=elev)
sim.setMonthlyClimateData(min_temp, max_temp, precip, srad, wind, humidity)
sim.readCropandCropCycleParameters('input_crop_TSUM_parameters_maiz_sugar.xlsx', 'maize')
sim.setSoilWaterParameters(Sa=100*np.ones(mask.shape), pc=0.5)
sim.ImportLGPandLGPT(lgp=lgp, lgpt5=lgp5, lgpt10=lgp10)
sim.simulateCropCycle(start_doy=1, end_doy=365, step_doy=1, leap_year=False)

yield_rain = sim.getEstimatedYieldRainfed()   # kg/ha
yield_irr  = sim.getEstimatedYieldIrrigated() # kg/ha
```

## Diagnostic Triplets Summary

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | critical | unit_conversion | Temperature in K instead of °C |
| dt_002 | critical | unit_conversion | Relative humidity % instead of fraction |
| dt_003 | critical | unit_conversion | Precipitation mm/month instead of mm/day |
| dt_004 | critical | array_format | Climate array axis order wrong |
| dt_005 | high | parameter | Latitude min/max swapped or wrong |
| dt_006 | medium | unit_conversion | Wind speed at wrong height |
| dt_007 | medium | interpolation | Cubic spline produces negative precip |
| dt_008 | medium | parameter | Default soil water parameters used |
| dt_009 | medium | performance | Numba not installed, extremely slow |
| dt_010 | high | data_format | Mask value incorrect, all pixels excluded |
| dt_011 | high | file_io | Excel crop parameter sheet missing columns |
| dt_012 | medium | unit_conversion | Radiation MJ/m²/day instead of W/m² |
| dt_013 | critical | data_format | Soil map codes don't match Excel SMU IDs |
| dt_014 | medium | unit_conversion | Slope in degrees instead of percent |
| dt_015 | low | output | Yield in kg/ha, user expects ton/ha |

## File Structure

```
ki/
├── SKILL.md                          # This file
├── knowledge_infrastructure.yaml     # Machine-readable schema
├── tools/
│   ├── convert_forcing.py           # CMFD/MSWX → PyAEZ format
│   ├── convert_soil.py              # HWSD → soil map + params
│   ├── run_pyaez.py                 # Execute pipeline
│   └── parse_output.py             # GeoTIFF → CSV extraction
├── docs/
│   ├── s0_data_preparation.md       # Input data conversion
│   ├── s1_climate_regime.md         # Module I skill doc
│   ├── s2_crop_simulation.md        # Module II skill doc
│   ├── s3_climatic_constraints.md   # Module III skill doc
│   ├── s4_soil_constraints.md       # Module IV skill doc
│   └── s5_terrain_economic.md       # Modules V–VI skill doc
└── diagnostics/
    └── triplets.yaml                # 15 symptom→diagnosis→remedy entries
```
