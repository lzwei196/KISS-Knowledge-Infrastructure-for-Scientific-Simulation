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
| on ANY error, before debugging | `diagnostics/triplets.yaml` (32 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (18 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |
| what past runs learned | `.kdt_evolution.jsonl` | append-only memory of previous runs and fixes on this KI. |

*Projected 2026-08-22 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_climate_to_monica.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_climate_to_monica.py --help` |
| `tools/convert_soil_to_monica.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_monica.py --help` |
| `tools/parse_monica_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_monica_output.py --help` |
| `tools/run_monica.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_monica.py --help` |
| `tools/site_photoperiod.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/site_photoperiod.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# MONICA — Model of Nitrogen and Carbon in Agro-ecosystems

## Package Metadata

| Field            | Value                                              |
|------------------|----------------------------------------------------|
| Model            | MONICA v3.x                                        |
| Domain           | Crop / agro-ecosystem simulation                   |
| Language          | C++17 (core), Python (orchestration)              |
| Build system     | CMake ≥ 3.22                                       |
| Time step        | Daily                                              |
| Spatial domain   | 1-D column, 1 m² surface, 2 m depth               |
| License          | Mozilla Public License 2.0                         |
| Repository       | https://github.com/zalf-rpm/monica                 |
| Parameters repo  | https://github.com/zalf-rpm/monica-parameters      |
| Infrastructure   | https://github.com/zalf-rpm/mas-infrastructure     |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/FAOSTAT/SKILL.md` for crop yield observations.
See `data_ki/SPAM/SKILL.md` for gridded yield data.


## Overview

MONICA is a dynamic, process-based simulation model that describes the transport
and bio-chemical turnover of carbon, nitrogen, and water in agro-ecosystems. On
daily time steps, it mechanistically models the most important processes in soil
and plant, linked so that feedback relations are reproduced as closely to nature
as possible.

Key simulation modules:
- **Soil moisture** (THESEUS water balance): infiltration, evapotranspiration, percolation, capillary rise
- **Soil temperature**: heat diffusion with snow-cover damping
- **Soil organic matter**: multi-pool C/N turnover (AOM → SMB → SOM)
- **Crop growth**: phenology, photosynthesis, organ-based biomass partitioning, N uptake
- **Nitrogen cycling**: nitrification, denitrification, N₂O emissions, leaching, volatilization

---

## Pipeline Overview

| # | Stage                 | Tool                          | Input                    | Output                   |
|---|----------------------|-------------------------------|--------------------------|--------------------------|
| 1 | Climate forcing      | `convert_climate_to_monica.py`| Global met CSV/NetCDF    | MONICA `climate.csv`     |
| 2 | Soil parameterisation| `convert_soil_to_monica.py`   | HWSD / soil DB           | `site.json` soil layers  |
| 3 | Crop rotation setup  | (manual / template)           | Agronomic calendar       | `crop.json`              |
| 4 | Simulation config    | (manual / template)           | Dates, outputs, switches | `sim.json`               |
| 5 | Execution            | `run_monica.py`               | sim.json + all inputs    | `out.csv`                |
| 6 | Output parsing       | `parse_monica_output.py`      | `out.csv`                | Clean CSV / metrics      |

---

## Tools Reference

| Script                          | Lines | Purpose                                        |
|---------------------------------|-------|------------------------------------------------|
| `convert_climate_to_monica.py`  | ~300  | Global forcing → MONICA climate.csv            |
| `convert_soil_to_monica.py`     | ~250  | HWSD/generic soil → site.json soil profile     |
| `run_monica.py`                 | ~200  | Execute monica-run binary with preflight checks|
| `parse_monica_output.py`        | ~250  | Extract output CSV to clean timeseries + metrics|

---

## Execution Model

MONICA is run via the standalone CLI binary `monica-run`:

```bash
export MONICA_PARAMETERS=/path/to/monica-parameters
monica-run [options] path/to/sim.json
```

### CLI Options

| Flag              | Description                             |
|-------------------|-----------------------------------------|
| `-d, --debug`     | Show debug outputs                      |
| `-sd, --start-date` | Override climate start date (ISO)    |
| `-ed, --end-date`   | Override climate end date (ISO)      |
| `-op, --path-to-output` | Output directory                |
| `-o, --path-to-output-file` | Output file path            |
| `-c, --path-to-crop`  | Override crop.json path             |
| `-s, --path-to-site`  | Override site.json path             |
| `-w, --path-to-climate` | Override climate.csv path         |

### Environment Variable

`MONICA_PARAMETERS` **must** point to the `monica-parameters` directory. Without
it, MONICA cannot resolve `"include-from-file"` references in JSON configs.

---

## Input Files

### 1. sim.json — Simulation Configuration

Controls the simulation run: date range, input file paths, output events, model
switches (irrigation, N-response, water-deficit response).

Key sections:
- `crop.json`, `site.json`, `climate.csv`: paths to companion files
- `climate.csv-options`: CSV parsing (separator, header lines, column mapping)
- `output.events[]`: what variables to write and when (daily, monthly, crop, run)
- `UseSecondaryYields`, `NitrogenResponseOn`, `WaterDeficitResponseOn`: booleans

### 2. site.json — Site & Soil Configuration

Describes location and soil profile:
- `Latitude` [decimal degrees], `Slope` [m/m], `HeightNN` [m]
- `NDeposition` [kg N ha⁻¹ yr⁻¹]
- `SoilProfileParameters[]`: array of layers, each with:
  - `Thickness` [m], `SoilOrganicCarbon` [%], `SoilRawDensity` [kg m⁻³]
  - `KA5TextureClass` or `Sand`/`Clay` fractions [0–1]
- Module parameter includes (soil-moisture, soil-temperature, soil-organic, soil-transport)

### 3. crop.json — Crop Rotation

Defines crop species/cultivar references and management calendar:
- `crops{}`: named crop entries with `species` and `cultivar` JSON includes
- `fert-params{}`: fertilizer library (AN, urea, manure, etc.)
- `cropRotation[]`: array of workstep sequences:
  - `Sowing` (date, plant density)
  - `MineralFertilization` (date, amount [kg N ha⁻¹])
  - `OrganicFertilization` (amount [kg FM ha⁻¹])
  - `Irrigation` (amount [mm])
  - `Tillage` (depth [m])
  - `AutomaticHarvest` (latest date, conditions)

### 4. climate.csv — Daily Weather

Semicolon-separated CSV with 2 header rows (names + units):

| Column    | Unit       | Description                    |
|-----------|------------|--------------------------------|
| DE-date   | DD.MM.YYYY | Date (German format)           |
| iso-date  | YYYY-MM-DD | Date (ISO format, alternative) |
| tavg      | °C         | Mean air temperature           |
| tmin      | °C         | Minimum air temperature        |
| tmax      | °C         | Maximum air temperature        |
| wind      | m s⁻¹      | Wind speed                     |
| globrad   | MJ m⁻² d⁻¹| Global radiation               |
| precip    | mm         | Precipitation                  |
| relhumid  | %          | Relative humidity              |
| sunhours  | h          | Sunshine duration (optional)   |
| vappd     | kPa        | Vapour pressure deficit (opt.) |

**Warning**: The original Hohenfinow2 example uses `globrad` in `J cm⁻²` and
applies a `/100` conversion in `header-to-acd-names`. The internal unit is
**MJ m⁻² d⁻¹**. See Unit Trap Table below.

---

## Output Description

**Source of truth:** `dag.yaml`. The dag is the authoritative description of
MONICA's observable outputs; if this section ever disagrees with `dag.yaml`, the
dag wins and this section must be corrected.

### Headline output

> `Yield` — Harvested crop marketable dry-matter yield. (`kg DM ha-1`)

This is the rank-1 output in `dag.yaml`: `var='Yield'`, `unit='kg DM ha-1'`,
`description='Harvested crop marketable dry-matter yield.'`

### Dag output inventory

| Output variable (dag `var`) | Validation rank | Unit | Description |
|-----------------------------|-----------------|------|-------------|
| Yield | 1 | kg DM ha-1 | Harvested crop marketable dry-matter yield. |
| LAI | see `dag.yaml` | see `dag.yaml` | see `dag.yaml` |
| Stage | see `dag.yaml` | see `dag.yaml` | see `dag.yaml` |
| Act_ET | see `dag.yaml` | see `dag.yaml` | see `dag.yaml` |
| Mois | see `dag.yaml` | see `dag.yaml` | see `dag.yaml` |
| NLeach | see `dag.yaml` | see `dag.yaml` | see `dag.yaml` |
| N2O | see `dag.yaml` | see `dag.yaml` | see `dag.yaml` |
| SOC | see `dag.yaml` | see `dag.yaml` | see `dag.yaml` |
| SumNUp | see `dag.yaml` | see `dag.yaml` | see `dag.yaml` |
| GPP | see `dag.yaml` | see `dag.yaml` | see `dag.yaml` |

### Output CSV Format

Output CSV has 3+ header rows:
1. Field names (Date, Crop, Yield, Mois/1, …)
2. Units ([mm], [kg ha⁻¹], [m³ m⁻³], …)
3. JSON column references (j:Date, j:Crop, …)

### Key Output Variables

| Variable       | Unit          | Description                          |
|----------------|---------------|--------------------------------------|
| Yield          | kg DM ha⁻¹   | Harvested dry-matter yield           |
| LAI            | m² m⁻²       | Leaf area index                      |
| Stage          | 0–7           | Phenological development stage       |
| TempSum        | °C d          | Accumulated temperature sum          |
| Height         | m             | Crop height                          |
| TraDef         | 0–1           | Transpiration deficit (stress)       |
| NDef           | 0–1           | Nitrogen deficiency factor           |
| Act_ET         | mm            | Actual evapotranspiration            |
| ET0            | mm            | Reference ET (Penman-Monteith)       |
| Precip         | mm            | Precipitation                        |
| Mois/1–20      | m³ m⁻³       | Volumetric soil moisture per layer   |
| STemp/1–5      | °C            | Soil temperature per layer           |
| NO3/1–20       | kg N m⁻³     | Nitrate per soil layer               |
| NH4/1–20       | kg N m⁻³     | Ammonium per soil layer              |
| NLeach         | kg N ha⁻¹    | Nitrogen leaching below root zone    |
| Denit          | kg N ha⁻¹    | Denitrification                      |
| N2O            | kg N ha⁻¹    | Nitrous oxide emissions              |
| SOC/1–6        | %             | Soil organic carbon per layer        |
| NEP            | kg C ha⁻¹    | Net ecosystem production             |
| Rh             | kg C ha⁻¹    | Heterotrophic respiration            |
| GPP            | kg C ha⁻¹    | Gross primary production             |

---

## Unit Table / Unit Conversion Table

This table records the unit conversions documented for MONICA input preparation,
output comparison, and known silent traps. Exact machine-readable I/O shapes live
in `docs/format_spec.yaml`; regenerate that file from the KI rather than
hand-editing it.

| Variable | Source unit or condition | MONICA / comparison unit | Conversion | Notes |
|----------|--------------------------|---------------------------|------------|-------|
| globrad | J cm⁻² | MJ m⁻² d⁻¹ | ÷100 | Hohenfinow2-style radiation trap |
| globrad / CMFD shortwave rad | W m⁻² | MJ m⁻² d⁻¹ | ×0.0864 | Daily radiation conversion |
| precip | m d⁻¹ | mm d⁻¹ | ×1000 | Silent magnitude trap |
| CMFD precipitation | kg m⁻² s⁻¹ | mm/day | ×86400 | Daily CMFD workflow |
| CMFD 3-hour precipitation | kg/m²/s | mm/day | ×10800 per step, sum 8 steps | `8b. CMFD/MSWX Data Conventions` |
| MSWX 3-hour precipitation | mm/3hr | mm/day | sum 8 steps | No ×10800 conversion |
| CMFD temperature | K | °C | −273.15 | Use sub-daily observations for Tmin/Tmax |
| MSWX temperature | °C | °C | none | Already Celsius |
| wind | km h⁻¹ | m s⁻¹ | ÷3.6 | Silent magnitude trap |
| relhumid | fraction 0–1 | % 0–100 | ×100 | Silent magnitude trap |
| vappd | mm Hg | kPa | ×0.1333 | Vapour pressure deficit |
| Thickness | cm | m | ÷100 | Fatal soil-layer trap |
| SoilRawDens | g cm⁻³ | kg m⁻³ | ×1000 | Soil bulk density |
| SOC | g kg⁻¹ | % | ÷10 | Soil organic carbon input |
| NDeposition | kg N ha⁻¹ d⁻¹ | kg N ha⁻¹ yr⁻¹ | ×365 | Deposition period trap |
| Fertiliser | kg ha⁻¹ product | kg N ha⁻¹ | ×N% | Convert product mass to nitrogen mass |
| Sand/Clay | % | fraction 0–1 | ÷100 | Soil texture fractions |
| Yield comparison | kg DM ha⁻¹ | kg FW ha⁻¹ at ~12% harvest moisture | ÷0.88 | `yield_FW = yield_DM ÷ 0.88` |

## Unit Trap Table

These are the most dangerous unit conversion errors when preparing MONICA inputs.

| ID  | Variable    | Wrong unit          | Correct unit       | Factor | Severity |
|-----|-------------|---------------------|--------------------|--------|----------|
| UT1 | globrad     | J cm⁻²             | MJ m⁻² d⁻¹        | ÷100   | silent   |
| UT2 | globrad     | W m⁻²              | MJ m⁻² d⁻¹        | ×0.0864| silent   |
| UT3 | precip      | m d⁻¹              | mm d⁻¹             | ×1000  | silent   |
| UT4 | wind        | km h⁻¹             | m s⁻¹              | ÷3.6   | silent   |
| UT5 | relhumid    | fraction 0–1        | % 0–100            | ×100   | silent   |
| UT6 | vappd       | mm Hg               | kPa                | ×0.1333| silent   |
| UT7 | Thickness   | cm                  | m                  | ÷100   | fatal    |
| UT8 | SoilRawDens | g cm⁻³              | kg m⁻³             | ×1000  | silent   |
| UT9 | SOC         | g kg⁻¹              | %                  | ÷10    | silent   |
| UT10| NDeposition | kg N ha⁻¹ d⁻¹      | kg N ha⁻¹ yr⁻¹    | ×365   | silent   |
| UT11| Fertiliser  | kg ha⁻¹ (product)   | kg N ha⁻¹          | ×N%    | silent   |
| UT12| Sand/Clay   | %                   | fraction 0–1       | ÷100   | silent   |

> **All unit traps are silent**: MONICA will run without error; output will
> simply be physically wrong.

---

## Build & Dependencies

### Required Repositories (sibling directories)

```
monica-master/
├── monica/              # this repo
├── monica-parameters/   # crop/soil/fertiliser parameter JSONs
└── mas-infrastructure/  # shared C++ libraries (mas_cpp_misc symlink)
```

### Build Steps (Linux)

```bash
cd monica
ln -sf ../mas-infrastructure/src mas_cpp_misc   # if not already linked
mkdir _cmake_release && cd _cmake_release
cmake -DCMAKE_BUILD_TYPE=Release ..
make -j$(nproc)
```

### Dependencies
- CMake ≥ 3.22
- C++17 compiler (GCC ≥ 7, Clang ≥ 5)
- Cap'n Proto (serialisation support)
- ZeroMQ (for distributed mode, optional for local runs)
- pthreads
- Python 3 (for orchestration scripts)

---

## Crop Organs and Development Stages

### Organ Indices

| Index | Organ              | Output key   |
|-------|--------------------|--------------|
| 0     | Root               | OrgBiom/Root |
| 1     | Leaf               | OrgBiom/Leaf |
| 2     | Shoot / Stem       | OrgBiom/Shoot|
| 3     | Storage (grain)    | OrgBiom/Fruit|
| 4     | Permanent structure| OrgBiom/Struct|

### Development Stages (0–7)

| Stage | Name                     | Key event              |
|-------|--------------------------|------------------------|
| 0     | Germination              | Sowing → emergence     |
| 1     | Emergence                | Leaf unfolding         |
| 2     | Leaf development         | Tillering              |
| 3     | Tillering / stem elong.  | Jointing               |
| 4     | Heading / flowering      | Anthesis               |
| 5     | Fruit development        | Grain fill             |
| 6     | Ripening                 | Senescence             |
| 7     | Maturity / harvest ready | Automatic harvest      |

---

## Soil Organic Matter Pools

MONICA tracks 6 organic matter pools per layer:

| Pool     | Full name                    | Typical source        |
|----------|------------------------------|-----------------------|
| AOM_Fast | Added OM, fast decomposing   | Green manure, roots   |
| AOM_Slow | Added OM, slow decomposing   | Straw, wood           |
| SMB_Fast | Soil microbial biomass, fast | Active decomposers    |
| SMB_Slow | Soil microbial biomass, slow | Dormant microbes      |
| SOM_Fast | Soil organic matter, fast    | Young humus           |
| SOM_Slow | Soil organic matter, slow    | Stable humus          |

Conversion: `SOC = SOM × 0.58` (OM-to-C ratio)

---

## Calibration Parameters (most sensitive)

| Parameter                        | Default | Range       | Unit   | Module       |
|----------------------------------|---------|-------------|--------|--------------|
| pc_MaxAssimilationRate           | varies  | 15–60       | µmol m⁻² s⁻¹ | Crop    |
| pc_StageTemperatureSum[]         | varies  | crop-dep.   | °C d   | Crop         |
| pc_CropSpecificMaxRootingDepth   | varies  | 0.5–2.0     | m      | Crop         |
| Kc factor per stage              | varies  | 0.3–1.3     | –      | Soil moisture|
| vs_FieldCapacity                 | PTF     | 0.10–0.45   | m³ m⁻³| Soil moisture|
| vs_PermanentWiltingPoint         | PTF     | 0.04–0.20   | m³ m⁻³| Soil moisture|
| ps_MicrobialUtilizationEfficiency| 0.5     | 0.3–0.7     | –      | Soil organic |
| snowRetainedWaterToSnowRatio     | varies  | 0.0–0.5     | –      | Snow         |

---

## Quick Start

```bash
# 1. Clone all repos
mkdir monica-master && cd monica-master
git clone https://github.com/zalf-rpm/monica.git
git clone https://github.com/zalf-rpm/monica-parameters.git
git clone https://github.com/zalf-rpm/mas-infrastructure.git

# 2. Set up symlink and build
cd monica
ln -sf ../mas-infrastructure/src mas_cpp_misc
mkdir _cmake_release && cd _cmake_release
cmake -DCMAKE_BUILD_TYPE=Release ..
make -j$(nproc)

# 3. Set parameters path
export MONICA_PARAMETERS=$(pwd)/../../monica-parameters

# 4. Run Hohenfinow2 example
./monica-run -o ../../output/out.csv ../installer/Hohenfinow2/sim-min.json
```

---

## Diagnostic Triplets Summary

See `diagnostics/triplets.yaml` for the full set. Key entries:

| ID    | Symptom                              | Root cause                                          |
|-------|--------------------------------------|-----------------------------------------------------|
| dt_01 | Yield is 10–100× too high            | globrad in J cm⁻² not MJ m⁻² d⁻¹                  |
| dt_02 | Zero crop growth                     | MONICA_PARAMETERS not set                           |
| dt_03 | Negative soil moisture               | Thickness in cm instead of m                        |
| dt_04 | Unrealistic ET                       | Wind in km h⁻¹ instead of m s⁻¹                    |
| dt_05 | JSON parse error                     | Trailing comma or missing bracket                   |
| dt_06 | N leaching 10× too high             | NDeposition daily not yearly                        |
| dt_18 | Crash exit -6, no output             | SoilProfileParameters at root not in SiteParameters |
| dt_19 | Zero yield, 0s elapsed               | csv-separator mismatch (tool outputs ";", default ",") |
| dt_20 | UnicodeDecodeError in soil tool      | Passing .bil raster to --format hwsd (needs CSV)    |
| dt_21 | PBIAS < -40% for China wheat         | UseAutomaticIrrigation false (rainfed vs irrigated) |
| dt_22 | CMFD yields 26% above NASA POWER     | Higher observed radiation in CMFD → more GPP        |
| dt_23 | Henan -13% despite irrigation        | HWSD 80% sand ≠ cultivated Fluvisol texture         |

---

## Validated Results

Validation is judged against `docs/validation_convention.yaml`, not against
intuition or remembered thresholds. The convention wins over any threshold stated
elsewhere in prose.

### Rank-1 validation target

| Property | Value |
|----------|-------|
| Dag variable | Yield |
| Dag unit | kg DM ha-1 |
| Dag description | Harvested crop marketable dry-matter yield. |
| Direction of headline judging | Lower error is better for PMARE and NMAE; PBIAS is zero-centered |

### Performance bars from `docs/validation_convention.yaml`

| Variable | Metric | Direction | Very good band | Good band | Satisfactory band | Citation key(s) |
|----------|--------|-----------|----------------|-----------|-------------------|-----------------|
| Yield | pmare | minimize | ≤10 (sarkar2014) | ≤15 (sarkar2014) | ≤25 (sarkar2014) | sarkar2014 |
| Yield | nmae | minimize | ≤0.19 (nendel2011) | ≤0.29 (nendel2011) | ≤0.3 (nendel2011) | nendel2011 |
| Yield | pmare | minimize | ≤10 (sarkar2014) | ≤15 (sarkar2014) | ≤25 (sarkar2014) | sarkar2014 |
| Yield | pbias | zero_centered | within ±3 (jahr2016, bergez2022) | within ±4 (jahr2016, bergez2022) | within ±15 (jahr2016, bergez2022) | jahr2016, bergez2022 |

### Current documented validation run

The body currently documents a China multi-site CMFD workflow validated on 5
provinces for winter wheat during 1991–2000, with default parameters and PBIAS
reported against provincial reference yields.

| Province | Lat | Metric reported | Result |
|----------|-----|-----------------|--------|
| Hebei | 38.5° | PBIAS | +5.8% |
| Shandong | 36.5° | PBIAS | +10.3% |
| Henan | 34.0° | PBIAS | -13.3% |
| Jiangsu | 33.5° | PBIAS | +19.7% |
| Anhui | 32.5° | PBIAS | +16.4% |

These PBIAS results should be interpreted with the zero-centered Yield PBIAS
bands above: within ±3 is very good (jahr2016, bergez2022), within ±4 is good
(jahr2016, bergez2022), and within ±15 is satisfactory (jahr2016, bergez2022).

---

## Coupling Points

- **Climate forcing**: any gridded product (ERA5, CMFD, MSWX) → convert to MONICA CSV
- **Soil data**: HWSD, SoilGrids, KA5 → convert to site.json layers
- **Yield comparison**: FAO, USDA NASS, national statistics
- **Carbon flux**: eddy covariance towers (NEE, GPP, Rh)
- **Water balance**: lysimeter data, soil moisture sensors, recharge estimates

---

## China Multi-Site Workflow (CMFD forcing)

Validated on 5 provinces (Hebei, Shandong, Henan, Jiangsu, Anhui), winter wheat,
1991–2000. PBIAS range: -13% to +20% vs. provincial reference yields.

### Step-by-step

**1. Extract CMFD point data**

CMFD daily files only have mean temperature (`temp`, K). Derive Tmin/Tmax from
3-hourly files (`Data_forcing_03hr_010deg/Temp/temp_CMFD_..._YYYYMM.nc`, 8 steps/day):

```python
# Per month, per year:
data = ds.variables['temp'][:, ilat, ilon]  # shape (n_3hr,) in K
tmin = [float(data[d*8:(d+1)*8].min()) - 273.15 for d in range(ndays)]
tmax = [float(data[d*8:(d+1)*8].max()) - 273.15 for d in range(ndays)]
```

Daily srad (W/m²) → MJ/m²/day: `× 86400 / 1e6 = × 0.0864`
Daily prec (kg/m²/s) → mm/day: `× 86400`

Write intermediate CSV with columns:
`date, tavg_C, tmin_C, tmax_C, wind_ms, globrad_MJm2, precip_mm, relhumid_pct`

**2. Convert to MONICA climate.csv**

```bash
python convert_climate_to_monica.py \
  --input cmfd_raw.csv --format generic_csv \
  --output climate.csv \
  --date-col date --tavg-col tavg_C --tmin-col tmin_C --tmax-col tmax_C \
  --wind-col wind_ms --globrad-col globrad_MJm2 \
  --precip-col precip_mm --relhumid-col relhumid_pct
```

⚠️ Output uses **semicolon (`;`)** as delimiter. Update sim.json:
```json
"climate.csv-options": { "no-of-climate-file-header-lines": 2, "csv-separator": ";" }
```

**3. Generate site.json from HWSD**

First look up MU_GLOBAL from `data/soil/HWSD_RASTER/hwsd.bil` (rasterio), then
extract T_SAND/T_CLAY/T_OC/T_BULK_DENSITY/T_PH_H2O from `data/soil/HWSD_DATA.csv`
(open with `encoding='latin-1'`).

Write a 1-row CSV with T_* columns → pass to `convert_soil_to_monica.py --format hwsd`.

⚠️ **Site.json structure bug (fixed in tool)**: the tool previously emitted
`SoilProfileParameters` at the JSON root. It must be nested inside `SiteParameters`
or MONICA crashes with `std::out_of_range` (exit -6). This is fixed in the tool
as of 2026-04-30. If using an older version, apply the fix manually.

After generating, merge onto the working template (preserves `SoilTemperatureParameters`,
`SoilOrganicParameters`, etc.) and set correct latitude.

**4. Irrigation settings for China wheat**

```json
"UseAutomaticIrrigation": true,
"AutoIrrigationParams": {
    "irrigationParameters": { "nitrateConcentration": [0, "mg dm-3"] },
    "amount": [50, "mm"],
    "trigger_if_nFC_below_%": [55, "%"],
    "calc_nFC_until_depth_m": [0.6, "m"]
}
```

Also relax AutomaticHarvest precip conditions (original too strict for China):
```json
"max-3d-precip-sum": 25,
"max-curr-day-precip": 5
```

**5. Cultivar photoperiod transfer + emergence control + phenology gate (MANDATORY outside Central Europe; 2026-08-22, dt_29 / dt_30)**

MONICA's stock long-day cultivars (`crops/wheat/winter-wheat.json`: `DaylengthRequirement` 20 h, `BaseDaylength`
0/7 h, `VernalisationRequirement` 50 d) are a ~52°N parameterisation: MONICA's photoperiodic daylength (sun at −6°,
`src/core/crop-module.cpp` "old DLP") peaks at 18.5 h there, at 35°N at only 15.5 h, so the long-day factor
`(DL − base) / (20 − base)` that multiplies every stage's thermal time stays ~0.45–0.55 through the whole spring.
Probe (34.6°N / 115.1°E, CMFD, 1999–2015, irrigated, N 203): stem elongation starts ~Apr 2, anthesis ~May 27,
maturity ~Jun 22 — real NCP wheat joints mid-March, flowers late April–early May and matures Jun 5–10. Grain
fill lands in the >30 °C late-June window, the harvest index collapses to ~0.2 (AbBiom 16–17 t, Yield ~3 t DM ha⁻¹),
and 11/17 seasons are cut by `latest-date` — the −50 % PBIAS of the 2026-08-22 GDHY run, NOT a water/N problem
(TraDef ≈ 1, NDef ≈ 1, HeatRed = 1).

Rule (latitude-derived, NO yield fitting): set every positive `DaylengthRequirement` entry to the site's maximum
photoperiodic daylength, so the photoperiod factor saturates at the local solstice:
```bash
python tools/site_photoperiod.py daylength --lat 35.0          # -> dl_max_photoperiodic_h 15.5 (52.5N: 18.5)
python tools/site_photoperiod.py adapt --lat 35.0 \
    --base $MONICA_PARAMETERS/crops/wheat/winter-wheat.json --out winter-wheat_35N.json
```
and use the written object as `cropParams.cultivar` (inline it, or include it by path). The tool is for LONG-DAY
cultivars only: it refuses (exit 2, nothing written) any base carrying a negative short-day `DaylengthRequirement`
entry in ANY stage (e.g. `crops/soybean/*.json`), an `--out` that resolves to `--base`, and any `--out` inside the
monica-parameters repository (detected from `--base`; `$MONICA_PARAMETERS` is protected too). It creates NO
directories — the parent of `--out` must already exist (make your run directory first) — and writes exactly
`<out>.tmp` then `<out>` (rename); a pre-existing `<out>.tmp` is refused. EVERY refusal, including command-line
usage errors (missing `--out`, non-numeric `--lat`, …), is one JSON `{"status":"error","error":…}` on stdout with
exit 2 (only `-h/--help` prints usage text, exit 0), so a caller can always `json.loads` the stdout. Same probe after the rule:
anthesis ~May 9, maturity ~Jun 9, 2/17 seasons at the cap, HI 0.28, mean 4849 kg DM ha⁻¹ (+54 %). Keep
`VernalisationRequirement` (30 vs 50 changes < 2 %) and the stage temperature sums. The shipped low-latitude
`winter-wheat_AgMIP4_bacanora_St1.json` is a spring type (vern 1, DL 11.5/16.67 h) and is WRONG for the NCP
(anthesis Apr 1, 2923 kg DM ha⁻¹).

Also set `"EmergenceMoistureControlOn": false` in sim.json (the validated multisite sim.json had it; the MODEL
DEFAULT IS TRUE — `monica-parameters.h` `pc_EmergenceMoistureControlOn{true}` — docs/06 used to say false).
With it on, a dry NCP autumn seedbed (e.g. the 2010 drought) keeps the crop in germination (output Stage 1) from
October to March: auto-irrigation cannot help because `SoilColumn::applyIrrigationViaTrigger` only fires inside
the cultivar's heat-sum window (`HeatSumIrrigationStart/End` 461–1676 °Cd, i.e. never before emergence), and
the season yields 0 (13 % of the 2026-08-22 column-seasons; 1999: 63/80 columns).

Phenology gate BEFORE scoring Yield: add the event blocks `"anthesis", ["Date","Crop"]` and
`"maturity", ["Date","Crop"]` next to the `"crop"` block (parse with `parse_monica_output.py --columns section
Date ...`; rows of those blocks carry `section` = anthesis/maturity), and require the median simulated
anthesis/maturity within ±10 d of the regional calendar (validation_convention Stage band) with < 10 % of the
seasons cut at `latest-date` without a maturity row. A season harvested ON `latest-date` without maturity is a
phenology failure, not a yield. Do NOT add `["Stage|harvest","LAST"]` to the crop block — it duplicates the
`harvest` header and the parser then returns the stage instead of the harvest date.

### Validated performance (5 sites, default parameters)

| Province | Lat   | PBIAS (sim DM vs. prov. ref FW) | Irrigation/yr |
|----------|-------|----------------------------------|---------------|
| Hebei    | 38.5° | +5.8%                           | 150 mm        |
| Shandong | 36.5° | +10.3%                          | 128 mm        |
| Henan    | 34.0° | -13.3% (sandy HWSD, see dt_23) | 111 mm        |
| Jiangsu  | 33.5° | +19.7%                          | 78 mm         |
| Anhui    | 32.5° | +16.4%                          | 83 mm         |

### Unit notes for output comparison

MONICA yields are **kg DM ha⁻¹**. National/provincial statistics are **kg FW ha⁻¹**
at ~12% harvest moisture.

Conversion: `yield_FW = yield_DM ÷ 0.88` (÷ (1 − 0.12))

**Which obs are fresh weight (2026-08-22, dt_31):** every statistics-derived yield — FAOSTAT, provincial
yearbooks, and the gridded GDHY v1.2/1.3 product, which is harmonised to FAO/national statistics (its `.nc4`
files carry no unit attribute) — is FW: apply the ÷0.88 to the MONICA DM yield BEFORE scoring and STATE the
convention in the result (keep the DM-direct number as an auxiliary). Compare DM-direct only against obs
explicitly reported as dry matter (field trials, GGCMI/AgMIP protocol data). 2026-08-22 GDHY NCP block
(20 × 0.5° cells, 2000–2016, `run_and_score.py`, phenology gate PASS): per-site median PBIAS −16.0 % DM-direct
→ −4.6 % FW (block mean sim 4.38 t DM = 4.97 t FW vs obs 5.31 t/ha). The validated 5-site table above is
DM-direct legacy (dt_25) — never mix it with FW numbers.

CMFD forcing gives ~26% higher yields than NASA POWER at the same site (higher
observed radiation → more photosynthesis).

⚠️ **Comparison-scale gate (driven by obs_shape, NOT by the forcing product).** A
single 1-D MONICA column represents ONE productive, managed field — not a province
and not a nation. When the observation is a `regional_aggregate_time_series`
(FAOSTAT national means, provincial yearbook means), the dag
(`outputs.Yield.observability`) declares ONLY [magnitude_accuracy, trend_match]
valid and REQUIRES the point sim to be representative-aggregated to the region
before scoring (see triplet dt_24). Raw NSE/KGE/r (temporal_pattern_match) are
structurally invalid for this obs_shape and must NOT gate a retry.
  - Compare a single-province point against the matching PROVINCIAL reference
    (e.g. Shandong wheat ≈ 4200 kg ha⁻¹ FW → PBIAS +10.3%, table above), NEVER
    against the national FAOSTAT mean — a single irrigated high-yield province
    overshoots the national aggregate by +40–45% (structural scale mismatch, the
    irrigated mirror of dt_21’s rainfed undershoot; not a model/unit error).
  - To compare against the national aggregate honestly, area-weight several
    province point runs into one series and detrend BOTH sim and obs first
    (the national series carries a multi-decade technology trend a weather-driven
    point cannot reproduce).
  - This applies to BOTH NASA POWER and CMFD forcing — it is a property of the
    obs_shape, not of the radiation product.

**Reporting contract for regional-aggregate / gridded-statistics yield obs (2026-08-22, dt_32).** When the
obs_shape is `regional_aggregate_time_series` (FAOSTAT, provincial yearbooks, and GDHY/SPAM pixels — statistics-
harmonised area means with a technology trend), the result's headline `metrics` block and EVERY `test_runs[]` row
carry ONLY the dag-valid families: `pbias` (+ `rmse`) for magnitude_accuracy and `trend_error` / `decadal_pbias` /
`slope_ratio` for trend_match, plus `determining_metric: pbias`, `obs_shape`, `metric_families_valid` and
`detrending_applied`. NSE/KGE/r from the SAME `all_metrics` call go to `aux_temporal_pattern_not_gate_valid`
(transparency) — NEVER into `metrics` or a `test_runs` row: the orchestrator's dag_driven_gate REJECTs the whole
retest (`REJECT_WRONG_METRIC … families not in valid_families=['trend_match','magnitude_accuracy']`) as soon as a
row carries nse/kge/r for this obs_shape, and the route reader takes the first of r/nse/kge it finds as the verdict
stat, so a structurally ~0 r (dt_24/dt_25) would route the case to fix_ki for ever. Definitions (`run_and_score.py`
stage 5): `trend_error` = slope of (sim − obs) over the scored years × (n − 1) / mean(obs) — the fraction of the obs
mean the bias drifts across the record (0 = no residual trend; negative = the sim falls behind a rising obs);
`decadal_pbias` = max |PBIAS| of the first-half and second-half means; `slope_ratio` = sim/obs linear slope
(`ki_tools_common.metrics.trend_metrics`). A fixed-management run does NOT carry the technology trend — NCP block
2000–2016: slope_ratio 0.15, trend_error −0.36, half-period PBIAS +7.8 % → −14.4 % — report it, do not tune for it
(dt_25). `run_and_score.py` writes `metrics`, `test_runs[0]` and the aux block in exactly this shape; a retest/report
agent hands the runner off with `kdt_detached_run.py`, returns `run_detached` and lets the orchestrator harvest
`result.json` itself — it copies the row VERBATIM and never re-authors it from the generic nse/kge/pbias template.
The runner refuses to start (rc 1) without `KDT_RUN_CONTEXT` (exported by `kdt_detached_run.py`) or `KDT_STATE_DIR`
— the check is the first statement after the stdlib imports (before numpy/pandas/xarray/ki_tools_common are imported
and before the work dir is created), it never guesses a state dir, so a `result.json` can never land in a stale
detached dir (2026-08-22 v6/v7). Every KI-tool call (stage 0 and the parser included) must return rc 0 AND a trailing
stdout JSON object with `status: success` AND its output file, else `tools_failed` + RuntimeError — no silent fallback;
`tools_used` lists only the KI tools / `ki_tools_common` functions the process actually invoked, and
`tools_reused_from_cache` counts the cached tool outputs a resumed run consumed instead (2026-08-22 v8).
