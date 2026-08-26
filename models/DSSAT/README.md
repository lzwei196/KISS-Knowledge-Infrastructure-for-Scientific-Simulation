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

---

# DSSAT-CSM v4.8.5 — Knowledge Infrastructure

**Model**: DSSAT-CSM (Decision Support System for Agrotechnology Transfer, Cropping System Model)
**Version**: 4.8.5, Build 41
**Domain**: Crop simulation — multi-crop growth, development, and yield
**Language**: Fortran 90
**Binary**: `KISSPATH_HOME/DSSAT/build/bin/dscsm048`
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
sys.path.insert(0, "KISSPATH_KI_ROOT/DSSAT/knowledge_infrastructure/tools")
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
KISSPATH_HOME/DSSAT/build/bin/dscsm048 B DSSBatch.v48
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

Location: `KISSPATH_HOME/DSSAT/Data/Genotype/China/`

| Crop | File | Cultivars | Key varieties |
|------|------|-----------|---------------|
| Wheat | WHCER048_China.CUL | 17 | Zhengmai9023, Jimai22, Yangmai158 |
| Maize | MZCER048_China.CUL | 12 | Zhengdan958, Xianyu335, Denghai605 |
| Rice | RICER048_China.CUL | 8 | Zhongzao39, Huanghuazhan |
| Soybean | SBGRO048_China.CUL | 5 | Zhonghuang13, Henong47 |

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
sys.path.insert(0, "KISSPATH_KI_ROOT/DSSAT/knowledge_infrastructure/tools")
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
