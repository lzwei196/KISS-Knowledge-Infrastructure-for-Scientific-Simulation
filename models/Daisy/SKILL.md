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
| to run the pipeline stages | `tools/` (5 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (19 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (17 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/calib_run.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help` |
| `tools/convert_soil_to_dai.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_dai.py --help` |
| `tools/convert_weather_to_dwf.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_weather_to_dwf.py --help` |
| `tools/parse_daisy_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_daisy_output.py --help` |
| `tools/run_daisy.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_daisy.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# Daisy v7.1.4 (Soil-Crop-Water Simulation Model) — Knowledge Infrastructure

**Package**: `hydrocraft-daisy-soil` v1.0.0
**Model**: Daisy v7.1.4 — Mechanistic simulation of agricultural fields
**Origin**: Agrohydrology Group, University of Copenhagen
**Last updated**: 2026-03-25
**Stats**: 4 tools | 6 skill documents | 18 diagnostic triplets | ~2,500 lines of validated Python
**Validation status**: `example_validated` (Taastrup, Denmark, 1986-1988)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for meteorological forcing documentation.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/RISMA/SKILL.md` for soil moisture observations.


## Overview

This knowledge infrastructure enables autonomous simulation of agricultural field processes
using the Daisy model, covering water, nitrogen, carbon, and pesticide dynamics in the
soil-plant-atmosphere system. The 4 validated tools replace manual `.dai` file editing with
a Python pipeline that integrates with global forcing data and standardized soil databases.

**What Daisy does**: 1D mechanistic model for agricultural field simulation. Simulates:
- Soil water transport (Richards equation, macropore flow, preferential flow)
- Soil heat transport (conduction, convection)
- Nitrogen dynamics (mineralization, nitrification, denitrification, plant uptake)
- Carbon turnover (multi-pool organic matter model: SOM, SMB, AOM)
- Crop growth (phenology, photosynthesis, root growth, water/N stress)
- Pesticide fate (sorption, degradation, transport)
- Field management (tillage, fertilization, irrigation, sowing, harvest)
- Groundwater coupling (deep drainage, aquifer interaction)
- Snow and frost dynamics

**Key architectural features**:
- Lisp-like configuration language (`.dai` files)
- Daisy Weather File format (`.dwf`) for meteorological forcing
- Daisy Log File format (`.dlf`) for tabular output
- Library system for reusable soil, crop, management, and log definitions
- Built-in pedotransfer functions (Cosby, HYPRES, van Genuchten)
- Batch and spawn modes for multi-scenario runs

---

## Installation

### Building from source (Linux)

```bash
# Dependencies
apt install g++ cmake libsuitesparse-dev libboost-filesystem-dev python3-pybind11

# Clone and build
git clone https://github.com/daisy-model/daisy.git
cd daisy
mkdir -p build/linux-gcc-portable
cmake . -B build/linux-gcc-portable --preset linux-gcc-portable
cmake --build build/linux-gcc-portable -j $(nproc)

# Binary location
build/linux-gcc-portable/daisy

# Verify
build/linux-gcc-portable/daisy -v
```

### Pre-built packages

```
deb:     apt install ./daisy_7.1.4_amd64.deb
flatpak: flatpak install --user daisy-7.1.4.flatpak
```

### Python dependencies (for KI tools)

```
numpy, pandas, matplotlib, pyyaml
```

---

## Pipeline Stages

The Daisy simulation pipeline consists of 6 stages:

| Stage | Name | Tool | Input | Output |
|-------|------|------|-------|--------|
| S1 | Weather Preparation | `convert_weather_to_dwf.py` | Global forcing (CSV/NetCDF) | `.dwf` file |
| S2 | Soil Definition | `convert_soil_to_dai.py` | HWSD/texture data | Soil `.dai` file |
| S3 | Setup Generation | Manual / template | Weather + Soil + Management | Main `.dai` file |
| S4 | Execution | `run_daisy.py` | Main `.dai` file | `.dlf` output files |
| S5 | Output Analysis | `parse_daisy_output.py` | `.dlf` files | CSV + figures |
| S6 | Validation | Manual | Observed + simulated | Metrics + figures |

---

## 7. Tool Inventory

| Tool | Purpose | Inputs | Outputs |
|------|---------|--------|---------|
| `tools/convert_weather_to_dwf.py` | Convert meteorological forcing into Daisy weather format | Global forcing CSV/NetCDF | `.dwf` weather file |
| `tools/convert_soil_to_dai.py` | Convert soil texture/profile data into Daisy soil definitions | HWSD or custom soil texture/profile data | Soil `.dai` file |
| `tools/run_daisy.py` | Execute the actual Daisy model binary | Main `.dai` setup file and libraries | `.dlf` output files and run logs |
| `tools/parse_daisy_output.py` | Parse Daisy log files into analysis-ready tables | `.dlf` output files | CSV files, summaries, and figures |

### Shared Utilities (`ki_tools_common`)

Tools should use these shared helpers instead of writing raw data extraction or metric code:

```python
from ki_tools_common.load_forcing import load_daily_forcing
from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_forcing_ranges
from ki_tools_common.units import convert
```

---

## 3. Input Format Reference

Exact machine-readable shapes live in `docs/format_spec.yaml`, projected from `dag.yaml`
and `diagnostics/triplets.yaml`. Regenerate that file after changing the dag or triplets;
do not hand-edit it. This section explains the model-facing intent and common traps.

### Weather File (`.dwf`)

The Daisy Weather File is a custom text format with header metadata and columnar data.

**Header section** (keyword: value pairs):
```
dwf-0.0 -- Description text
Station: Taastrup
Elevation: 30 m
Longitude: 12 dgEast
Latitude: 56 dgNorth
TimeZone: 15 dgEast
Surface: reference
ScreenHeight: 2.0 m
Begin: 1962-04-01
End: 2008-10-31
Timestep: 24 hours
NH4WetDep: 0.9 ppm
NH4DryDep: 2.2 kgN/ha/year
NO3WetDep: 0.6 ppm
NO3DryDep: 1.1 kgN/ha/year
TAverage: 7.8 dgC
TAmplitude: 8.5 dgC
MaxTDay: 209 yday
```

**Data section** (tab-separated, after dashed line):
```
Year  Month  Day  GlobRad  AirTemp  Precip  RefEvap
year  month  mday W/m^2    dgC      mm/d    mm/d
1962  4      1    120.4    2.8      0.0     1.3
```

**Required columns**: Year, Month, Day, GlobRad (W/m^2), AirTemp (dgC), Precip (mm/d)
**Optional columns**: RefEvap (mm/d), Wind (m/s), RelHum (%), VapPres (Pa), etc.

### Soil Definition (`.dai`)

Soil is defined hierarchically: horizons → column.

**Horizon** (texture fractions are dimensionless 0-1 or percent with [%]):
```lisp
(defhorizon "My Ap" USDA3            ; or FAO3, ISSS4
  (clay 0.107)                        ; fraction or [%]
  (silt 0.222)
  (sand 0.671)
  (humus 0.024)
  (dry_bulk_density 1.45 [g/cm^3])
  (C_per_N 11.0 [g C/g N])
  (hydraulic M_vG                     ; van Genuchten-Mualem
    (Theta_res 0.0)
    (Theta_sat 0.392)
    (alpha 0.0385)                    ; [cm^-1]
    (n 1.211)
    (K_sat 7.52 [cm/h])))
```

**Texture classification systems**:
- `USDA3`: clay, silt, sand (3 fractions, USDA system)
- `FAO3`: clay, silt, sand (3 fractions, FAO system)
- `ISSS4`: clay, silt, fine_sand, coarse_sand (4 fractions, ISSS system)

**Column** (soil profile = stack of horizons):
```lisp
(defcolumn MySite default
  (Soil (MaxRootingDepth 100 [cm])
        (horizons (-30 [cm] "My Ap")    ; depths are NEGATIVE from surface
                  (-250 [cm] "My C")))
  (Groundwater deep)                     ; or: aquitard, fixed
  (OrganicMatter original
    (init (input 1400 [kg C/ha/y])
          (root 480 [kg C/ha/y])
          (end -20 [cm]))))
```

### Management Definition (`.dai`)

```lisp
(defaction "My Management" activity
  (wait_mm_dd 3 05)                          ; wait until March 5
  (fertilize (N25S (weight 115 [kg N/ha])))  ; mineral fertilizer
  (plowing)
  (wait_mm_dd 4 05)
  (seed_bed_preparation)
  (sow "Spring Barley")
  (wait (or (crop_ds_after "Spring Barley" 2.0)  ; DS 2.0 = ripe
            (mm_dd 08 20)))
  (harvest "Spring Barley" (stub 8 [cm]) (stem 0.70)))
```

### Main Setup File (`.dai`)

```lisp
(input file "tillage.dai")
(input file "crop.dai")
(input file "log.dai")

(defprogram MySimulation Daisy
  (column MySite)
  (weather default "my-weather.dwf")
  (time 1986 12 1 1)                   ; start: YYYY MM DD HH
  (stop 1988 4 1 1)                    ; end:   YYYY MM DD HH
  (manager activity ...)
  (output harvest
    ("Field nitrogen" (when monthly))
    ("Soil nitrogen" (when daily))
    ("Field water" (when monthly))
    ("Soil water" (when daily))
    ("Crop" (crop "Spring Barley"))))

(run MySimulation)
```

---

## 6. Output Description

This section restates `dag.yaml`; if this section and the dag disagree, `dag.yaml` wins.

**Headline output** (`validation_rank: 1`):

> `sorg_DM` — Harvested storage-organ (grain) dry matter — the primary crop yield output. (`Mg DM/ha`)

| Output variable (dag `var`) | Rank | Unit | Notes |
|-----------------------------|------|------|-------|
| `sorg_DM` | 1 | Mg DM/ha | Harvested storage-organ (grain) dry matter — the primary crop yield output. |
| `harvest_index` | dag output | see `dag.yaml` | Other dag output. |
| `Harvest_N` | dag output | see `dag.yaml` | Other dag output. |
| `Leaching` | dag output | see `dag.yaml` | Other dag output. |
| `Denitrification` | dag output | see `dag.yaml` | Other dag output. |
| `Evapotranspiration` | dag output | see `dag.yaml` | Other dag output. |
| `Drain / Percolation` | dag output | see `dag.yaml` | Other dag output. |
| `Theta` | dag output | see `dag.yaml` | Other dag output. |
| `Soil temperature` | dag output | see `dag.yaml` | Other dag output. |
| `DS` | dag output | see `dag.yaml` | Other dag output. |
| `LAI` | dag output | see `dag.yaml` | Other dag output. |

---

## Output Format Reference

### Daisy Log File (`.dlf`)

Tab-separated text with metadata header:
```
dlf-0.0 -- Harvest (defined in 'log-std.dai').

VERSION: 7.1.4
LOGFILE: harvest.dlf
RUN: Mon Mar 25 12:00:00 2026

COLUMN: *
SIMFILE: test.dai
SIM: AndebyFarm

----
year  month  mday  hour  column  crop  stem_DM  ...
```

### Key Output Files

| File | Content | Key Variables | Units |
|------|---------|---------------|-------|
| `harvest.dlf` | Crop harvest events | stem_DM, leaf_DM, sorg_DM, stem_N, sorg_N, harvest_index | Mg DM/ha, kg N/ha |
| `field_nitrogen.dlf` | N balance | Fertilizer, Fixation, Harvest_N, Denitrification, Leaching | kg N/ha |
| `field_water.dlf` | Water balance | Precipitation, Irrigation, Evapotranspiration, Drain, Percolation | mm |
| `soil_nitrogen.dlf` | Soil N profile | NH4, NO3, org_N per layer | kg N/ha |
| `soil_water.dlf` | Soil water profile | Theta per layer | mm |
| `<crop>.dlf` | Crop development | DS, LAI, Height, Root_Depth, WLeaf, WStem, WSOrg | various |

### Harvest Output Variables

| Variable | Description | Unit |
|----------|-------------|------|
| `stem_DM` | Harvested stem dry matter | Mg DM/ha |
| `leaf_DM` | Harvested leaf dry matter | Mg DM/ha |
| `dead_DM` | Harvested dead leaf matter | Mg DM/ha |
| `sorg_DM` | Harvested storage organ (grain) dry matter | Mg DM/ha |
| `stem_N` | Nitrogen in harvested stems | kg N/ha |
| `sorg_N` | Nitrogen in harvested grain | kg N/ha |
| `water_stress_days` | Days with water stress | d |
| `nitrogen_stress_days` | Days with nitrogen stress | d |
| `harvest_index` | Ratio of grain to total aboveground DM | dimensionless |

---

## 8. Unit Conversion Table

This table documents the unit conversions used by the Daisy KI pipeline. Verify source
data attributes before running a new dataset; `docs/format_spec.yaml` is the exact
machine-readable contract.

| Variable / parameter | Source unit | Daisy model unit | Conversion | Type |
|----------------------|-------------|------------------|------------|------|
| `GlobRad` | MJ/m^2/d daily total | W/m^2 daily mean | ÷ 0.0864 (= ×11.574) | multiplicative |
| `AirTemp` | K | dgC (°C) | − 273.15 | additive |
| `AirTemp` | dgC (°C) | dgC (°C) | identity | passthrough |
| `Precip` | mm/3h (CMFD) | mm/d | × 8 | multiplicative |
| `Precip` | kg/m^2/s | mm/d | × 86400 | multiplicative |
| `Precip` | mm/d | mm/d | identity | passthrough |
| `RefEvap` | mm/d | mm/d | identity | passthrough |
| `Wind` | m/s | m/s | identity, but check measurement height | passthrough |
| `RelHum` | fraction (0–1) | % (0–100) | × 100 | multiplicative |
| `VapPres` | Pa | Pa | identity | passthrough |
| Elevation | m | m | identity | passthrough |
| Longitude | degrees (−180 to 180) | dgEast | identity if east; 360−abs(value) if west | convention |
| Latitude | degrees (−90 to 90) | dgNorth | identity | passthrough |
| Clay, silt, sand | percent (0–100) | fraction (0–1) | ÷ 100 | multiplicative |
| Clay, silt, sand | fraction (0–1) | fraction (0–1) | identity | passthrough |
| Bulk density | kg/m^3 | g/cm^3 | ÷ 1000 | multiplicative |
| `K_sat` | m/s | cm/h | × 360000 | multiplicative |
| van Genuchten alpha | m^-1 | cm^-1 | ÷ 100 | multiplicative |
| Horizon depth | positive depth from surface | negative cm from surface | negate | sign convention |
| Fertilizer N | g N/m^2 | kg N/ha | × 10 | multiplicative |
| Organic input | g C/m^2/y | kg C/ha/y | × 10 | multiplicative |
| Timestep | source frequency | 24 hours | aggregate or resample to daily | temporal |

---

## 8c. Sign Conventions and Output Units

These conventions are checked during input preparation and post-processing because sign or
accumulation mistakes can silently invalidate validation metrics.

| Variable | Convention in this KI | Common alternative | Impact if wrong |
|----------|----------------------|--------------------|-----------------|
| `sorg_DM` | Mg DM/ha harvested storage-organ dry matter | fresh mass or kg/ha | Crop yield magnitude and dry-matter comparisons are wrong. |
| `harvest_index` | dimensionless ratio of grain to total aboveground dry matter | percent | Ratios are off by 100 if interpreted as percent. |
| `Harvest_N` | kg N/ha harvested nitrogen | g N/m^2 | Nitrogen removal is off by 10. |
| `Leaching` | kg N/ha nitrogen loss in field nitrogen outputs | concentration or flux rate | Nitrogen balance and validation metrics are not comparable. |
| `Denitrification` | kg N/ha nitrogen loss in field nitrogen outputs | rate per day | Period totals are misread as instantaneous rates. |
| `Evapotranspiration` | mm water-balance output | m or kg/m^2/s | Water balance magnitude is wrong. |
| `Drain / Percolation` | mm water-balance output | m or mm/s | Drainage magnitude and timing are wrong. |
| `Theta` | soil water profile output; see `dag.yaml` and `.dlf` headers for exact unit | percent or volumetric fraction without checking | Soil moisture comparisons can be scaled incorrectly. |
| `Soil temperature` | soil profile temperature; see `dag.yaml` and `.dlf` headers for exact unit | K | Temperature bias is shifted by 273.15. |
| `DS` | dimensionless crop development stage | calendar day or phenological class | Crop timing diagnostics are invalid. |
| `LAI` | leaf area index, dimensionless area ratio | percent cover | Canopy comparisons are not comparable. |

**Output unit verification checklist:**
- Read `dag.yaml` before binding observations or scoring outputs.
- Read `.dlf` headers and unit rows before parsing a new Daisy log definition.
- Print the first values from each parsed output and check order of magnitude.
- For fluxes and balances, verify whether values are timestep rates or period totals.
- For validation, compare `sorg_DM` in `Mg DM/ha` dry matter against observations in the same basis.

---

## Unit Trap Table

These are the most dangerous unit conversion pitfalls when preparing Daisy inputs:

| Parameter | Daisy Expects | Common Source Unit | Conversion | Severity |
|-----------|---------------|-------------------|------------|----------|
| GlobRad | W/m^2 (daily mean) | MJ/m^2/d (daily total) | ÷ 0.0864 (= ×11.574) | **CRITICAL** |
| AirTemp | dgC (°C) | K (Kelvin) | − 273.15 | CRITICAL |
| Precip | mm/d | mm/3h (CMFD) | × 8 | CRITICAL |
| Precip | mm/d | kg/m^2/s | × 86400 | CRITICAL |
| Wind speed | m/s | m/s | identity (but check height) | MEDIUM |
| RelHum | % (0–100) | fraction (0–1) | × 100 | HIGH |
| Elevation | m | m | identity | LOW |
| Longitude | dgEast | degrees (−180 to 180) | identity if E, 360−|val| if W | MEDIUM |
| Latitude | dgNorth | degrees (−90 to 90) | identity | LOW |
| Clay/silt/sand | fraction (0–1) | percent (0–100) | ÷ 100 | **CRITICAL** |
| Bulk density | g/cm^3 | kg/m^3 | ÷ 1000 | CRITICAL |
| K_sat | cm/h | m/s | × 360000 (from m/s to cm/h) | CRITICAL |
| Alpha (vG) | cm^-1 | m^-1 | ÷ 100 | HIGH |
| Horizon depth | negative cm from surface | positive depth | negate | HIGH |
| Fertilizer N | kg N/ha | g N/m^2 | × 10 | HIGH |
| Organic input | kg C/ha/y | g C/m^2/y | × 10 | HIGH |
| Timestep | 24 hours | — | must match data freq | MEDIUM |

---

## 9. Diagnostic Triplets

On any error, inspect `diagnostics/triplets.yaml` before writing new debugging code. The
full triplet corpus stays in YAML to avoid drift; this document only points to the workflow.

| Step | Action | Reason |
|------|--------|--------|
| 1 | Match the observed symptom against `diagnostics/triplets.yaml`. | Known Daisy/KI failures are documented there with remedies. |
| 2 | Apply the listed `remedy` exactly when a triplet matches. | The remedy is part of the KI's validated debugging path. |
| 3 | If no triplet matches, read the relevant `docs/s*_*.md` stage document. | Stage docs contain format expectations and verification traps. |
| 4 | Compare against working files in `outputs/` or shipped Daisy examples. | The correct `.dai`, `.dwf`, and `.dlf` shapes are easiest to confirm from examples. |
| 5 | Only then fix the tool or report the full error. | Avoid replacing the actual Daisy model with a hand-coded approximation. |

---

## Tool Reference

### 1. `convert_weather_to_dwf.py` — Forcing Converter

Converts global meteorological data (CSV with columns for date, temperature, radiation,
precipitation, etc.) into Daisy's `.dwf` weather file format.

**Key conversions**:
- Radiation: MJ/m^2/d → W/m^2 (÷ 0.0864)
- Temperature: K → °C (− 273.15) or passthrough if already °C
- Precipitation: mm/3h → mm/d (× 8) or kg/m^2/s → mm/d (× 86400)
- Validates: no negative radiation, temperature range −60 to +60°C, precip ≥ 0

### 2. `convert_soil_to_dai.py` — Soil/Parameter Converter

Converts HWSD or custom soil texture data into Daisy horizon and column definitions.

**Key conversions**:
- Texture fractions from % to 0–1
- Bulk density from kg/m^3 to g/cm^3
- Depths from positive to negative (Daisy convention)
- Auto-selects texture system (USDA3 for 3-fraction, ISSS4 for 4-fraction)
- Optionally estimates hydraulic parameters via built-in pedotransfer functions

### 3. `run_daisy.py` — Execution Wrapper

Runs the Daisy binary with a given `.dai` setup file and captures output/errors.

**Features**:
- Locates daisy binary (build dir, system PATH, or explicit path)
- Validates that required input files (.dwf, .dai libraries) exist
- Runs with timeout protection
- Captures stdout/stderr and parses daisy.log for errors
- Returns exit code and paths to generated .dlf files

### 4. `parse_daisy_output.py` — Output Parser

Parses `.dlf` (Daisy Log File) output into pandas DataFrames and CSV files.

**Features**:
- Reads DLF header metadata (version, run time, parameters)
- Parses tab-separated data section with proper column types
- Extracts harvest summary, water balance, N balance, crop development
- Computes derived metrics (total yield, N use efficiency, water productivity)
- Generates time series CSV for downstream analysis

---

## Execution Reference

### Command Line

```bash
# Run a simulation
daisy test.dai

# Run with version info
daisy -v

# Run with info
daisy --info

# Run batch (multiple scenarios)
daisy batch.dai
```

### Required Files for a Simulation

1. **Main `.dai` file** — defines the program with column, weather, manager, output
2. **Weather `.dwf` file** — meteorological forcing data
3. **Library `.dai` files** — crop.dai, tillage.dai, fertilizer.dai, log.dai (from lib/)
4. **Soil `.dai` file** — if soil defined in separate file

### Library Files (installed with Daisy)

| File | Content |
|------|---------|
| `crop.dai` | Standard crop parameterizations (wheat, barley, maize, pea, etc.) |
| `tillage.dai` | Tillage operations (plowing, seed bed preparation, etc.) |
| `fertilizer.dai` | Fertilizer types (mineral: N25S, AmmoniumNitrate; organic: slurry) |
| `log.dai` | Standard output log definitions |
| `vegetation.dai` | Vegetation parameters |

---

## 10. Coupling Interfaces

| Upstream source | Variable exchanged | Unit | Temporal resolution |
|-----------------|-------------------|------|---------------------|
| CMFD/MSWX/NASA POWER via `load_daily_forcing` | Weather forcing: radiation, temperature, precipitation, optional evapotranspiration, wind, humidity, vapor pressure | Daisy `.dwf` units | Daily |
| HWSD or custom texture/profile data | Soil texture, bulk density, hydraulic parameters, horizon depths | Daisy `.dai` units | Static profile |
| Management templates or user setup | Tillage, fertilization, sowing, harvest, irrigation | Daisy `.dai` action units | Event-based |

| Downstream consumer | Variable exchanged | Unit | Temporal resolution |
|---------------------|-------------------|------|---------------------|
| Validation workflow | `sorg_DM` | Mg DM/ha | Harvest event / period summary |
| Water-balance analysis | `Evapotranspiration`, `Drain / Percolation`, `Theta` | see `dag.yaml` and `.dlf` headers | Daily to monthly, depending on log definition |
| Nitrogen-balance analysis | `Harvest_N`, `Leaching`, `Denitrification` | see `dag.yaml` and `.dlf` headers | Daily to monthly, depending on log definition |
| Crop-development analysis | `DS`, `LAI`, `harvest_index` | see `dag.yaml` and `.dlf` headers | Daily to harvest event, depending on log definition |

---

## 11. Validated Results

The KI status line records `example_validated` for Taastrup, Denmark, 1986-1988. The
current body campaign is pending; do not invent achieved metric values. When a real
validation run is scored, judge it against `docs/validation_convention.yaml`, not intuition.

### Test Site: Taastrup

| Property | Value |
|----------|-------|
| Location | Taastrup, Denmark |
| Period | 1986-1988 |
| Validation status | `example_validated` |
| Headline output | `sorg_DM` |
| Headline unit | Mg DM/ha |

### Performance Metrics — judged against the field's bar

Convention for `sorg_DM`: metric `pbias`; direction `zero_centered`; citation `moriasi2015`.
The convention's null bands are stated as `no cited threshold`.

> Bar for `sorg_DM` (`pbias`, per `moriasi2015`): satisfactory within 25.0 of zero;
> good: no cited threshold (`moriasi2015`); very good: no cited threshold (`moriasi2015`).
> Achieved: body campaign pending.

| Metric | Calibration | Validation | Full Period | Bar (convention, cited) |
|--------|-------------|------------|-------------|-------------------------|
| PBIAS (%) | body campaign pending | body campaign pending | body campaign pending | satisfactory: zero-centered 25.0 (`moriasi2015`); good: no cited threshold (`moriasi2015`); very good: no cited threshold (`moriasi2015`) |

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | Pipeline | Pending for body campaign | Use `convert_weather_to_dwf.py` and verify with `preflight_check.py`. |
| Soil | Pipeline | Pending for body campaign | Use `convert_soil_to_dai.py` and verify Daisy units/sign conventions. |
| Management | Daisy setup/template | Pending for body campaign | Keep `.dai` actions in Daisy syntax and units. |
| Observations | User/site data | Pending for body campaign | Bind to `sorg_DM` in `Mg DM/ha` dry matter for headline scoring. |
| Outputs | Daisy `.dlf` logs | Pending for body campaign | Parse with `parse_daisy_output.py`; do not hand-code replacement formulas. |

---

## 12. Parameter Selection by Region

These are physically informed starting points, not calibration results. Prefer site-specific
Daisy documentation, local agronomic management records, and the validated Taastrup example
when no local calibration exists.

| Climate / region | Key parameters | Rationale |
|------------------|----------------|-----------|
| Temperate Northern Europe | Built-in Daisy crop libraries, local sowing/harvest dates, measured soil horizons where available | Daisy crop parameterizations are primarily calibrated for temperate agricultural systems. |
| New sites with HWSD-only soils | Texture fractions, bulk density, pedotransfer hydraulic parameters | Provides a reproducible starting soil profile while preserving unit checks. |
| Irrigated fields | Irrigation actions and water-balance logging | Management timing and water additions must be explicit in `.dai` setup files. |

---

## Quick Start Example

```bash
# 1. Copy sample files
cp -r /path/to/daisy/sample /tmp/daisy-test
cd /tmp/daisy-test

# 2. Run the tutorial simulation
daisy test.dai

# 3. Check outputs
cat harvest.dlf          # Crop harvest results
cat field_water.dlf      # Water balance
cat field_nitrogen.dlf   # Nitrogen balance
cat sbarley.dlf          # Spring barley crop development
```

Expected output files: `harvest.dlf`, `field_nitrogen.dlf`, `field_water.dlf`,
`soil_nitrogen.dlf`, `soil_water.dlf`, `sbarley.dlf`, `checkpoint-*.dai`, `daisy.log`

---

## Common Crop Models Available

| Crop | Dai Library | Typical Yield (Mg DM/ha) |
|------|-------------|--------------------------|
| Spring Barley | crop.dai / dk-sbarley.dai | 4–7 |
| Winter Wheat | crop.dai / dk-wwheat.dai | 6–10 |
| Winter Barley | crop.dai / dk-wbarley.dai | 5–8 |
| Winter Rape | crop.dai / dk-wrape.dai | 3–5 |
| Silage Maize | crop.dai / dk-maize.dai | 10–18 |
| Pea | pea.dai | 3–5 |
| Grass | grass.dai | 8–14 (4 cuts/yr) |
| Potato | potato.dai | 6–12 |
| Sugar Beet | sugarbeet.dai | 10–16 |

---

## Known Limitations

1. **1D only** — no lateral flow between fields (except 2D experimental GP2D mode)
2. **Daily or hourly** — sub-hourly forcing not supported in standard mode
3. **Temperate focus** — crop models calibrated primarily for Northern European conditions
4. **No built-in calibration** — parameter optimization requires external tools
5. **Lisp-like syntax** — steep learning curve for configuration files
6. **No GUI** — command-line only (VSCode extension available for syntax highlighting)
