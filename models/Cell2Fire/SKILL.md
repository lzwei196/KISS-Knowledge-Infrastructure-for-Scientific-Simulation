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
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (16 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 8 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_fuel_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_fuel_params.py --help` |
| `tools/convert_weather_to_c2f.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_weather_to_c2f.py --help` |
| `tools/parse_cell2fire_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_cell2fire_output.py --help` |
| `tools/run_cell2fire.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_cell2fire.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# Cell2Fire W (C2F-W) — Knowledge Infrastructure

**Package**: `hydrocraft-cell2fire-wildfire` v1.0.0
**Model**: Cell2Fire W (C2F-W) — unified Scott&Burgan, FBP-Canada, Kitral fire spread simulator
**Source**: https://github.com/fire2a/C2F-W
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 15+ diagnostic triplets | ~2,000 lines of validated Python
**Validation status**: `build_validated` (Vilopriu 2013, Scott&Burgan model)

---

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | Cell2Fire W (C2F-W) |
| Package | `hydrocraft-cell2fire-wildfire` v1.0.0 |
| Language | C++ with OpenMP, wrapped by KI Python tools |
| Repository | https://github.com/fire2a/C2F-W |
| Primary domain | Wildfire spread / hazard |
| Spatial mode | Distributed gridded landscape |
| Validation status | `build_validated` (Vilopriu 2013, Scott&Burgan model) |

---

## 2. What This Model Does

Cell2Fire W is a large-scale, grid-based wildfire spread simulator. It propagates fire between
regular grid cells using elliptical spread and a selected fire-behavior model: Scott & Burgan,
Canadian FBP, Kitral, or Portugal. It can run deterministic fire scars or Monte Carlo ensembles
for burn probability, and it can emit per-cell fire behavior fields such as ROS, intensity,
flame length, and crown-fire state.

The headline variable for validation is the dag rank-1 output: `FinalGrid (burned/unburned)`.

---

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`** (projected from dag + triplets; regenerate it
after changing either file, never hand-edit it). This section explains intent and common traps.

### 3.1 Meteorological Forcing

| Variable | Unit model expects | Source dataset | Source unit | Conversion |
|----------|-------------------|----------------|-------------|------------|
| Wind speed (WS) | km/h | CMFD/MSWX/NASA POWER or station forcing | often m/s | x3.6 |
| Wind direction (WD) | degrees, meteorological FROM, north=0 | CMFD/MSWX/NASA POWER or station forcing | varies | if math TO convention: `(value + 180) % 360` |
| Air temperature (TMP) | deg C | FBP weather forcing | often K or deg C | K to deg C: -273.15 |
| Relative humidity (RH) | percent (0-100) | FBP weather forcing | often fraction or percent | fraction to percent: x100 |
| Precipitation (APCP) | mm | FBP weather forcing | often m, mm/step, or kg/m2/s | source-specific; verify attributes |
| FWI System indices | dimensionless | externally computed CFFDRS/FWI pipeline | dimensionless | none; must be supplied for `--sim C` |

### 3.2 Static Inputs

| Input | Unit model expects | Tool that prepares it |
|-------|--------------------|----------------------|
| Fuel type grid | integer fuel code | `convert_landscape_to_c2f` |
| Elevation grid | meters ASL | `convert_landscape_to_c2f` |
| Slope grid | degrees | `convert_landscape_to_c2f` |
| Slope aspect (`saz`) | degrees, compass north=0 | `convert_landscape_to_c2f` |
| Crown base height (`cbh`) | meters | `convert_landscape_to_c2f` |
| Crown bulk density (`cbd`) | kg/m3 | `convert_landscape_to_c2f` |
| Crown closure / canopy cover (`ccf`, `fcc`) | percent | `convert_landscape_to_c2f` |
| Grass curing (`cur`) | percent | `convert_landscape_to_c2f` |

### 3.3 Configuration Files

| File | Format | Notes |
|------|--------|-------|
| `Weather.csv` | CSV | Hourly weather rows; S&B/Kitral and FBP use different column sets. |
| `Ignitions.csv` | CSV | Optional fixed ignition cells; cell ids are 1-based row-major from top-left. |
| `spain_lookup_table.csv` | CSV | Fuel coefficients lookup for Scott & Burgan / Kitral / Portugal style runs. |
| `fbp_lookup_table.csv` | CSV | Fuel coefficients lookup for Canadian FBP runs. |
| `probabilityMap.asc` | ESRI ASCII grid | Optional ignition probability per cell. |

---

## 4. Build Instructions

Run the KI preflight first:

```bash
python preflight_check.py
```

Then compile the model binary when the local Cell2Fire source needs rebuilding:

```bash
cd Cell2Fire/
make
sudo make install  # optional
```

Known build issues are captured in `diagnostics/triplets.yaml`; check it before debugging a
failed import, compile, or execution.

---

## 5. Execution

Minimal execution pattern:

```bash
mkdir results
./Cell2Fire --input-instance-folder ../data/ScottAndBurgan/Hom_Fuel_101_40x40-asc \
  --output-folder results --nsims 3 --sim S --output-messages --final-grid --seed 123
```

The KI execution wrapper is `run_cell2fire`; read the tool argparse (`--help`) before composing
a run.

---

## 6. Output Description

**SOURCE: `dag.yaml`.** The dag is the model identity for outputs. If this section and
`dag.yaml` ever disagree, `dag.yaml` wins.

**Headline output** (dag `validation_rank: 1`):

> `FinalGrid (burned/unburned)` — Final per-cell burn state grid (fire scar) for one simulation. (`0=unburned, 1=burned`)

| Output variable (dag `var`) | rank | File | Unit |
|-----------------------------|------|------|------|
| `FinalGrid (burned/unburned)` | 1 | `Grids/Grids{sim}/FinalGrid.csv` | `0=unburned, 1=burned` |
| `burn probability` | 2 | `burn_probability.csv / .asc` (post-processing of FinalGrid ensemble) | `0.0-1.0` |
| `fire propagation messages` | 3 | `Messages/MessagesFile{sim}.csv` | `(sender_cell, receiver_cell, fire_period, ROS)` |
| `rate of spread (ROS)` | 4 | `RateOfSpread/ROSFile{sim}.csv` | `m/min` |
| `fireline intensity` | 5 | `Intensity/IntensityFile{sim}.csv` | `kW/m (Byram intensity)` |
| `flame length` | 6 | `FlameLength/FLFile{sim}.csv` | `m` |
| `crown fire state / crown fraction burned` | 7 | `CrownFire/CrownFile{sim}.csv ; CrownFractionBurn/CFBFile{sim}.csv` | `0/1 ; fraction` |

The dag's rank-1 variable is what this model is judged by when a single headline output is
required. Other dag outputs are `burn probability`, `fire propagation messages`,
`rate of spread (ROS)`, `fireline intensity`, `flame length`, and
`crown fire state / crown fraction burned`.

---

## 7. Tool Inventory

| Tool | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `convert_landscape_to_c2f` | Prepare Cell2Fire landscape rasters | Fuel, elevation, slope, aspect rasters | ASC/TIF instance-folder rasters |
| `convert_weather_to_c2f` | Convert meteorological forcing | Station or gridded forcing | `Weather.csv` |
| `convert_fuel_params` | Generate fuel lookup table | Fuel type mapping / parameters | `spain_lookup_table.csv` or `fbp_lookup_table.csv` |
| `run_cell2fire` | Execute the real Cell2Fire binary | Instance folder and CLI args | Cell2Fire output folder |
| `parse_cell2fire_output` | Parse and aggregate model outputs | Cell2Fire output folder | Burn probability maps and summary CSVs |

Use shared KI utilities where applicable, especially
`from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

---

## 8. Unit Conversion Table

> **Critical**: This table documents unit conversions that must be verified before running.
> `docs/format_spec.yaml` is the exact I/O contract.
> This is the KI unit table for inputs and output-unit conventions.

| Variable | Source unit (verified) | Model unit | Factor / conversion | Type |
|----------|------------------------|------------|---------------------|------|
| Wind Speed (WS) | m/s | km/h | x3.6 | multiplicative |
| Wind Direction (WD) | degrees, mathematical TO | degrees, meteorological FROM | `(value + 180) % 360` | convention |
| Elevation | feet | meters ASL | x0.3048 | multiplicative |
| Slope | percent rise | degrees | `atan(pct/100) x 180/pi` | nonlinear |
| Slope Aspect (`saz`) | degrees, mathematical east=0 | degrees, compass north=0 | `(90 - value) % 360` | convention |
| Temperature (TMP) | K | deg C | -273.15 | additive |
| Relative Humidity (RH) | fraction (0-1) | percent (0-100) | x100 | multiplicative |
| Precipitation (APCP) | m | mm | x1000 | multiplicative |
| Crown Base Height (`cbh`) | feet | meters | x0.3048 | multiplicative |
| Crown Bulk Density (`cbd`) | lb/ft3 | kg/m3 | x16.0185 | multiplicative |
| Fuel Moisture Content (FMC) | fraction (0-1) | percent | x100 | multiplicative |
| Fire Period Length | hours | minutes | x60 | multiplicative |

### 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| FinalGrid (burned/unburned) | `0=unburned, 1=burned` | Boolean or inverse mask | CSI/F1 fire-scar scores invert or collapse |
| Burn probability | `0.0-1.0` probability per cell | Percent 0-100 | Probability metrics are off by 100x |
| Wind direction | Meteorological FROM, north=0 | Mathematical TO, east=0 | Fire spread direction rotates or reverses |
| Rate of spread (ROS) | `m/min` | `m/s`, `m/h`, `km/h` | Arrival time and propagation threshold are wrong |
| Fireline intensity | `kW/m` | `W/m`, `MW/m` | Fire-behavior magnitude comparisons are wrong |
| Flame length | `m` | feet | Crown/surface fire interpretation is wrong |

---

## 9. Diagnostic Triplets (Top 5)

The full corpus is in `diagnostics/triplets.yaml`; check it first on any error.

| # | Error / symptom | Diagnosis | Remedy |
|---|-----------------|-----------|--------|
| 1 | `dt_001`: fire barely spreads; burned area tiny; ROS near zero | Wind speed in m/s instead of km/h | Multiply wind speed by 3.6 in `convert_weather_to_c2f.py` |
| 2 | `dt_002`: fire spreads in wrong direction | Wind direction in math convention instead of meteorological FROM | Apply `(WD + 180) % 360` |
| 3 | `dt_003`: FBP produces extreme fire behavior in mild weather | Relative humidity fraction instead of percent | Multiply RH by 100 if values are in 0-1 range |
| 4 | `dt_004`: FBP temperature calculations nonsensical | Temperature in Kelvin instead of Celsius | Subtract 273.15 from temperature values |
| 5 | `dt_007`: segmentation fault at simulation start | Raster dimension mismatch | Ensure all ASC files have identical dimensions, cellsize, and corner coordinates |

---

## 10. Coupling Interfaces

| Upstream source/model | Variable exchanged | Unit | Temporal resolution |
|-----------------------|-------------------|------|---------------------|
| CMFD/MSWX/NASA POWER or station forcing | Weather drivers (`WS`, `WD`, and FBP columns as needed) | mixed; see Section 8 | hourly model rows |
| DEM / landscape processing | Elevation, slope, aspect | meters, degrees | static grid |
| Fuel map / fuel lookup processing | Fuel type and fuel coefficients | integer code / mixed table | static grid |
| Fire perimeter observations such as MTBS | Observed final burn scar for validation | burned/unburned raster | event final perimeter |

| Downstream consumer | Variable exchanged | Unit | Temporal resolution |
|---------------------|-------------------|------|---------------------|
| Burn-scar validation workflow | `FinalGrid (burned/unburned)` | `0=unburned, 1=burned` | event final state |
| Risk mapping / planning workflow | `burn probability` | `0.0-1.0` | ensemble summary |
| Arrival-time / spread diagnostics | `fire propagation messages` | `(sender_cell, receiver_cell, fire_period, ROS)` | fire period |

---

## 11. Validated Results

Validated run bodies are pending in this KI. Until a run-specific body campaign is added,
judge candidate runs against the cited field bars in `docs/validation_convention.yaml`; do not
invent thresholds.

### Performance Metrics - judged against the field's bar, not intuition

| Dag variable | Metric | Direction | Satisfactory | Good | Very good | Citation |
|--------------|--------|-----------|--------------|------|-----------|----------|
| `FinalGrid (burned/unburned)` | `csi` | maximize | >= 0.25 | >= 0.4286 | >= 0.6667 | `giannaros2020` |
| `burn probability` | `top_quintile_burn_capture_percent` | maximize | >= 56.7 | >= 68.0 | >= 80.0 | `moran2025` |
| `burn probability` | `logarithmic_skill_score` | maximize | >= 0.0 | no cited threshold | no cited threshold | `moran2025` |
| `fire propagation messages` | `csi` | maximize | >= 0.25 | >= 0.4286 | >= 0.6667 | `giannaros2020` |

Bar for `FinalGrid (burned/unburned)` (`csi`, per `giannaros2020`): satisfactory >= 0.25,
good >= 0.4286, very good >= 0.6667. Achieved: pending body campaign -> no run verdict.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Weather forcing | KI pipeline / source forcing | Pending run-specific validation | Use `preflight_check.py` and `docs/format_spec.yaml`. |
| Landscape rasters | KI pipeline / GIS sources | Pending run-specific validation | All rasters must align exactly. |
| Fuel lookup tables | KI pipeline / model fuel scheme | Pending run-specific validation | Match lookup table to `--sim`. |
| Ignitions | User-provided or random / probability map | Pending run-specific validation | Fixed cells use 1-based row-major ids. |
| Observed fire scar | MTBS or equivalent perimeter source | Pending run-specific validation | Bind to `FinalGrid (burned/unburned)` for headline CSI. |

---

## 12. Parameter Selection by Region

These are not calibration results. Use model defaults as physically informed starting points
when no site-specific calibration exists, then document any ROS or ellipse tuning in the run
body.

| Climate / Region | Key parameters | Rationale |
|---|---|---|
| Mediterranean / Scott & Burgan | `--sim S`, `--scenario` selected from fire-weather severity, `HFactor/FFactor/BFactor/EFactor=1.0` before tuning | Matches the S&B fuel-model path and keeps ROS/ellipse multipliers neutral before calibration. |
| Canada / boreal FBP | `--sim C`, externally supplied `FFMC/DMC/DC/ISI/BUI/FWI`, FBP fuel codes | The FBP model requires Canadian FWI System indices and FBP-compatible fuel codes. |
| Chile / Kitral | `--sim K`, Kitral-compatible fuels and weather rows | Uses the Kitral fire-behavior path for South American vegetation. |
| Portugal / experimental | `--sim P` only when explicitly intended | The Portugal model is marked experimental in the KI. |

---

## Legacy Detailed Reference

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

## Output Description

Cell2Fire produces per-simulation CSV files in the output folder, organized by variable type (Grids, Messages, RateOfSpread, Intensity, FlameLength, CrownFire). The main outputs are burn-state grids (0=unburned, 1=burned), fire spread message logs (sender cell, receiver cell, time step), and optional per-cell rate-of-spread, fire intensity (kW/m), and flame length (m) grids. All outputs are plain CSV; burn probability maps are derived by averaging final grids across Monte Carlo simulations. Use `parse_cell2fire_output.py` to aggregate results into structured summary CSVs. See the detailed structure below.

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
