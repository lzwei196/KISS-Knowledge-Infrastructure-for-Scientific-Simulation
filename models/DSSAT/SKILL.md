> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
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

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
Then convert to DSSAT .WTH format using this KI's tool: `tools/s2_weather_prep/convert_cmfd_to_wth.py`

### Soil properties

**Data Sources**: Use `from ki_tools_common.soil_utils import lookup_hwsd` for soil properties.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.

---

# DSSAT-CSM v4.8.5 — Knowledge Infrastructure

**Model**: DSSAT-CSM (Decision Support System for Agrotechnology Transfer, Cropping System Model)
**Version**: 4.8.5, Build 41
**Domain**: Crop simulation — multi-crop growth, development, and yield
**Language**: Fortran 90
**Binary**: `/home/server/DSSAT/build/bin/dscsm048`
**License**: Research/non-commercial
**Repository**: https://github.com/DSSAT/dssat-csm-os

---

## Overview

DSSAT simulates crop growth, development, and yield for 24+ species (wheat, maize, rice, soybean,
sorghum, millet, cotton, etc.) under varying weather, soil, and management conditions. It uses
process-based physiology (photosynthesis, phenology, soil water balance, N/P dynamics) driven by
daily weather data and management schedules.

**Key advantage**: Most detailed crop model in HydroCraft — 50+ diagnostic triplets, 9 pipeline
stages, Chinese cultivar library with 42 calibrated varieties.

---

## Binary Location & Execution

**ALWAYS use `dssat_workdir_setup.py` — NEVER set up DSSAT files manually.**

```python
import sys
sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/DSSAT/knowledge_infrastructure/tools")
from dssat_workdir_setup import create_workdir, run_dssat, parse_summary

# Step 1: Create workdir (handles all 6 Fortran pitfalls automatically)
workdir = create_workdir(
    crop="MZ",                    # MZ=maize, WH=wheat, SB=soybean, RI=rice
    cultivar="IB0001",            # From genotype library (see Chinese Cultivar Library below)
    weather_file="path/to.WTH",   # DSSAT .WTH format weather file
    soil_id="IBMZ910014",         # DSSAT soil profile ID
    lat=32.625, lon=116.375,
    planting_date=80150,           # YYDDD format (year 80, DOY 150) or "YYYY-MM-DD"
    start_year=1980, end_year=1985,
    output_dir="/tmp/dssat_run",
)

# Step 2: Run DSSAT
result = run_dssat(workdir)
print(f"Success: {result['success']}")

# Step 3: Parse results
summary = parse_summary(workdir)
for rec in summary:
    print(f"Yield: {rec['HWAM']} kg/ha, Biomass: {rec['CWAM']} kg/ha")
```

### What `dssat_workdir_setup.py` handles (6 known pitfalls):

| Pitfall | What happens without it | The utility's fix |
|---------|------------------------|-------------------|
| Fortran path truncation | Paths >72 chars cause FOTEFX error | Creates workdir under /tmp/ with short paths |
| Missing .CDE files | MODEL.ERR / crash | Symlinks all CDE+SDA files from DSSAT/Data/ |
| Weather station mismatch | Simulation uses wrong weather | Derives 4-char WSTA code from filename |
| CUL column alignment | Wrong cultivar coefficients | Fixed-width format with exact column positions |
| DSSATPRO paths | Old paths point to wrong dirs | Regenerates with workdir paths |
| Summary.OUT parsing | Manual parsing misses edge cases | Structured dict with date conversion |

**Raw binary** (only if you know what you're doing):
```bash
cd /path/to/working_directory
/home/server/DSSAT/build/bin/dscsm048 B DSSBatch.v48
```

---

## Pipeline Stages

| Order | Stage | Skill Document | Key Tools |
|-------|-------|---------------|-----------|
| 1 | Experiment Design | [s1_experiment_design_skill.md](docs/s1_experiment_design_skill.md) | FileX template generation |
| 2 | Weather Prep | [s2_weather_prep_skill.md](docs/s2_weather_prep_skill.md) | CMFD/MSWX → .WTH conversion |
| 3 | Soil Setup | [s3_soil_setup_skill.md](docs/s3_soil_setup_skill.md) | HWSD → SOIL.SOL conversion |
| 4 | Genotype Config | [s4_genotype_config_skill.md](docs/s4_genotype_config_skill.md) | Cultivar selection from library |
| 5 | Simulation Controls | [s5_simulation_controls_skill.md](docs/s5_simulation_controls_skill.md) | DSSAT48.INP, DSSBATCH.v48 |
| 6 | Initial Conditions | [s6_initial_conditions_skill.md](docs/s6_initial_conditions_skill.md) | Soil water/N initialization |
| 7 | Management Spec | [s7_management_spec_skill.md](docs/s7_management_spec_skill.md) | Planting, fertilizer, irrigation |
| 8 | Batch Execution | [s8_batch_execution_skill.md](docs/s8_batch_execution_skill.md) | Run dscsm048 |
| 9 | Output Parsing | [s9_output_parsing_skill.md](docs/s9_output_parsing_skill.md) | Parse Summary.OUT, PlantGro.OUT |

**Additional tools**: `convert_cmfd_to_wth.py` (CMFD → .WTH conversion) and `convert_hwsd_to_sol.py` (HWSD → SOIL.SOL conversion).

**Stages 1-7 can run in parallel** — they each write a section of the FileX or prepare external files.
Stage 8 depends on all of 1-7. Stage 9 depends on 8.

---

## Unit Conversion Table

| Variable | Source unit (CMFD) | DSSAT expected | Conversion | Trap if wrong |
|----------|--------------------|----------------|------------|---------------|
| Temperature | K | °C | -273.15 | Crop never matures |
| Precipitation | mm/3hr | mm/day | Sum 8 timesteps | Wrong water balance |
| Solar radiation | W/m² | MJ/m²/day | ×0.0864 | Zero or excess growth |
| Wind speed | m/s | km/day | ×86.4 | Wrong ET |
| Precipitation | kg/m²/s (CMFD raw) | mm/day | ×86400 | CMFD 3-hourly files store mm/3hr directly — sum 8 steps |

---

## Chinese Cultivar Library

Location: `/home/server/DSSAT/Data/Genotype/China/`

| Crop | File | Cultivars | Key varieties | Setup Tool |
|------|------|-----------|---------------|------------|
| Wheat | WHCER048_China.CUL | 17 | Zhengmai9023, Jimai22, Yangmai158 | dssat_workdir_setup.py (crop="WH") |
| Maize | MZCER048_China.CUL | 12 | Zhengdan958, Xianyu335, Denghai605 | dssat_workdir_setup.py (crop="MZ") |
| Rice | RICER048_China.CUL | 11 | YZR Hybrid Shanyou, NEC Japonica | **setup_rice_experiment.py** |
| Soybean | SBGRO048_China.CUL | 7 | NEC MG I, HHH MG III | **setup_soybean_experiment.py** |

---

## Diagnostic Triplets (50 entries)

See `diagnostics/triplets.yaml` for the full set. Top 5 most common:

| # | Symptom | Root Cause | Fix |
|---|---------|------------|-----|
| 1 | MODEL.ERR not found | Binary not in workdir | Copy dscsm048 into working directory |
| 2 | Zero yield | Wrong solar radiation unit (W/m² not MJ/m²/d) | Multiply by 0.0864 |
| 3 | Crop never matures | Temperature in K not °C | Subtract 273.15 |
| 4 | FOTEFX error | Path >72 chars (Fortran limit) | Use shorter paths |
| 5 | NL exceeded | FileX has >500 treatments | Split into multiple experiments |

---

## Validated Results

| Basin | Crop | Yield (kg/ha) | Reference | Period |
|-------|------|---------------|-----------|--------|
| Bengbu | Maize | 5,324 | SPAM 2020 (-2.3%) | 2010 |
| Bengbu | Wheat | 4,876 | SPAM 2020 (+1.8%) | 2010 |
| Blue Nile (Ethiopia) | Wheat | 1,482 | Uncalibrated | 2005-2015 |
| Blue Nile (Ethiopia) | Maize | 4,810 | Uncalibrated | 2005-2015 |

### 3×3 Validation Results (2026-04-10)

| Site | Crop | Simulated | SPAM Ref | Bias | Cultivar |
|------|------|-----------|----------|------|----------|
| Bengbu | Maize | 5,937 ± 911 | 5,652 | +5.0% | CN0001 (Zhengdan958) |
| Bengbu | Wheat | 3,987 ± 606 | 6,144 | -35.1% | CN0102 (Jimai22) — 1980s vs 2020 obs |
| Harbin | Maize | 6,027 ± 3,080 | 8,219 | -26.7% | CN0018 (NEC Spring Medium) |
| Harbin | Wheat | 321 ± 353 | 4,170 | -92.3% | FAILED — no spring wheat cultivar |
| São Paulo | Maize | 14,690 ± 1,520 | 3,701 | +297% | IB0035 (US default, uncalibrated) |
| São Paulo | Soybean | 1,977 ± 256 | 3,400 | -41.9% | IB0011 (MG0, needs MG VII-VIII) |

### Known Issues (from validation)

| Issue | Detail | Fix needed |
|-------|--------|-----------|
| **CMFD precip unit** | `convert_cmfd_to_wth.py` assumed mm/3hr but CMFD is kg/m²/s | **Fixed** — now ×10800 per timestep |
| **No spring wheat** | Chinese cultivar library lacks P1V=0 spring wheat | Calibrate NEC spring wheat (P1V=0, P1D~20) |
| **No Brazil cultivars** | US maize default +297% bias in tropics | Need Brazil-calibrated maize/soy library |
| **China CUL not auto-loaded** | `create_workdir()` doesn't merge China/ CUL files | Manually append after workdir creation |

---

## Standalone Workflow (WITHOUT VIC — for single-site or farmer queries)

DSSAT can run **independently** without any hydrological model. Use this workflow when the user
asks about crop yield, planting decisions, or cultivar comparisons — NOT the VIC 10-step workflow.

### Step 1: Get weather data

```python
# Use NASA POWER for any location worldwide (no local data needed)
python skills/vic-auto-run/s2_forcing/forcing_nasa_power.py \
  --lat 45.5 --lon -73.6 --start_year 2005 --end_year 2023 \
  --output_dir outputs/<run>/weather/
# Then convert to DSSAT .WTH format using the forcing-converter skill
```

Or use the validated DSSAT weather tool:
```python
from models.DSSAT.knowledge_infrastructure.tools.fetch_weather import fetch_nasa_power_dssat
fetch_nasa_power_dssat(lat=45.5, lon=-73.6, start=2005, end=2023, output="MTRL0501.WTH")
```

### Step 2: Set up and run using dssat_workdir_setup.py (MANDATORY)

```python
import sys
sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/DSSAT/knowledge_infrastructure/tools")
from dssat_workdir_setup import create_workdir, run_dssat, parse_summary

workdir = create_workdir(
    crop="MZ",                    # MZ=maize, WH=wheat, SB=soybean
    cultivar="IB0001",            # From cultivar library (see below)
    weather_file="path/to/MTRL0501.WTH",
    soil_id="IBMZ910014",
    lat=45.5, lon=-73.6,
    planting_date=5150,           # YYDDD: year 05, DOY 150 (or "2005-05-30")
    start_year=2005, end_year=2015,
    output_dir="outputs/<run>/dssat",
)

result = run_dssat(workdir)
summary = parse_summary(workdir)
for rec in summary:
    print(f"Yield: {rec['HWAM']} kg/ha")
```

### Step 3: Visualize results

```bash
python skills/plot/plot_crop_yield_map.py \
  --csv outputs/<run>/dssat/gridded_yield.csv \
  --value_col hwam_kgha \
  --title "Maize Yield" --output outputs/<run>/yield_map.png
```

---

## Known Limitations

- Chinese cultivar library primarily covers winter wheat zones; spring wheat needs calibration
- FileX format is fixed-width columns — whitespace errors cause silent failures
- Fortran path length limit (~72-256 chars depending on compiler)
- No built-in spatial mode — grid simulations use wrapper scripts

---

*Generated by the Knowledge Dissection Toolkit v4.0.*

---

## Rice Simulation (CERES-Rice / RICER048)

**Model**: CERES-Rice (RICER048 in DSSAT)
**Status**: Validated tool ready, Chinese cultivar library with 11 varieties
**Tool**: `tools/setup_rice_experiment.py`

### Quick Start (Rice)

```python
import sys
sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/DSSAT/knowledge_infrastructure/tools")
from setup_rice_experiment import setup_rice

# Auto-selects cultivar and planting date by latitude
result = setup_rice(
    lat=30.0, lon=114.0,         # Wuhan, Yangtze region
    year=2010,
    weather_file="path/to.WTH",
    soil_id="IB00000001",
    output_dir="/tmp/dssat_rice",
)
# Result contains: workdir, cultivar, summary (if run succeeded)
```

### Chinese Rice Cultivar Table

| Code | Name | Region | System | Plant DOY | Expected Yield (kg/ha) |
|------|------|--------|--------|-----------|----------------------|
| CN0201 | YZR Indica Medium | Yangtze (28-33N) | Single crop | ~120 (May 1) | 6,000-8,000 |
| CN0202 | YZR Indica Early | Yangtze | Single crop | ~110 (Apr 20) | 5,000-7,000 |
| CN0203 | YZR Indica Late | Yangtze | Single crop | ~130 (May 10) | 6,500-8,500 |
| CN0204 | YZR Hybrid (Shanyou) | Yangtze | Single crop | ~125 (May 5) | 7,000-9,500 |
| CN0211 | SC Early Indica | South (<28N) | Double early | ~75 (Mar 16) | 4,000-6,000 |
| CN0212 | SC Early Hybrid | South | Double early | ~80 (Mar 21) | 4,500-6,500 |
| CN0221 | SC Late Indica | South | Double late | ~195 (Jul 14) | 4,000-5,500 |
| CN0222 | SC Late Hybrid | South | Double late | ~190 (Jul 9) | 4,500-6,500 |
| CN0231 | NEC Japonica Calib | Northeast (>40N) | Single crop | ~130 (May 10) | 6,000-8,500 |
| CN0232 | NEC Japonica Early | Northeast | Single crop | ~125 (May 5) | 5,000-7,000 |
| CN0233 | NEC Japonica Late | Northeast | Single crop | ~135 (May 15) | 6,500-9,000 |

### Key CERES-Rice Parameters

| Parameter | Description | Range | Calibration |
|-----------|-------------|-------|-------------|
| P1 | Juvenile phase duration (GDD, base 9C) | 150-800 | Flexible, match panicle initiation |
| P2O | Critical photoperiod (hours) | 11-13 | Do not go below 11 without data |
| P2R | Photoperiod sensitivity (GDD/h) | 5-300 | Modern varieties: lower range |
| P5 | Grain filling duration (GDD, base 9C) | 150-850 | Match maturity date |
| G1 | Spikelet number coeff (#/g) | 50-75 | Typical: 55 |
| G2 | Single grain weight (g) | 0.015-0.030 | Low flexibility |
| G3 | Tillering coefficient | 0.7-1.3 | Relative to IR64 |
| PHINT | Phyllochron interval (GDD) | 55-90 | Default 83, need leaf data to change |

### Rice-Specific Notes
- Rice uses transplanting (PLME=T, PAGE=23 for seedling age) in the FileX
- Paddy rice needs flood irrigation management (IR011=bund height, IR009=flood depth)
- N fertilizer: typically 120-180 kg/ha in China (use NPKGRIDS for site-specific rates)
- The model does NOT have a separate .ECO file — ecotype params are in .SPE
- For double-cropping in South China, run two separate experiments (early + late)

---

## Soybean Simulation (CROPGRO / SBGRO048)

**Model**: CROPGRO-Soybean (CRGRO048 engine, SBGRO048 species files)
**Status**: Validated tool ready, Chinese cultivar library with 7 varieties
**Tool**: `tools/setup_soybean_experiment.py`

### Quick Start (Soybean)

```python
import sys
sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/DSSAT/knowledge_infrastructure/tools")
from setup_soybean_experiment import setup_soybean

# Auto-selects cultivar by latitude and maturity group
result = setup_soybean(
    lat=45.0, lon=126.0,         # Harbin, Northeast
    year=2010,
    weather_file="path/to.WTH",
    soil_id="IB00000001",
    output_dir="/tmp/dssat_soybean",
)
```

### Chinese Soybean Cultivar Table

| Code | Name | Region | MG | Plant DOY | Expected Yield (kg/ha) |
|------|------|--------|-----|-----------|----------------------|
| CN0301 | NEC MG 0 Early | Northeast (>40N) | 0 | ~130 (May 10) | 1,800-2,800 |
| CN0302 | NEC MG I Medium | Northeast | I | ~135 (May 15) | 2,000-3,000 |
| CN0303 | NEC MG II Late | Northeast | II | ~128 (May 8) | 2,200-3,200 |
| CN0311 | HHH MG III | Huang-Huai-Hai (32-40N) | III | ~165 (Jun 14) | 2,000-3,000 |
| CN0312 | HHH MG IV | Huang-Huai-Hai | IV | ~160 (Jun 9) | 2,200-3,200 |
| CN0321 | SC MG V | South (<32N) | V | ~165 (Jun 14) | 1,800-2,600 |
| CN0322 | SC MG VI | South | VI | ~170 (Jun 19) | 1,600-2,400 |

### Key CROPGRO-Soybean Parameters

| Parameter | Description | Range | Calibration |
|-----------|-------------|-------|-------------|
| CSDL | Critical short day length (h) | 11.8-14.6 | Phenology |
| PPSEN | Photoperiod sensitivity slope (1/h) | 0.13-0.39 | Phenology |
| EM-FL | Emergence to flowering (photothermal days) | 9-29 | Phenology |
| FL-SD | Flowering to first seed (photothermal days) | 11-22 | Phenology |
| SD-PM | First seed to maturity (photothermal days) | 22-38 | Phenology |
| LFMAX | Max leaf photosynthesis rate (mg CO2/m2/s) | 1.0-1.4 | Growth |
| SLAVR | Specific leaf area (cm2/g) | 300-400 | Growth |
| WTPSD | Max weight per seed (g) | 0.15-0.19 | Growth |

### Soybean-Specific Notes
- CROPGRO is a different model engine than CERES — uses photothermal time, not GDD
- Soybean is a legume: SYMBI=Y is set automatically (N fixation enabled)
- Minimal N fertilizer needed (0-30 kg/ha starter), soybean fixes its own N
- Maturity Group (MG) is the key cultivar parameter — higher MG = longer season
- HHH soybean is relay-planted after winter wheat harvest (~mid June)
- Ecotype (.ECO) file exists for soybean (SBGRO048.ECO) and must be present

---

## PlantGro.OUT Parser (Daily Growth Analysis)

**Tool**: `tools/parse_plantgro.py`
**Status**: Operational, tested on maize 10-year PlantGro.OUT

### Quick Start (PlantGro Parser)

```python
import sys
sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/DSSAT/knowledge_infrastructure/tools")
from parse_plantgro import parse_plantgro, extract_growth_summary, get_timeseries

# Parse all daily records
records = parse_plantgro("/path/to/PlantGro.OUT")

# Get summary metrics (peak LAI, phenology, stress days)
summary = extract_growth_summary(records)
for run in summary["runs"]:
    print(f"Run {run['run']}: LAI={run['peak_lai']}, "
          f"Grain={run['final_grain_kgha']} kg/ha, "
          f"Water stress days={run['total_stress_days_water']}")

# Extract time series for specific variables
ts = get_timeseries(records, ["LAID", "CWAD", "GWAD"], run_number=1)
```

### CLI Usage

```bash
# Growth summary (peak LAI, phenology dates, stress)
python tools/parse_plantgro.py /path/to/PlantGro.OUT --summary

# Export daily data to CSV
python tools/parse_plantgro.py /path/to/PlantGro.OUT --format csv --output growth.csv

# Extract specific variables
python tools/parse_plantgro.py /path/to/PlantGro.OUT --variables LAID CWAD GWAD --format json
```

### Key Output Variables

| Variable | Description | Unit | Available For |
|----------|-------------|------|---------------|
| LAID | Leaf area index | m2/m2 | All crops |
| CWAD | Total aboveground biomass | kg/ha | All crops |
| GWAD | Grain/fruit weight | kg/ha | All crops |
| HIAD | Harvest index | fraction | All crops |
| WSPD | Water stress (photosynthesis) | 0-1 | All crops |
| NSTD | Nitrogen stress | 0-1 | All crops |
| RDPD | Root depth | m | All crops |
| GSTD | Growth stage | Zadoks | CERES crops |
| DTTD | Daily thermal time | C-day | All crops |
| G#AD | Grain number | #/m2 | Cereals |
| GWGD | Individual grain weight | mg | Cereals |

### Growth Summary Output (extract_growth_summary)

Returns per run:
- `peak_lai` / `peak_lai_date` / `peak_lai_dap`
- `max_biomass_kgha`
- `final_grain_kgha` / `final_harvest_index`
- `emergence_dap` / `emergence_date`
- `anthesis_dap` / `anthesis_date`
- `maturity_dap` / `maturity_date`
- `total_stress_days_water` / `total_stress_days_nitrogen`
- `max_root_depth_m`
- `total_thermal_time`

---

## Crop Calendar Reference (China)

| Region | Latitude | Winter Wheat | Summer Maize | Rice | Soybean |
|--------|----------|-------------|-------------|------|---------|
| Northeast | >40°N | — | May-Sep | May-Oct (japonica) | May-Sep (MG 0-II) |
| North China | 35-40°N | Oct-Jun | Jun-Sep | — | Jun-Sep (MG II-III, after wheat) |
| Huang-Huai | 32-35°N | Oct-Jun | Jun-Oct | — | Jun-Oct (MG III-IV, after wheat) |
| Yangtze | 28-32°N | Nov-May | — | Apr-Oct (single indica) | Jun-Oct (MG IV-V) |
| South | <28°N | — | — | Mar-Jul, Jul-Nov (double) | Jun-Nov (MG V-VI) |

**Data sources on server:**
- GGCMI Crop Calendar: `/home/server/Crop_model_dataset/GGCMI_phase3_crop_calendar/`
- China Phenology GeoTIFF: `/home/server/Crop_model_dataset/8313530/`
- SPAM crop distribution: `/home/server/Crop_model_dataset/dataverse_files/`
