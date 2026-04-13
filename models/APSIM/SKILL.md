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

# APSIM Next Generation — Knowledge Infrastructure Skill Document

## 1. Quick Overview

APSIM (Agricultural Production Systems sIMulator) is a process-based crop and farming
systems simulator developed by the APSIM Initiative (Australia). It models crop growth,
soil water balance, nitrogen cycling, and management operations at field/point scale
with a daily timestep. APSIM Next Generation (ApsimX) is the C#/.NET 8.0 rewrite of
the classic Fortran APSIM, using JSON-based simulation files (.apsimx) and SQLite
output databases.

| Attribute          | Value                                          |
|--------------------|------------------------------------------------|
| **Language**       | C# (.NET 8.0)                                  |
| **Build system**   | dotnet (MSBuild, ApsimX.sln)                   |
| **Input format**   | JSON (.apsimx) + custom text weather (.met)     |
| **Output format**  | SQLite (.db), optional CSV export               |
| **Timestep**       | Daily                                           |
| **Spatial scale**  | Point / field (Zone-based, area in ha)          |
| **Key crops**      | Wheat, Maize, Canola, Sorghum, Barley, Soybean, Peanut, Sugarcane, Rice, Oats, Chickpea, Mungbean, and 30+ others |
| **Repository**     | https://github.com/APSIMInitiative/ApsimX       |
| **License**        | MIT-like (see LICENSE.md)                       |
| **CLI binary**     | `apsim` (assembly name from APSIM.Cli)          |

## 2. Installation

### 2.1 From Source (Linux)

```bash
# Prerequisites: .NET 8.0 SDK, libsqlite3-dev
sudo apt-get install -y dotnet-sdk-8.0 libsqlite3-dev

# Clone and build
git clone https://github.com/APSIMInitiative/ApsimX.git
cd ApsimX
dotnet build -c Release -f net8.0

# The CLI binary is at:
#   APSIM.Cli/bin/Release/net8.0/apsim
```

### 2.2 Docker

```bash
docker build -f Dockerfiles/release-dockerfile -t apsim .
docker run --rm -v $(pwd)/data:/data apsim run /data/simulation.apsimx
```

### 2.3 Pre-built Installers

Download from https://www.apsim.info/download-apsim/ for Windows/macOS/Linux.

## 3. Pipeline Stages

The APSIM modelling pipeline has seven stages:

| Stage | Name                | Description                                              | Tool                    |
|-------|---------------------|----------------------------------------------------------|-------------------------|
| S0    | Configuration       | Define crop type, site, simulation period, management    | —                       |
| S1    | Domain Setup        | Select soil profile, crop cultivar, zone properties      | `convert_soil.py`       |
| S2    | Data Preparation    | Convert weather forcing to .met format                   | `convert_met.py`        |
| S3    | Simulation Assembly | Build .apsimx JSON file from components                  | `build_apsimx.py`       |
| S4    | Execution           | Run APSIM via CLI                                        | `run_apsim.py`          |
| S5    | Output Parsing      | Extract results from SQLite .db to CSV                   | `parse_output.py`       |
| S6    | Validation          | Compare simulated vs observed, compute metrics           | (manual / scripts)      |

## 4. Critical Domain Knowledge

### 4.1 Weather (.met) File Format — UNIT TRAPS

The .met file is a custom APSIM text format. **Critical units:**

| Column   | Required | Units          | Common Source Units    | Conversion                  |
|----------|----------|----------------|------------------------|-----------------------------|
| `year`   | YES      | integer year   | —                      | —                           |
| `day`    | YES      | day-of-year    | date string            | Convert date → DOY (1-366)  |
| `radn`   | YES      | MJ/m^2         | W/m² (CMFD/ERA5)       | W/m² × 0.0864 = MJ/m²/day  |
| `maxt`   | YES      | °C             | K (ERA5/CMFD)          | K − 273.15 = °C             |
| `mint`   | YES      | °C             | K                      | K − 273.15 = °C             |
| `rain`   | YES      | mm/day         | mm/3hr (CMFD)          | Sum 8 intervals per day     |
| `pan`    | optional | mm/day         | —                      | —                           |
| `vp`     | optional | hPa            | kPa (ERA5)             | kPa × 10 = hPa             |
| `wind`   | optional | m/s            | —                      | —                           |
| `co2`    | optional | ppm            | —                      | —                           |

**CRITICAL: Radiation must be MJ/m²/day, NOT W/m².** Supplying W/m² (typically 100-400)
instead of MJ/m² (typically 5-30) will cause massively inflated biomass production.
This is the #1 unit trap. See diagnostic triplet dt_001.

**CRITICAL: The header line must use parenthesized units exactly as APSIM expects:**
```
year  day radn  maxt   mint  rain  pan    vp      code
 ()   () (MJ/m^2) (oC) (oC)  (mm)  (mm)   (hPa)     ()
```

**CRITICAL: `tav` and `amp` in the header are REQUIRED metadata.**
- `tav` = annual average ambient temperature (°C)
- `amp` = annual amplitude in mean monthly temperature (°C)
- These drive the soil temperature model. If missing, APSIM crashes silently or
  produces unrealistic soil temperatures. See dt_002.

### 4.2 Soil Parameters — Layer-Based Arrays

APSIM soils are specified as arrays indexed by layer. All layers must have the
same number of elements (same number of layers).

| Parameter        | Units   | Description                     | Typical Range        |
|------------------|---------|---------------------------------|----------------------|
| `Thickness`      | mm      | Layer depth                     | 100–300              |
| `BD`             | g/cc    | Bulk density                    | 1.0–1.8              |
| `AirDry`         | mm/mm   | Air-dry water content           | 0.01–0.15            |
| `LL15`           | mm/mm   | Lower limit (wilting point)     | 0.05–0.25            |
| `DUL`            | mm/mm   | Drained upper limit (field cap) | 0.15–0.45            |
| `SAT`            | mm/mm   | Saturation                      | 0.30–0.55            |
| `KS`             | mm/day  | Saturated hydraulic conductivity| 1–500                |

**CRITICAL ordering: AirDry ≤ LL15 ≤ DUL ≤ SAT.** Violation crashes the water
balance model. See dt_003.

**Crop-specific parameters (SoilCrop):**

| Parameter | Units        | Description                        | Typical Range |
|-----------|--------------|------------------------------------|---------------|
| `LL`      | mm/mm        | Crop lower limit (extraction limit)| ≥ LL15        |
| `KL`      | /day         | Root water uptake rate             | 0.01–0.10     |
| `XF`      | dimensionless| Root exploration factor            | 0.0–1.0       |

**Water balance parameters (SoilWater / WaterBalance):**

| Parameter     | Units | Description                              |
|---------------|-------|------------------------------------------|
| `SummerU`     | mm    | Stage 1 evaporation limit (summer)       |
| `SummerCona`  | mm/d^0.5 | Stage 2 evaporation coefficient (summer) |
| `WinterU`     | mm    | Stage 1 evaporation limit (winter)       |
| `WinterCona`  | mm/d^0.5 | Stage 2 evaporation coefficient (winter) |
| `Salb`        | 0-1   | Bare soil albedo                         |
| `CN2Bare`     | —     | SCS curve number (bare soil)             |
| `SWCON`       | 0-1   | Soil water conductivity (per layer)      |
| `DiffusConst` | —     | Diffusivity constant                     |
| `DiffusSlope` | —     | Diffusivity slope                        |

### 4.3 Simulation JSON Structure (.apsimx)

The .apsimx file is a nested JSON tree. Each node has `$type`, `Name`, and `Children`:

```
Simulations
├── DataStore                    ($type: Models.Storage.DataStore)
└── Simulation                   ($type: Models.Core.Simulation)
    ├── Clock                    (Start, End dates)
    ├── Summary                  (logging)
    ├── Weather                  (FileName → .met path)
    ├── MicroClimate             (light interception)
    └── Zone                     (Area in ha)
        ├── Soil                 (Physical, Chemical, Organic, WaterBalance, SoilCrop)
        ├── Plant / Crop         (cultivar, phenology, organs)
        ├── Manager              (sowing rules, fertilizer, irrigation)
        └── Report               (VariableNames[], EventNames[])
```

**CRITICAL: `%root%` in file paths is replaced with the directory containing the
.apsimx file at runtime.** Relative paths resolve from this root. See dt_004.

### 4.4 Crop Sowing Parameters

Sowing is triggered by a Manager script calling `[Crop].Sow(...)`:

| Parameter       | Units   | Description                          |
|-----------------|---------|--------------------------------------|
| `Population`    | /m²     | Plant population density             |
| `Depth`         | mm      | Sowing depth                         |
| `Cultivar`      | string  | Cultivar name (must match available) |
| `RowSpacing`    | mm      | Row spacing                          |
| `MaxCover`      | 0-1     | Maximum canopy cover                 |
| `BudNumber`     | integer | Number of buds (tuber crops)         |

**CRITICAL: Population is plants per m², NOT per hectare.** 100 plants/m² = 1,000,000
plants/ha. Supplying 100,000 (intended as plants/ha) as plants/m² gives 10^9 plants/ha.
See dt_005.

### 4.5 Key Output Variables

Variables are addressed by model path in Report definitions:

| Variable Path                      | Units  | Description                     |
|------------------------------------|--------|---------------------------------|
| `[Clock].Today`                    | date   | Simulation date                 |
| `[Wheat].Grain.Wt`                | g/m²   | Grain dry weight                |
| `[Wheat].AboveGround.Wt`          | g/m²   | Above-ground biomass            |
| `[Wheat].Leaf.LAI`                | m²/m²  | Leaf area index                 |
| `[Wheat].Phenology.Stage`         | code   | Phenological stage number       |
| `[Wheat].Phenology.CurrentPhaseName`| string | Phase name                    |
| `[Wheat].Root.RootingDepth`       | mm     | Rooting depth                   |
| `[Soil].Water.SW`                 | mm/mm  | Volumetric soil water (array)   |
| `[Soil].Water.ESW`                | mm     | Extractable soil water (array)  |
| `[Soil].SoilWater.Runoff`         | mm     | Surface runoff                  |
| `[Soil].SoilWater.Drainage`       | mm     | Deep drainage                   |
| `[Soil].SoilWater.Es`             | mm     | Soil evaporation                |
| `[Weather].Rain`                  | mm     | Daily rainfall                  |
| `[Weather].MaxT`                  | °C     | Maximum temperature             |
| `[Weather].MinT`                  | °C     | Minimum temperature             |
| `[Weather].Radn`                  | MJ/m²  | Solar radiation                 |

**CRITICAL: Biomass outputs (Wt) are in g/m², NOT kg/ha.** To convert:
kg/ha = g/m² × 10. Grain yield of 300 g/m² = 3000 kg/ha = 3.0 t/ha. See dt_006.

### 4.6 Fertiliser Application

Fertiliser is applied via Manager script or Operations list:

| Parameter | Units  | Description                              |
|-----------|--------|------------------------------------------|
| `Amount`  | kg/ha  | Application amount                       |
| `Depth`   | mm     | Application depth in soil                |
| `Type`    | enum   | NO3N, NH4N, UreaN, etc.                  |

### 4.7 Irrigation

| Parameter | Units | Description                                |
|-----------|-------|--------------------------------------------|
| `Amount`  | mm    | Irrigation depth                           |
| `Depth`   | mm    | Depth of application in soil               |
| `Duration`| min   | Duration of irrigation event               |
| `Efficiency`| 0-1 | Irrigation efficiency                      |

### 4.8 Phenology and Thermal Time

APSIM crops use thermal time (degree-days) to drive phenological development:

```
ThermalTime = max(0, (Tmax + Tmin)/2 - Tbase)
```

Where Tbase varies by crop (e.g., Wheat ~0°C, Maize ~8°C, Sorghum ~11°C).

Key phenological stages (wheat example):
1. Sowing → Germination
2. Germination → Emergence
3. Emergence → Terminal Spikelet
4. Terminal Spikelet → Flowering
5. Flowering → Start Grain Fill
6. Start Grain Fill → End Grain Fill
7. End Grain Fill → Maturity
8. Maturity → Harvest Ripe

### 4.9 Canopy Cover Calculation

```
CoverGreen = 1 - exp(-ExtinctionCoeff × LAI / MaxCover)
CoverTotal = 1 - (1 - CoverGreen) × (1 - CoverDead)
```

## 5. Unit Trap Table

This table documents the most dangerous unit mismatches when preparing APSIM inputs
from global datasets (ERA5, CMFD, MSWX, SoilGrids, HWSD):

| ID  | Variable    | APSIM Unit   | Common Source | Source Unit     | Conversion Factor              | Severity |
|-----|-------------|--------------|---------------|-----------------|-------------------------------|----------|
| U01 | Radiation   | MJ/m²/day   | ERA5/CMFD     | W/m² (instant)  | × 0.0864 (÷ 11.574)          | FATAL    |
| U02 | Temperature | °C           | ERA5          | K               | − 273.15                      | FATAL    |
| U03 | Vapor press | hPa          | ERA5          | kPa             | × 10                          | degraded |
| U04 | Rainfall    | mm/day       | CMFD          | mm/3hr          | Sum 8 intervals               | FATAL    |
| U05 | Biomass out | g/m²         | Literature    | kg/ha           | ÷ 10 (APSIM→lit) or × 10     | silent   |
| U06 | Population  | plants/m²    | Agronomic     | plants/ha       | ÷ 10000                       | FATAL    |
| U07 | Soil water  | mm/mm (vol)  | SoilGrids     | % (v/v)         | ÷ 100                         | FATAL    |
| U08 | Thickness   | mm           | HWSD          | cm              | × 10                          | FATAL    |
| U09 | Bulk density| g/cc         | SoilGrids     | kg/m³           | ÷ 1000                        | FATAL    |
| U10 | KS          | mm/day       | Literature    | cm/hr           | × 240                         | degraded |
| U11 | Row spacing | mm           | Agronomic     | cm              | × 10                          | degraded |
| U12 | Sowing depth| mm           | Agronomic     | cm              | × 10                          | degraded |
| U13 | Root depth  | mm           | Literature    | cm or m         | × 10 or × 1000               | silent   |
| U14 | CO2         | ppm          | —             | µmol/mol        | 1:1 (same)                    | none     |
| U15 | Wind speed  | m/s          | ERA5          | m/s             | 1:1 (check u/v components)    | degraded |

## 6. Tool Reference

| Tool                  | Stage | Purpose                                        |
|-----------------------|-------|------------------------------------------------|
| `convert_met.py`      | S2    | Convert global forcing (NetCDF) → APSIM .met   |
| `convert_soil.py`     | S1    | Convert HWSD/SoilGrids → APSIM soil JSON       |
| `build_apsimx.py`     | S3    | Assemble .apsimx simulation file from parts     |
| `run_apsim.py`        | S4    | Execute APSIM CLI with preflight checks         |
| `parse_output.py`     | S5    | Extract SQLite .db results → CSV                |

All tools follow the validate→process→validate pattern:
1. `validate_inputs()` — check files exist, units correct, ranges valid
2. `process()` — core transformation logic
3. `validate_outputs()` — verify output quality and physical constraints

## 7. Execution

### 7.1 Basic Run

```bash
# Run a single simulation
apsim run Wheat.apsimx

# Run with CSV export
apsim run Wheat.apsimx --csv

# Run specific simulations by name regex
apsim run Wheat.apsimx --simulation-names "Dalby.*"

# Run single-threaded (useful for debugging)
apsim run Wheat.apsimx --single-threaded

# Verbose output
apsim run Wheat.apsimx --verbose
```

### 7.2 Edit Before Run

```bash
# Override parameters via config file
apsim run Wheat.apsimx --edit config.txt
```

Config file format (one override per line):
```
[Simulation].Clock.Start = 2000-01-01
[Simulation].Clock.End = 2005-12-31
[Simulation].Zone.Weather.FileName = /data/weather/site.met
```

### 7.3 Output Access

After running, output is in `{filename}.db` (SQLite):
```bash
sqlite3 Wheat.db "SELECT * FROM Report LIMIT 10;"
```

Or use `--csv` flag to auto-export to `{filename}.Report.csv`.

## 8. Validation Metrics for Crop Models

| Metric | Formula / Description                           | Good Value        |
|--------|------------------------------------------------|-------------------|
| RMSE   | √(mean((sim-obs)²))                           | < 15% of obs mean |
| nRMSE  | RMSE / mean(obs) × 100                         | < 15%             |
| R²     | Coefficient of determination                    | > 0.80            |
| PBIAS  | 100 × Σ(sim-obs) / Σ(obs)                      | |PBIAS| < 15%     |
| d      | Willmott index of agreement                    | > 0.85            |
| EF     | Nash-Sutcliffe model efficiency (=NSE)         | > 0.50            |

Common validation targets:
- **Grain yield** (t/ha): Primary metric for crop models
- **Biomass** (t/ha): Total above-ground dry matter
- **Phenology** (days): Flowering date, maturity date
- **LAI** (m²/m²): Peak LAI timing and magnitude
- **Soil water** (mm): Profile soil water content over time

## 9. File Structure

```
project/
├── simulation.apsimx          # Main simulation file (JSON)
├── weather/
│   └── site.met               # Weather forcing data
├── simulation.db              # Output database (SQLite, auto-created)
├── simulation.db-wal          # Write-ahead log (temp, auto-managed)
├── simulation.db-shm          # Shared memory (temp, auto-managed)
└── simulation.Report.csv      # CSV export (if --csv flag used)
```

## 10. Diagnostic Triplets Summary

The most dangerous silent errors in APSIM modelling:

1. **dt_001 — Radiation in W/m² instead of MJ/m²/day**: Biomass explodes to
   unrealistic values. Tool `convert_met.py` auto-converts and validates range.

2. **dt_002 — Missing tav/amp in .met header**: Soil temperature model fails
   silently, producing unrealistic soil temperatures that affect germination
   and root growth.

3. **dt_003 — Soil water limits not ordered (AirDry ≤ LL15 ≤ DUL ≤ SAT)**:
   Water balance crashes or produces negative water content.

4. **dt_005 — Plant population in wrong units**: Supplying plants/ha as
   plants/m² gives 10,000× too many plants.

5. **dt_006 — Biomass output confusion (g/m² vs kg/ha)**: Factor of 10
   error in reported yield.

6. **dt_010 — Wrong cultivar name**: Simulation crashes with unhelpful error.
   Must match exactly from available cultivar list.

7. **dt_013 — .met file path not resolved**: %root% macro not properly
   expanded, or relative path broken by directory change.
