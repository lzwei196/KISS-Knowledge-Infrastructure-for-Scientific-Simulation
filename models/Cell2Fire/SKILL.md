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

# Cell2Fire W (C2F-W) — Knowledge Infrastructure

**Package**: `hydrocraft-cell2fire-wildfire` v1.0.0
**Model**: Cell2Fire W (C2F-W) — unified Scott&Burgan, FBP-Canada, Kitral fire spread simulator
**Source**: https://github.com/fire2a/C2F-W
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 15+ diagnostic triplets | ~2,000 lines of validated Python
**Validation status**: `build_validated` (Vilopriu 2013, Scott&Burgan model)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for weather forcing documentation.
See `data_ki/MTBS/SKILL.md` for fire perimeter observations.


## Overview

Cell2Fire W is a large-scale, grid-based, wildfire spread simulator written in C++ with OpenMP
parallelism. It supports three fire behavior models:

- **Scott & Burgan (S)**: 40 fuel models from the US NFDRS, widely used in Mediterranean and
  North American ecosystems. Uses wind speed, wind direction, slope, and fuel moisture content.
- **Canadian FBP (C)**: Canadian Forest Fire Behavior Prediction system. 16 fuel types (C-1
  through S-3). Uses FFMC, DMC, DC, ISI, BUI, FWI indices from the Canadian FWI System.
- **Kitral (K)**: Chilean fire behavior model adapted for South American vegetation.
- **Portugal (P)**: Portuguese fire model (experimental).

**What Cell2Fire does**:
- Simulates fire spread on a regular grid (each cell has uniform fuel, elevation, weather)
- Fire propagation is modeled as elliptical spread from cell to cell
- Supports multiple ignition points (random or fixed)
- Outputs burn probability, fire scars, rate of spread, flame length, fire intensity
- Exploits OpenMP parallelism across multiple simulations (Monte Carlo)
- Crown fire initiation and active crown fire spread (with `--cros` flag)
- Spotting (ember transport) modeling

**Key architecture**: The landscape is a 2D grid of cells. Each cell has a fuel type (integer
code), elevation, slope aspect. Weather is uniform across the grid (single station, hourly).
Fire spreads via message-passing between adjacent cells (8-connectivity). The simulator runs
N independent Monte Carlo simulations with different random ignition points and/or weather
scenarios.

---

## Installation

### Dependencies (Debian/Ubuntu)

```bash
sudo apt install g++ libboost-random-dev libtiff-dev make
```

### Compile from source

```bash
cd Cell2Fire/
make          # produces Cell2Fire binary
sudo make install  # optional: copies to /usr/local/bin
```

### Container (Podman/Docker)

```bash
podman build -t cell2fire -f container/Dockerfile .
```

### Test

```bash
mkdir results
./Cell2Fire --input-instance-folder ../data/ScottAndBurgan/Hom_Fuel_101_40x40-asc \
  --output-folder results --nsims 3 --sim S --output-messages --final-grid --seed 123
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 1 | Landscape prep | `convert_landscape_to_c2f` | Prepare fuel, elevation, slope, aspect rasters as ASC/TIF |
| 2 | Weather prep | `convert_weather_to_c2f` | Convert meteorological data to Cell2Fire Weather.csv format |
| 3 | Fuel model config | `convert_fuel_params` | Generate fuel lookup table (spain_lookup_table.csv or fbp_lookup_table.csv) |
| 4 | Ignition config | (manual or tool) | Create Ignitions.csv with cell IDs for fixed ignition points |
| 5 | Execution | `run_cell2fire` | Run Cell2Fire binary with CLI arguments |
| 6 | Output parsing | `parse_cell2fire_output` | Extract burn grids, messages, ROS, intensity to structured CSV |
| 7 | Visualization | (QGIS plugin or custom) | Map burn probability, fire scars, risk metrics |

---

## Input Instance Folder Structure

Each simulation requires an **instance folder** containing:

```
instance_folder/
├── fuels.asc|.tif         # Fuel type grid (integer codes matching lookup table)
├── elevation.asc|.tif     # Elevation grid (meters above sea level)
├── slope.asc|.tif         # Slope grid (degrees, 0-90) [optional for S&B]
├── saz.asc|.tif           # Slope aspect grid (degrees, 0-360, north=0) [optional]
├── cbh.asc|.tif           # Crown base height (m) [S&B with crown fire]
├── cbd.asc|.tif           # Crown bulk density (kg/m³) [S&B with crown fire]
├── ccf.asc|.tif           # Crown closure fraction (%) [S&B]
├── fcc.asc|.tif           # Foliar canopy cover (%) [S&B]
├── cur.asc|.tif           # Curing percentage (%) [FBP only]
├── Weather.csv            # Hourly weather data
├── Weathers/              # Directory with multiple Weather*.csv files (for random weather)
│   ├── Weather1.csv
│   ├── Weather2.csv
│   └── ...
├── Ignitions.csv          # Fixed ignition points (optional)
├── spain_lookup_table.csv # Fuel coefficients lookup (S&B)
├── fbp_lookup_table.csv   # Fuel coefficients lookup (FBP-Canada)
└── probabilityMap.asc     # Ignition probability per cell (optional)
```

### ASC Raster Format (ESRI ASCII Grid)

```
ncols         40
nrows         40
xllcorner     457900
yllcorner     5716800
cellsize      100
NODATA_value  -9999
101 101 101 101 ...
101 101 101 101 ...
```

All rasters must share the same ncols, nrows, cellsize, and corner coordinates.

---

## Weather CSV Formats

### Scott & Burgan (--sim S)

```csv
Instance,datetime,WS,WD,FireScenario
Jaime,2001-10-16 13:00,10,180.0,2
```

| Column | Unit | Description |
|--------|------|-------------|
| Instance | string | Scenario name identifier |
| datetime | YYYY-MM-DD HH:MM | Timestamp (hourly) |
| WS | km/h | Wind speed at 10m height |
| WD | degrees | Wind direction (0-360, meteorological: direction wind comes FROM, north=0) |
| FireScenario | integer | Scenario index (1, 2, or 3 for S&B fire weather severity) |

### Canadian FBP (--sim C)

```csv
Scenario,datetime,APCP,TMP,RH,WS,WD,FFMC,DMC,DC,ISI,BUI,FWI
JCB,2001-10-16 13:00,0.0,17.7,20,21,235,90.5,64,535,13.4,99,37.9
```

| Column | Unit | Description |
|--------|------|-------------|
| Scenario | string | Scenario name identifier |
| datetime | YYYY-MM-DD HH:MM | Timestamp (hourly) |
| APCP | mm | Accumulated precipitation |
| TMP | °C | Temperature |
| RH | % | Relative humidity (0-100) |
| WS | km/h | Wind speed |
| WD | degrees | Wind direction (meteorological convention) |
| FFMC | dimensionless | Fine Fuel Moisture Code (0-101) |
| DMC | dimensionless | Duff Moisture Code |
| DC | dimensionless | Drought Code |
| ISI | dimensionless | Initial Spread Index |
| BUI | dimensionless | Buildup Index |
| FWI | dimensionless | Fire Weather Index |

### Kitral (--sim K)

```csv
Instance,datetime,WS,WD,FireScenario
KitralSP,11/11/13 18:00,26,321.0,1
```

Same format as Scott & Burgan.

---

## Unit Trap Table

| Variable | Cell2Fire Expects | Common Source Unit | Conversion | Trap Severity |
|----------|------------------|--------------------|------------|---------------|
| Wind Speed (WS) | km/h | m/s | × 3.6 | **CRITICAL** — ROS scales ~linearly with wind |
| Wind Direction (WD) | degrees (met. convention, FROM) | degrees (math, TO) | (value + 180) % 360 | **HIGH** — fire spread goes opposite direction |
| Elevation | meters ASL | feet | × 0.3048 | **HIGH** — slope calculation wrong |
| Slope | degrees | percent rise | atan(pct/100) × 180/π | **HIGH** — affects slope factor |
| Slope Aspect (saz) | degrees (compass, north=0) | degrees (math, east=0) | (90 - value) % 360 | **MEDIUM** — affects directional spread |
| Temperature (TMP) | °C | K | − 273.15 | **HIGH** — FBP only |
| Relative Humidity (RH) | % (0-100) | fraction (0-1) | × 100 | **CRITICAL** — FBP fire indices wrong |
| Precipitation (APCP) | mm | m | × 1000 | **HIGH** — FBP only |
| Crown Base Height (cbh) | meters | feet | × 0.3048 | **MEDIUM** |
| Crown Bulk Density (cbd) | kg/m³ | lb/ft³ | × 16.0185 | **MEDIUM** |
| Cell Size | meters | varies | must match raster cellsize | **CRITICAL** — area/distance calculations |
| Fuel Moisture Content (FMC) | % | fraction (0-1) | × 100 | **HIGH** |
| FFMC | 0-101 (dimensionless) | — | must come from FWI System | **HIGH** |
| Fire Period Length | minutes | hours | × 60 | **HIGH** — time step too long/short |

---

## CLI Reference

### Required Arguments

| Flag | Description |
|------|-------------|
| `--input-instance-folder PATH` | Path to instance folder containing rasters and weather |
| `--output-folder PATH` | Path to empty output directory |
| `--sim {S,C,K,P}` | Fire model: S=Scott&Burgan, C=Canadian FBP, K=Kitral, P=Portugal |

### Key Optional Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--nsims N` | 1 | Number of Monte Carlo simulations |
| `--seed N` | 123 | Random seed for reproducibility |
| `--nthreads N` | 1 | Number of OpenMP threads |
| `--Weather-Period-Length N` | 60 | Minutes per weather observation period |
| `--Fire-Period-Length F` | 1.0 | Fire time step in minutes (≤ Weather-Period-Length) |
| `--max-fire-periods N` | -1 (unlimited) | Maximum fire periods to simulate |
| `--fmc N` | 100 | Foliar moisture content (%) for Scott&Burgan |
| `--scenario N` | 3 | S&B fire weather scenario (1=low, 2=moderate, 3=extreme) |
| `--weather {rows,random}` | rows | Weather selection mode |
| `--ignitions` | false | Use Ignitions.csv for fixed ignition points |
| `--IgnitionRad N` | 0 | Radius of ignition area (cells) |
| `--cros` | false | Enable crown fire spread |
| `--ROS-Threshold F` | 0.1 | Minimum ROS to propagate fire (m/min) |
| `--ROS-CV F` | 0.0 | Coefficient of variation for ROS stochasticity |
| `--HFactor F` | 1.0 | Head fire ROS multiplier |
| `--FFactor F` | 1.0 | Flank fire ROS multiplier |
| `--BFactor F` | 1.0 | Back fire ROS multiplier |
| `--EFactor F` | 1.0 | Ellipse eccentricity factor |
| `--CBDFactor F` | 0.0 | Crown Bulk Density factor (S&B crown fire) |
| `--CCFFactor F` | 0.0 | Crown Closure Fraction factor |
| `--ROS10Factor F` | 3.34 | ROS10 adjustment factor |

### Output Flags

| Flag | Description |
|------|-------------|
| `--output-messages` | Write fire spread messages (cell-to-cell propagation) |
| `--grids` | Write grid state at each period |
| `--final-grid` | Write final burned/unburned grid |
| `--out-ros` | Write rate of spread per cell |
| `--out-fl` | Write flame length per cell |
| `--out-intensity` | Write fire intensity per cell |
| `--out-crown` | Write crown fire state per cell |
| `--out-cfb` | Write crown fraction burned |
| `--out-sfb` | Write surface fraction burned |
| `--ignitionsLog` | Log ignition points used |
| `--verbose` | Enable verbose output |

---

## Output Folder Structure

```
output_folder/
├── Grids/Grids{sim}/                # Per-period grid snapshots (if --grids)
│   ├── ForestGrid00.csv             # Grid state at period 0
│   ├── ForestGrid01.csv             # Grid state at period 1
│   └── ...
├── Grids/Grids{sim}/FinalGrid.csv   # Final burned state (if --final-grid)
├── Messages/MessagesFile{sim}.csv   # Fire spread messages (if --output-messages)
├── RateOfSpread/ROSFile{sim}.csv    # Rate of spread (if --out-ros)
├── Intensity/IntensityFile{sim}.csv # Fire intensity (if --out-intensity)
├── FlameLength/FLFile{sim}.csv      # Flame length (if --out-fl)
├── CrownFire/CrownFile{sim}.csv     # Crown fire state (if --out-crown)
├── CrownFractionBurn/CFBFile{sim}.csv
├── SurfaceFractionBurn/SFBFile{sim}.csv
├── IgnitionsHistory/                # Ignition log (if --ignitionsLog)
└── ignition_and_weather_log.csv     # Simulation-level ignition/weather record
```

### Messages CSV Format

```csv
i,j,time
sender_cell,receiver_cell,fire_period
```

This records which cell ignited which neighbor at what time step.

### Grid CSV Format

Comma-separated grid values:
- 0 = Available (not burned)
- 1 = Burning/Burned

---

## Fuel Model Reference

### Scott & Burgan Fuel Codes (--sim S)

| Code Range | Category | Examples |
|-----------|----------|---------|
| 0 | Non-burnable | Water, rock, urban |
| 91-99 | Non-burnable special | NB1-NB9 |
| 101-108 | Grass (GR1-GR8) | Short sparse to tall coarse grass |
| 121-124 | Grass-Shrub (GS1-GS4) | Mixed grass and shrub |
| 141-149 | Shrub (SH1-SH9) | Low to tall dense shrub |
| 161-165 | Timber-Understory (TU1-TU5) | Forest with understory fuel |
| 181-189 | Timber Litter (TL1-TL9) | Conifer/hardwood litter |
| 201-204 | Slash-Blowdown (SB1-SB4) | Logging residue |

### Canadian FBP Fuel Types (--sim C)

| Code | Type | Description |
|------|------|-------------|
| 1 | C-1 | Spruce-Lichen Woodland |
| 2 | C-2 | Boreal Spruce |
| 3 | C-3 | Mature Jack/Lodgepole Pine |
| 4 | C-4 | Immature Jack/Lodgepole Pine |
| 5 | C-5 | Red and White Pine |
| 6 | C-6 | Conifer Plantation |
| 7 | C-7 | Ponderosa Pine / Douglas-Fir |
| 11 | D-1 | Leafless Aspen |
| 12 | D-2 | Green Aspen |
| 13 | M-1 | Boreal Mixedwood (leafless) |
| 14 | M-2 | Boreal Mixedwood (green) |
| 16 | O-1a | Matted Grass |
| 17 | O-1b | Standing Grass |
| 18 | S-1 | Jack/Lodgepole Pine Slash |
| 19 | S-2 | White Spruce / Balsam Slash |
| 20 | S-3 | Coastal Cedar / Hemlock / Douglas-Fir Slash |

---

## Tool Reference

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| `convert_weather_to_c2f.py` | Convert meteorological data to C2F weather CSV | Met station CSV or gridded data | Weather.csv |
| `convert_fuel_params.py` | Generate fuel lookup table | Fuel type mapping, custom parameters | spain_lookup_table.csv or fbp_lookup_table.csv |
| `run_cell2fire.py` | Execute C2F binary with validation | Instance folder, CLI args | Output folder with results |
| `parse_cell2fire_output.py` | Parse C2F outputs to structured data | Output folder | Burn probability maps, summary CSVs |

---

## Critical Traps and Gotchas

1. **Wind speed units**: Cell2Fire expects km/h. Most global datasets provide m/s. Forgetting `×3.6` causes dramatic under-prediction of fire spread.

2. **Wind direction convention**: Cell2Fire uses meteorological convention (direction wind blows FROM, clockwise from north). Many datasets use mathematical convention (direction TO, counter-clockwise from east). Mixing these sends fire in the wrong direction.

3. **Scenario parameter (S&B)**: The `--scenario` flag (1-3) selects fire weather severity which affects fuel moisture thresholds. Using scenario 3 (extreme) vs 1 (low) can change burned area by 10×.

4. **FMC parameter**: `--fmc` is foliar moisture content in percent. Default is 100% (fully saturated foliage). Lower values dramatically increase crown fire potential.

5. **Empty output folder**: Cell2Fire requires the output folder to exist AND be empty. Leftover files from previous runs cause silent errors.

6. **NODATA alignment**: All rasters must have identical ncols, nrows, cellsize, and corner coordinates. Misaligned rasters cause segfaults or incorrect cell-to-cell adjacency.

7. **Weather file count**: When using `--weather random`, Cell2Fire counts Weather*.csv files in the Weathers/ subdirectory. Files must be named Weather1.csv, Weather2.csv, etc.

8. **Fire-Period-Length ≤ Weather-Period-Length**: If Fire-Period-Length > Weather-Period-Length, it is silently clamped to Weather-Period-Length.

9. **Non-burnable fuels**: Fuel code 0 and codes 91-99 are non-burnable. Fire cannot cross these cells. Using wrong NODATA values in the fuel raster creates artificial firebreaks.

10. **Ignition cell numbering**: Cell IDs in Ignitions.csv are 1-based, counting row-major from top-left. Cell 1 is row 0, col 0.
