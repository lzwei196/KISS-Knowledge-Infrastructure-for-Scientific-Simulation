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

## Output Format

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

| ID    | Symptom                              | Root cause                           |
|-------|--------------------------------------|--------------------------------------|
| dt_01 | Yield is 10–100× too high            | globrad in J cm⁻² not MJ m⁻² d⁻¹   |
| dt_02 | Zero crop growth                     | MONICA_PARAMETERS not set            |
| dt_03 | Negative soil moisture               | Thickness in cm instead of m         |
| dt_04 | Unrealistic ET                       | Wind in km h⁻¹ instead of m s⁻¹     |
| dt_05 | JSON parse error                     | Trailing comma or missing bracket    |
| dt_06 | N leaching 10× too high             | NDeposition daily not yearly         |

---

## Coupling Points

- **Climate forcing**: any gridded product (ERA5, CMFD, MSWX) → convert to MONICA CSV
- **Soil data**: HWSD, SoilGrids, KA5 → convert to site.json layers
- **Yield comparison**: FAO, USDA NASS, national statistics
- **Carbon flux**: eddy covariance towers (NEE, GPP, Rh)
- **Water balance**: lysimeter data, soil moisture sensors, recharge estimates
