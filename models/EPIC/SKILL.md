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

# EPIC (Geo-EPIC) Crop Model — Knowledge Infrastructure

**Package**: `hydrocraft-epic-crop` v1.0.0
**Model**: EPIC 1102 via Geo-EPIC-win toolkit
**Source**: https://github.com/smarsGroup/geo_epic_win
**Domain**: Crop growth simulation and yield estimation
**Last updated**: 2026-03-28
**Stats**: 4 tools | 7 skill documents | 18 diagnostic triplets | ~1,600 lines of validated Python

---

## Overview

EPIC (Environmental Policy Integrated Climate) is a field-scale crop growth simulation model
developed by USDA. The Geo-EPIC toolkit (geo_epic_win) extends EPIC to geospatial scales,
enabling simulation of crop growth across large geographies (states, counties) by leveraging
remote sensing and geospatial databases. It includes modules for weather data acquisition,
soil data fetching from SSURGO/ISRIC, operation schedule management, and calibration.

**What EPIC simulates**:
- Crop growth and development (phenology, biomass accumulation, LAI)
- Yield estimation for 60+ crop types
- Soil water balance (infiltration, evapotranspiration, drainage)
- Nitrogen and phosphorus cycling
- Erosion (wind and water)
- Tillage and management effects
- Irrigation scheduling (auto-irrigation option)
- Multi-year crop rotations

**Key difference from other models**: EPIC operates at field/site scale (not gridded).
Geo-EPIC provides the geospatial framework to run many sites in parallel with
automated input generation from remote sensing and national databases.

---

## Installation

### Python Package

```bash
conda create --name epic_env python=3.11
conda activate epic_env
pip install git+https://github.com/smarsGroup/geo_epic_win.git
```

### EPIC Binary

The EPIC executable (EPIC1102.exe) is bundled with the package in the assets directory.
On Linux, the toolkit applies `chmod +x` automatically. The binary is a Windows PE
executable that may require Wine on Linux, or the toolkit handles cross-platform execution.

```
Binary:      src/geoEpic/assets/workspace_win/model/EPIC1102.exe
Version:     EPIC 1102
Config:      EPICCONT.DAT, EPICFILE.DAT, EPICRUN.DAT, PRNT1102.DAT
Crop DB:     CROPCOM.DAT (60+ crop parameterizations)
Parameters:  PARM.DAT (112 global parameters + 60 crop-specific)
```

### Key Dependencies

```
numpy<2.0.0, pandas>=2.2.0, geopandas==1.0.1, xarray==2024.7.0,
scipy==1.14.0, scikit-learn==1.5.1, matplotlib==3.9.2,
rasterio, netCDF4, ruamel.yaml==0.17, earthengine-api==1.0.0,
SALib==1.5.1, pydap==3.4.1, lmdb, redis, pebble
```

### CLI Entry Point

```bash
geo_epic <command> [options]
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Create config.yml, define experiment, region, model path |
| 1 | Weather | `convert_weather_to_dly` | Fetch/convert weather data to EPIC .DLY format |
| 2 | Soil | `convert_soil_to_sol` | Fetch SSURGO/ISRIC soil data, write .SOL and .SIT files |
| 3 | Operations | (manual/OPC tools) | Create/edit .OPC files for crop management schedules |
| 4 | Workspace | `run_epic_workspace` | Assemble workspace, link files, generate EPICRUN.DAT |
| 5 | Execution | `run_epic_workspace` | Run EPIC binary for all sites in parallel |
| 6 | Output | `parse_epic_output` | Parse ACY/DGN files, extract yield and biomass |

---

## File Formats

### DLY (Daily Weather) — Input

Fixed-width Fortran format: `%6d%4d%4d%6.2f%6.2f%6.2f%6.2f%6.2f%6.2f`

| Column | Width | Variable | Unit | Description |
|--------|-------|----------|------|-------------|
| 1 | 6 | year | - | 4-digit year |
| 2 | 4 | month | - | Month (1-12) |
| 3 | 4 | day | - | Day (1-31) |
| 4 | 6 | srad | MJ/m2/day | Solar radiation |
| 5 | 6 | tmax | deg C | Maximum temperature |
| 6 | 6 | tmin | deg C | Minimum temperature |
| 7 | 6 | prcp | mm/day | Precipitation |
| 8 | 6 | rh | fraction (0-1) | Relative humidity |
| 9 | 6 | ws | m/s | Wind speed |

**Example line**: `  1922   1   1  10.7  8.33 -3.33  0.00  0.71  2.08`

The last line of the DLY file contains station metadata:
`STATION = name  STA ID = id  STATE = st  CO = county  LAT = lat  LONG = lon  ELEV = elev  Y-M-D end_date`

### WP1 (Monthly Weather Statistics) — Generated from DLY

14 parameters x 12 months: OBMX, OBMN, RST2, OBSL, RH, UAVO, SDTMX, SDTMN,
RST2_std, DAYP, RST3, PRW1, PRW2, WI

### SOL (Soil Profile) — Input

Fixed-width format (`%8.3f` per value), 42 lines minimum:

| Line | Content |
|------|---------|
| 1 | Soil ID header |
| 2 | Albedo (8.3f), Hydrological group (A=1, B=2, C=3, D=4) |
| 3 | Number of layers after split (typically 10) |
| 4-22 | 19 soil properties, one row per property, columns = layers |

**Soil Layer Properties (19 rows)**:
1. Layer_depth (cm)
2. Bulk_Density (g/cm3)
3. Wilting_capacity (fraction)
4. Field_Capacity (fraction)
5. Sand_content (%)
6. Silt_content (%)
7. N_concen (mg/kg)
8. pH
9. Sum_Bases (meq/100g)
10. Organic_Carbon (%)
11. Calcium_Carbonate (%)
12. Cation_exchange (meq/100g)
13. Coarse_Fragment (%)
14. Saturated_conductivity (mm/hr)
15-19. Additional properties (pkrz, rsd, BD_dry, psp, Ksat)

### SIT (Site Information) — Input

| Line | Content |
|------|---------|
| 1 | Description text |
| 2 | Prototype name |
| 3 | Site ID |
| 4 | Lat(8.2f) Lon(8.2f) Elev_m(8.2f) ... |
| 5 | ... Slope_length_m(8.2f) Slope_steepness(8.2f) ... |
| 6-7 | Additional parameters |

### OPC (Operation Schedule) — Input

Fixed-width format with 15 columns:

| Column | Width | Variable | Description |
|--------|-------|----------|-------------|
| Yid | 3 | Year ID | Relative year (1 = start_year) |
| Mn | 3 | Month | 1-12 |
| Dy | 3 | Day | 1-31 |
| CODE | 5 | Op code | Operation type (see below) |
| TRAC | 5 | Tractor | Equipment ID |
| CRP | 5 | Crop | Crop code from CROPCOM.DAT |
| XMTU | 5 | Context | Fertilizer/pesticide/layer ID |
| OPV1-8 | 8 each | Params | Operation-specific parameters |

**Key Operation Codes**:
- 2, 3, 4, 146: Planting (OPV1 = PHU thermal units)
- 650: Harvest
- 71: Fertilizer application (XMTU = fert ID, OPV1 = rate kg/ha)
- 72: Auto-irrigation activation
- 41: Residue management
- 9: Fallow

### ACY (Annual Crop Yield) — Output

Whitespace-delimited, skip first 10 rows. Key columns: YR, CPNM, YLDG, YLDF, BIOM, ...

### DGN (Daily General) — Output

Whitespace-delimited, skip first 10 rows. Key columns: Y, M, D, BIOM, RW, LAI, WS, ...
Above-ground biomass: AGB = BIOM - RW

---

## Unit Trap Table

| Variable | Source Unit | EPIC Unit | Conversion | Trap |
|----------|-----------|-----------|------------|------|
| Solar radiation (Daymet) | W/m2 | MJ/m2/day | srad * dayl / 1e6 | Omitting dayl gives ~86x overestimate |
| Solar radiation (GridMET) | W/m2 | MJ/m2/day | srad * 0.0864 | Using W/m2 directly → unrealistic values |
| Temperature (GridMET) | K | deg C | T - 273.15 | Kelvin in DLY → crash or unrealistic growth |
| Temperature (CMFD) | K | deg C | T - 273.15 | Same as above |
| Precipitation (CMFD 3hr) | mm/3hr | mm/day | sum 8 timesteps | Must aggregate, not average |
| Relative humidity (Daymet) | vapor pressure (Pa) | fraction (0-1) | rh_vappr formula | Wrong formula → RH > 1 or < 0 |
| Relative humidity (GridMET) | % (rmax, rmin) | fraction (0-1) | avg(rmax,rmin)/100 | Forgetting /100 → RH=70 not 0.70 |
| Wind speed | m/s | m/s | None | No conversion needed |
| Soil bulk density | g/cm3 | g/cm3 | None | Using kg/m3 → 1000x error |
| Layer depth (SSURGO) | cm | cm | None | Using inches → 2.54x error |
| Hydraulic conductivity | um/s (SSURGO) | mm/hr | ksat * 3.6 | SSURGO ksat in um/s, EPIC expects mm/hr |
| Organic matter → OC | % OM | % OC | OM / 1.724 | Van Bemmelen factor, not direct copy |
| Fertilizer rate | kg/ha | kg/ha | None | lb/ac → kg/ha requires * 1.121 |
| Elevation | m | m | None | Using ft → 0.3048x error in weather gen |
| PHU (thermal units) | deg C-day | deg C-day | None | Wrong PHU → crop never matures or matures early |
| Slope steepness | fraction | fraction | None | Using degrees or % without conversion |

---

## Workspace Structure

```
workspace_root/
├── config.yml            # Main configuration (YAML)
├── info.csv              # Site list: SiteID, soil, dly, opc, lat, lon
├── model/                # EPIC executable + config files
│   ├── EPIC1102.exe      # Binary
│   ├── EPICCONT.DAT      # Control parameters (duration, start date)
│   ├── EPICFILE.DAT      # Logical→physical file mapping
│   ├── EPICRUN.DAT       # Run configuration
│   ├── PRNT1102.DAT      # Output type toggles
│   ├── CROPCOM.DAT       # Crop parameter database (60+ crops)
│   ├── PARM.DAT          # Model parameters (112 global + 60 crop)
│   ├── FERT2012.DAT      # Fertilizer database
│   ├── PESTCOM.DAT       # Pesticide database
│   └── ...               # Other DAT files
├── weather/              # .DLY daily weather files
├── soil/                 # .SOL soil profile files
├── sites/                # .SIT site information files
├── opc/                  # .OPC operation schedule files
│   └── crop_templates/   # Template OPC files + MAPPING
├── output/               # Simulation outputs (.ACY, .DGN, etc.)
└── log/                  # Execution logs
```

---

## Configuration Reference (config.yml)

```yaml
EXPName: Project Name              # Experiment name
Region: Region name                # Study region
Area_of_Interest: AOI              # Area description

EPICModel: ./model/EPIC1102.exe    # Path to EPIC binary
start_date: '2000-01-01'           # Simulation start (YYYY-MM-DD)
duration: 6                        # Simulation years
output_types:                      # Output file types to enable
  - ACY                            # Annual crop yield
  - DGN                            # Daily general output
log_dir: ./log                     # Log directory
output_dir: ./output               # Output directory

weather_dir: ./weather             # DLY file directory
soil_dir: ./soil                   # SOL file directory
site_dir: ./sites                  # SIT file directory
opc_dir: ./opc                     # OPC file directory

run_info: ./info.csv               # Site list CSV
select: Range(0, 1)                # Site selection filter
timeout: 30                        # Per-site timeout (seconds)
```

---

## Tool Reference

| Tool | Script | Purpose |
|------|--------|---------|
| Weather Converter | `tools/convert_weather_to_dly.py` | NASA POWER/CMFD/MSWX → EPIC .DLY format |
| Soil Converter | `tools/convert_soil_to_sol.py` | HWSD/SoilGrids/SSURGO → EPIC .SOL + .SIT |
| Execution Wrapper | `tools/run_epic_workspace.py` | Configure and run EPIC binary |
| Output Parser | `tools/parse_epic_output.py` | Parse .ACY/.DGN to CSV/DataFrame |

---

## Calibration

EPIC calibration uses PyGMO (Particle Swarm Optimization or Differential Evolution):

1. Define workspace with multiple sites
2. Write `@workspace.logger` function to compute per-site metrics
3. Write `@workspace.objective` function to aggregate metrics
4. Load Parm or CropCom object
5. Call `parm.set_sensitive([param_list])` for parameters to calibrate
6. Create optimization problem: `workspace.make_problem(parm)`
7. Run optimizer (PSO, DE)

**Sensitive Parameters** (from PARM.sens):
- PARM values: 112 global parameters controlling erosion, hydrology, N/P cycling
- SCRP values: 60 crop-specific parameters (30 per set)
- CROPCOM parameters: per-crop growth coefficients

---

## Output File Types (PRNT1102.DAT toggles)

| Extension | Description |
|-----------|-------------|
| ACY | Annual crop yield (default ON) |
| DGN | Daily general output (default ON) |
| ACM | Annual carbon/nitrogen mass |
| DHS | Daily hydrology summary |
| DWC | Daily water chemistry |
| MFS | Monthly field summary |
| MPS | Monthly plant summary |
| ANN | Annual summary |
| SOT | Soil organic turnover |
| MCM | Monthly carbon mass |
| SCO | Scenario comparison |
| DTP | Daily topsoil |
| OUT | General output |
| SUM | Summary |
| DHY | Daily hydrology |
| DPS | Daily plant summary |

---

## Quick Start

```python
from geoEpic.core import Workspace
from geoEpic.io import DLY, SOL, SIT, OPC, ACY, DGN

# 1. Create workspace
ws = Workspace('config.yml')

# 2. Load/edit weather
dly = DLY.load('weather/site1.DLY')
print(dly.data.head())

# 3. Load/edit soil
sol = SOL.load('soil/site1.SOL')
print(sol.data)

# 4. Load/edit operations
opc = OPC.load('opc/site1.OPC')
opc.edit_plantation_date('2020-05-01', crop_code=2)  # Corn
opc.save('opc/site1.OPC')

# 5. Run all sites
ws.run()

# 6. Parse outputs
acy = ACY('output/site1.ACY')
yield_data = acy.get_var('YLDG')
dgn = DGN('output/site1.DGN')
biomass = dgn.get_var('BIOM')
```

---

## Execution Details

The EPIC binary runs per-site in a temporary cache directory:

1. Model directory copied to `/dev/shm/geo_epic_{user}/{uuid}/` (RAM-backed)
2. Weather (.DLY, .WP1, .WND) written as `1.DLY`, `1.WP1`, `1.WND`
3. Site files (.SIT, .SOL, .OPC) copied
4. EPICRUN.DAT updated: `{site_id} 1  0  0  0  1  1  1/`
5. Binary executed with stdin piped
6. Outputs collected from cache to `output_dir`

**EPICCONT.DAT line 1**: `[duration:4][start_year:4][start_month:4][start_day:4]`

---

## Data Sources Integration

| Source | Tool | Variables | Coverage |
|--------|------|-----------|----------|
| Daymet | `weather/daymet.py` | prcp, tmax, tmin, srad, vp, dayl | North America |
| GridMET | `weather/download_daily.py` | tmax, tmin, srad, prcp, rh, wind | CONUS |
| NASA POWER | external | All met variables | Global |
| SSURGO/SDA | `soil/sda.py` | Full soil profile | USA |
| ISRIC/SoilGrids | `spatial/isric.py` | Global soil properties | Global |
| Google Earth Engine | `gee/*.py` | Satellite indices, weather | Global |
| AgERA5 | `spatial/agera5.py` | Agro-meteorological data | Global |
