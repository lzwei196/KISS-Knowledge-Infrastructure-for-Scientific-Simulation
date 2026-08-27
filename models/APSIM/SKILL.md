> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (5 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (8 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (20 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (18 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |
| what past runs learned | `.kdt_evolution.jsonl` | append-only memory of previous runs and fixes on this KI. |

*Projected 2026-08-17 from the KI's actual contents — 10 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_apsimx.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_apsimx.py --help` |
| `tools/convert_met.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_met.py --help` |
| `tools/convert_soil.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil.py --help` |
| `tools/parse_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output.py --help` |
| `tools/run_apsim.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_apsim.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

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

## 6. Output Description

**Source of truth: `dag.yaml`.** The dag defines what this KI predicts. If this
section and `dag.yaml` disagree, `dag.yaml` wins.

**Headline output** (the dag's `validation_rank: 1` variable):

> `Grain.Wt` — Crop grain dry weight (yield) in the plant/crop biomass medium; g/m^2 x10 = kg/ha, /100 = t/ha. (`g/m^2`)

| Output variable (dag `var`) | Rank | Unit | Description / dag status |
|-----------------------------|------|------|--------------------------|
| `Grain.Wt` | 1 | `g/m^2` | Crop grain dry weight (yield) in the plant/crop biomass medium; g/m^2 x10 = kg/ha, /100 = t/ha. |
| `AboveGround.Wt` | dag output | see `dag.yaml` | Listed by the dag as an APSIM output. |
| `Leaf.LAI` | dag output | see `dag.yaml` | Listed by the dag as an APSIM output. |
| `Phenology.Stage / flowering & maturity date` | dag output | see `dag.yaml` | Listed by the dag as an APSIM output. |
| `Root.RootingDepth` | dag output | see `dag.yaml` | Listed by the dag as an APSIM output. |
| `Soil.Water.SW / ESW` | dag output | see `dag.yaml` | Listed by the dag as an APSIM output. |
| `SoilWater.Drainage / Runoff / Es` | dag output | see `dag.yaml` | Listed by the dag as an APSIM output. |

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

## 8. Unit Conversion Table

This unit table restates the KI's pipeline unit conversions and the dag's headline
output conversion. It is the quick-check table; detailed I/O shapes remain in
`docs/format_spec.yaml`, and the headline output identity remains in `dag.yaml`.

| Variable | Source unit / common source | Model or reported unit | Conversion | Type |
|----------|-----------------------------|------------------------|------------|------|
| Radiation (`radn`) | W/m² (ERA5/CMFD instant) | MJ/m²/day | × 0.0864 (÷ 11.574) | multiplicative |
| Temperature (`maxt`, `mint`) | K (ERA5/CMFD) | °C | − 273.15 | additive |
| Vapor pressure (`vp`) | kPa (ERA5) | hPa | × 10 | multiplicative |
| Rainfall (`rain`) | mm/3hr (CMFD) | mm/day | Sum 8 intervals | aggregation |
| `Grain.Wt` | `g/m^2` | kg/ha | x10 | multiplicative |
| `Grain.Wt` | `g/m^2` | t/ha | /100 | multiplicative |
| Population | plants/ha | plants/m² | ÷ 10000 | multiplicative |
| Soil water | % (v/v) | mm/mm | ÷ 100 | multiplicative |
| Thickness | cm | mm | × 10 | multiplicative |
| Bulk density | kg/m³ | g/cc | ÷ 1000 | multiplicative |
| KS | cm/hr | mm/day | × 240 | multiplicative |
| Row spacing | cm | mm | × 10 | multiplicative |
| Sowing depth | cm | mm | × 10 | multiplicative |
| Root depth | cm or m | mm | × 10 or × 1000 | multiplicative |
| CO2 | µmol/mol | ppm | 1:1 (same) | identity |
| Wind speed | m/s | m/s | 1:1 (check u/v components) | identity |

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

| Metric | Formula / Description                           | Grading source    |
|--------|------------------------------------------------|-------------------|
| RMSE   | √(mean((sim-obs)²))                           | no cited threshold in the provided `Grain.Wt` convention |
| nRMSE  | RMSE / mean(obs) × 100                         | use Section 11 / `docs/validation_convention.yaml` |
| R²     | Coefficient of determination                    | no cited threshold in the provided `Grain.Wt` convention |
| PBIAS  | 100 × Σ(sim-obs) / Σ(obs)                      | choose by dag obs-shape rules; no `Grain.Wt` convention bar stated here |
| d      | Willmott index of agreement                    | no cited threshold in the provided `Grain.Wt` convention |
| EF     | Nash-Sutcliffe model efficiency (=NSE)         | use Section 11 / `docs/validation_convention.yaml` |

Common validation targets:
- **Grain yield** (t/ha): Primary metric for crop models
- **Biomass** (t/ha): Total above-ground dry matter
- **Phenology** (days): Flowering date, maturity date
- **LAI** (m²/m²): Peak LAI timing and magnitude
- **Soil water** (mm): Profile soil water content over time

### 8.1 Obs-shape selection - REQUIRED before computing any metric

`dag.yaml` `outputs[Grain.Wt].observability.comparable_obs_shapes` declares THREE
mutually exclusive comparison modes. Pick by the OBSERVATION's spatial support,
not by the simulation's.

| Obs example | obs_shape | comparison_mode | determining_metric | detrending_options |
|---|---|---|---|---|
| One field trial, one season | `point_snapshot` | `scalar_comparison` | `pbias` | `none` |
| One field trial, many seasons | `point_time_series` | `time_series_comparison` | `pbias` | `none` |
| GDHY / SPAM / FAOSTAT / any gridded, district or national yield | `regional_aggregate_time_series` | `aggregate_trend_comparison` | `pbias` | `none`, `linear_residual`, `decadal_mean` |

**A 0.5-degree GDHY cell, a SPAM pixel, a district series and a national FAOSTAT
series are ALL `regional_aggregate_time_series`.** They average thousands of
fields and carry a secular technology/management trend that a
constant-management, weather-driven point simulation cannot and must not
reproduce. If `resolved_obs.granularity == "grid"`, or the obs is a statistical
aggregate of any kind, the obs_shape is `regional_aggregate_time_series` - full
stop. Declaring it `point_time_series` silently selects the wrong metric family.

### 8.2 Mandatory detrending for `regional_aggregate_time_series`

`ki_tools_common.metrics.all_metrics` alone (raw NSE / r / KGE) is **NOT** valid
for this obs shape. Also call `ki_tools_common.metrics.trend_metrics(obs, sim)`
(`metrics.py:492`), which implements the dag `trend_match` family with
`linear_residual` detrending:

python
from ki_tools_common.metrics import all_metrics, trend_metrics
m = all_metrics(obs, sim)           # magnitude_accuracy: PBIAS, RMSE
m.update(trend_metrics(obs, sim))   # trend_match: r_detr, r_firstdiff, slope_ratio


| Metric | Meaning | Use |
|---|---|---|
| `pbias` | determining metric; magnitude vs the aggregate | grade only against the applicable convention bar |
| `r_detr` | interannual skill after removing each series own linear trend | trend diagnostic |
| `r_firstdiff` | year-over-year change skill (trend-free by construction) | trend diagnostic |
| `slope_ratio` | sim trend / obs trend; near 0 is EXPECTED under constant management | report, do not score |
| `r` (raw), `nse` | NOT skill metrics for this shape | report as `r_raw` for transparency only |

**Do NOT truncate the record to a "management-consistent" sub-window in place of
detrending.** Truncation is not one of the dag `detrending_options`, it discards
data, and it moves PBIAS without removing the trend it was chosen to handle. A
sub-window may be reported as an ADDITIONAL diagnostic, clearly labelled, never
as a substitute.

**Worked example (GDHY wheat, Balcarce AR, 1984-2016, n=33).** Raw `r = -0.19`
looked like an anti-correlated model. `trend_metrics` on the SAME pairs gives
`r_detr = +0.14`, `r_firstdiff = +0.33`, `slope_obs = +0.074 t/ha/yr`,
`slope_sim = -0.042 t/ha/yr`. The negative raw r was entirely an artefact of the
obs technology trend. The only real model finding is `pbias = +40.8%`, i.e. the
attainable-vs-actual yield gap of triplet dt_019 - handle that with
region-matched management (dt_019), not with a metric change.

### 8.3 Calibration / validation split

`period_calibration` and `period_validation` must be DISJOINT. Emitting the same
window twice, so that `nse_val` is bit-identical to `nse_cal`, reports no
independent information. For an uncalibrated forward run, either split the
seasons into two disjoint periods or declare a single period and omit the
`_cal` / `_val` fields.

## 11. Validated Results

No achieved calibration, validation, or full-period metric values are stated in
the provided KI facts. Grade `Grain.Wt` runs against `docs/validation_convention.yaml`;
do not substitute remembered crop-model thresholds.

### Performance Metrics — convention bars for `Grain.Wt`

Each row below restates one convention entry for `Grain.Wt`. For minimize metrics,
lower values are better; for maximize metrics, higher values are better.

| Variable | Metric | Direction | Very good band | Good band | Satisfactory band |
|----------|--------|-----------|----------------|-----------|-------------------|
| `Grain.Wt` | `nrmse` | minimize | <= 10 (`zhao2012`, `brown2018`) | <= 20 (`zhao2012`, `brown2018`) | <= 30 (`zhao2012`, `brown2018`) |
| `Grain.Wt` | `ef` | maximize | >= 1.0 (`brown2018`) | no cited threshold | >= 0.0 (`brown2018`) |
| `Grain.Wt` | `nrmse` | minimize | <= 10 (`zhao2012`, `brown2018`) | <= 20 (`zhao2012`, `brown2018`) | <= 30 (`zhao2012`, `brown2018`) |
| `Grain.Wt` | `nse` | maximize | >= 0.75 (`pasley2023`) | >= 0.65 (`pasley2023`) | >= 0.5 (`pasley2023`) |
| `Grain.Wt` | `nrmse` | minimize | <= 10 (`zhao2012`, `lu2022`) | <= 20 (`zhao2012`, `lu2022`) | <= 30 (`zhao2012`, `lu2022`) |
| `Grain.Wt` | `nse` | maximize | >= 0.75 (`pasley2023`) | >= 0.65 (`pasley2023`) | >= 0.5 (`pasley2023`) |

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | Pipeline | Pending validation result in this document | Use `preflight_check.py` before any run. |
| Soil | Pipeline | Pending validation result in this document | Use KI soil conversion tools and `docs/format_spec.yaml`. |
| APSIM execution | Actual APSIM binary/package | Required | Do not substitute a simplified formula or approximation. |
| Observations | Observation-binding workflow | Pending validation result in this document | Choose obs shape from the dag before computing metrics. |

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
