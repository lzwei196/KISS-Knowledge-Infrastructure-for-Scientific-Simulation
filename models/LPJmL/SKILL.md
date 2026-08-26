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
| to run the pipeline stages | `tools/` (6 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (20 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_climate_to_clm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_climate_to_clm.py --help` |
| `tools/convert_forcing_to_clm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_clm.py --help` |
| `tools/convert_soil_to_clm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_clm.py --help` |
| `tools/convert_soil_to_lpjml.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_lpjml.py --help` |
| `tools/parse_lpjml_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_lpjml_output.py --help` |
| `tools/run_lpjml.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_lpjml.py --help` |

*6 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# LPJmL v6.0.0 — Knowledge Infrastructure

**Package**: `hydrocraft-lpjml-crop` v1.0.0
**Model**: LPJmL v6.0.0 (Lund-Potsdam-Jena managed Land)
**Domain**: Crop / Dynamic Global Vegetation Model (DGVM)
**Language**: C (with optional MPI parallelization)
**Created by**: PIK (Potsdam Institute for Climate Impact Research)
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 15+ diagnostic triplets
**Validation status**: `dissected`

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/FAOSTAT/SKILL.md` for crop yield observations.
See `data_ki/SPAM/SKILL.md` for gridded yield data.


## Overview

LPJmL (Lund-Potsdam-Jena managed Land) is a process-based dynamic global vegetation model that simulates vegetation dynamics, carbon and nitrogen cycling, hydrology, and crop yields on a global 0.5-degree grid. It integrates natural vegetation, managed grasslands, and 12+ crop functional types (CFTs) including temperate cereals, rice, maize, tropical cereals, pulses, roots, oil crops, and sugarcane.

**What LPJmL simulates**:
- Carbon cycle: GPP, NPP, autotrophic/heterotrophic respiration, soil/vegetation/litter carbon pools
- Nitrogen cycle: N deposition, fertilizer/manure application, BNF, leaching, denitrification, N2O emissions
- Hydrology: Evapotranspiration, runoff, river routing, discharge, irrigation water demand/supply, reservoirs
- Crop yields: Sowing dates, phenological heat units (PHU), harvest carbon, growing season length
- Vegetation dynamics: Establishment, mortality, fire disturbance, land-use change, timber harvest
- Permafrost, methane dynamics, wetlands, lake evaporation, snow

**Key difference from other crop models**: LPJmL is a fully coupled DGVM + crop model with C-N-water cycling and global river routing. It is NOT a field-scale crop model. Each grid cell (0.5 deg, ~55km) simulates multiple stand types (natural, cropland, grassland, biomass plantations) simultaneously.

---

## Installation

### Dependencies (Ubuntu/Debian)

```bash
sudo apt-get install libnetcdf-dev libudunits2-dev libjson-c-dev
# Optional for parallel runs:
sudo apt-get install mpich
```

### Build from source

```bash
cd /path/to/LPJmL
./configure.sh          # Detects OS, compiler, MPI availability
make                    # Builds bin/lpjml
make utils              # Builds 40+ utility programs
make test               # Creates output/ and restart/ directories
```

### Compilation flags (Makefile.inc LPJFLAGS)

| Flag | Description |
|------|-------------|
| `USE_NETCDF` | Enable NetCDF input/output |
| `USE_UDUNITS` | Enable unit conversion in NetCDF |
| `USE_MPI` | Build parallel MPI version |
| `CHECK_BALANCE` | Enable C/N/water balance checks |
| `SAFE` | Enable additional runtime safety checks |
| `WITH_FPE` | Enable floating-point exception traps |
| `DEBUG` | Generate diagnostic output |

### Binary

```
bin/lpjml    — Main simulation executable
bin/lpjcheck — Configuration file syntax checker
```

### Environment variables

| Variable | Purpose |
|----------|---------|
| `LPJROOT` | Root installation directory |
| `LPJINPATH` | Prepended to relative input file paths |
| `LPJOPTIONS` | CPP runtime options |
| `LPJOUTPATH` | Prepended to relative output file paths |
| `LPJRESTARTPATH` | Prepended to relative restart file paths |

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 1 | Climate forcing | `convert_climate_to_clm` | Convert global climate data (GSWP3-W5E5, CRU) to CLM binary format |
| 2 | Soil parameters | `convert_soil_to_lpjml` | Convert HWSD/soil texture data to LPJmL 13-type soil classification |
| 3 | Land-use input | (manual/LandInG) | Prepare CFT fractions, fertilizer, manure, sowing dates |
| 4 | Configuration | `lpjml_config.cjson` | Set simulation parameters (spinup, period, outputs) |
| 5 | Spinup | `run_lpjml` | Run ~4000yr natural vegetation spinup (equilsoil), write restart |
| 6 | Transient run | `run_lpjml` | Run with land use from restart, 1901-2019 |
| 7 | Output analysis | `parse_lpjml_output` | Extract binary/NetCDF outputs to CSV, compute yield metrics |

### Two-step simulation protocol

LPJmL requires a **two-step simulation**:
1. **Spinup** (natural vegetation): ~4000 years, cycling 30-year climate, creates equilibrium soil carbon and vegetation. Writes restart file at year 1700.
2. **Transient** (with land use): Reads restart, runs from 1901 to present with historical land use, fertilizer, CO2.

This is controlled by the `FROM_RESTART` preprocessor macro in `lpjml_config.cjson`.

---

## Input Data Reference

### Climate forcing (daily or monthly)

| Variable | CLM ID | Unit | Source |
|----------|--------|------|--------|
| `temp` | 1 | deg C | Mean daily temperature |
| `prec` | 2 | mm/day (daily) or mm/month (monthly) | Precipitation |
| `swdown` | 3 | W/m2 | Shortwave downward radiation |
| `lwnet` | 4 | W/m2 | Net longwave radiation |
| `tmin` | 9 | deg C | Daily minimum temperature |
| `tmax` | 10 | deg C | Daily maximum temperature |
| `tamp` | 11 | deg C | Diurnal temperature range (for CRU) |
| `wetdays` | 12 | days/month | Wet days (for CRU random precip) |
| `humid` | 14 | kg/kg | Specific humidity |
| `wind` | 15 | m/s | Wind speed |

### Static inputs

| Variable | CLM ID | Unit | Description |
|----------|--------|------|-------------|
| `soil` | 41 | code (1-13) | Soil texture class |
| `coord` | 43 | degrees | Grid cell coordinates |
| `landfrac` | 44 | fraction | Land fraction per cell |
| `countrycode` | 45 | code | Country code |
| `soilpH` | 46 | pH | Soil pH |
| `co2` | 5 | ppm | Annual atmospheric CO2 concentration |
| `elevation` | 39 | m | Surface elevation |
| `drainage` | 37 | index | River routing drainage direction |
| `lakes` | 36 | fraction | Lake fraction |
| `reservoir` | 40 | various | Reservoir info (capacity, year, etc.) |

### Land use inputs

| Variable | CLM ID | Unit | Description |
|----------|--------|------|-------------|
| `landuse` | 6 | fraction | CFT fractions (64 bands: 16 rainfed + 16 irrigated + irrigation systems) |
| `fertilizer_nr` | 18 | gN/m2/yr | N fertilizer application rate per CFT |
| `manure_nr` | 19 | gN/m2/yr | Manure N application rate per CFT |
| `sdate` | 25 | DOY | Prescribed sowing dates per CFT |
| `crop_phu` | 26 | deg C days | Phenological heat units per CFT |
| `with_tillage` | 7 | binary | Tillage practice |
| `residue_on_field` | 8 | fraction | Fraction of residues left on field |

---

## Output Variables (key crop-related)

| Output ID | Variable | Unit | Timestep | Description |
|-----------|----------|------|----------|-------------|
| `harvestc` | Harvest carbon | gC/m2/yr | annual | Total harvested carbon |
| `pft_harvestc` | PFT harvest C | gC/m2/yr | annual | CFT-specific harvested carbon (excl. residuals) |
| `pft_rharvestc` | PFT residual C | gC/m2/yr | annual | Harvested residual carbon |
| `sdate` | Sowing date | DOY | annual | Actual sowing date |
| `hdate` | Harvest date | DOY | annual | Actual harvest date |
| `growing_period` | Growing period | days | annual | Growing season length |
| `cftfrac` | CFT fraction | fraction | annual | Crop functional type area fraction |
| `npp` | NPP | gC/m2/month | monthly | Net primary production |
| `gpp` | GPP | gC/m2/month | monthly | Gross primary production |
| `runoff` | Runoff | mm/month | monthly | Total runoff |
| `discharge` | Discharge | hm3/day | monthly | River discharge |
| `transp` | Transpiration | mm/month | monthly | Transpiration |
| `evap` | Evaporation | mm/month | monthly | Evaporation |
| `irrig` | Irrigation | mm/month | monthly | Irrigation water applied |
| `vegc` | Vegetation C | gC/m2 | annual | Vegetation carbon stock |
| `soilc` | Soil C | gC/m2 | annual | Soil organic carbon stock |

### Converting harvest carbon to yield

LPJmL outputs crop yield as **carbon** (gC/m2). To convert to dry matter yield:
```
yield_DM (g/m2) = harvestc (gC/m2) / 0.45
yield_DM (t/ha) = harvestc (gC/m2) / 0.45 * 0.01
```
Where 0.45 is the carbon fraction of dry biomass (`biomass2c` in units.h).

---

## 6. Output Description

This section restates `dag.yaml`; the dag is the source of truth for output identity, units,
descriptions, and validation ranking. If this section and `dag.yaml` disagree, `dag.yaml` wins.

**Headline output** (`validation_rank: 1`):

> `discharge` — River discharge at the cell, produced by lateral routing through the drainage network. (`hm3/day`)

| Output variable (dag `var`) | Rank | Unit | Description |
|-----------------------------|------|------|-------------|
| `discharge` | 1 | `hm3/day` | River discharge at the cell, produced by lateral routing through the drainage network. |

Other dag outputs recorded for this KI:

| Output variable (dag `var`) |
|-----------------------------|
| `pft_harvestc` |
| `npp` |
| `gpp` |
| `runoff` |
| `transp` |
| `vegc` |
| `soilc` |

---

## Soil Types (13 classes)

LPJmL uses a simplified 13-class soil texture scheme based on USDA classification:

| Code | Name | Ks (mm/h) | Sand% | Silt% | Clay% | w_pwp | w_fc | w_sat |
|------|------|-----------|-------|-------|-------|-------|------|-------|
| 1 | Clay | 3.5 | 22 | 24 | 54 | 0.284 | 0.398 | 0.468 |
| 2 | Silty clay | 4.8 | 6 | 47 | 47 | 0.259 | 0.378 | 0.468 |
| 3 | Sandy clay | 26.0 | 52 | 6 | 42 | 0.205 | 0.295 | 0.406 |
| 4 | Clay loam | 8.8 | 32 | 34 | 34 | 0.214 | 0.345 | 0.465 |
| 5 | Silty clay loam | 7.3 | 10 | 56 | 34 | 0.247 | 0.387 | 0.464 |
| 6 | Sandy clay loam | 16.0 | 58 | 15 | 27 | 0.143 | 0.256 | 0.404 |
| 7 | Loam | 12.2 | 43 | 39 | 18 | 0.139 | 0.292 | 0.439 |
| 8 | Silt loam | 10.1 | 17 | 70 | 13 | 0.177 | 0.368 | 0.476 |
| 9 | Sandy loam | 18.8 | 58 | 32 | 10 | 0.100 | 0.228 | 0.434 |
| 10 | Silt | 10.1 | 10 | 60 | 30 | 0.177 | 0.368 | 0.476 |
| 11 | Loamy sand | 50.7 | 82 | 12 | 6 | 0.060 | 0.149 | 0.421 |
| 12 | Sand | 167.8 | 92 | 5 | 3 | 0.022 | 0.088 | 0.339 |
| 13 | Rock and ice | 0.1 | 99 | 0 | 1 | 0.001 | 0.05 | 0.08 |

---

## CLM File Format

LPJmL uses its own binary file format called **CLM** (Climate data for LPJmL):

### Header structure (CLM version 3/4)

| Field | Type | Description |
|-------|------|-------------|
| Header ID | char[7] | "LPJCLIM" or similar |
| Version | int | 3 or 4 |
| Order | int | Data ordering (1=cellindex, 2=yearcell, etc.) |
| Firstyear | int | First year in file |
| Nyear | int | Number of years |
| Firstcell | int | Index of first cell |
| Ncell | int | Number of grid cells |
| Nbands | int | Number of bands/variables |
| Cellsize_lon | float | Longitude resolution (typically 0.5) |
| Cellsize_lat | float | Latitude resolution (typically 0.5) |
| Datatype | int | 0=byte, 1=short, 2=int, 3=float, 4=double |
| Scalar | float | Scale factor |
| Nstep | int | Time steps per year (12=monthly, 365=daily) |

### Utility programs for CLM files

| Program | Purpose |
|---------|---------|
| `cru2clm` | Convert CRU data to CLM format |
| `cdf2clm` | Convert NetCDF to CLM |
| `clm2cdf` | Convert CLM to NetCDF |
| `printclm` | Print CLM file contents |
| `statclm` | Print statistics of CLM files |
| `catclm` | Concatenate CLM files |
| `cutclm` | Cut CLM files |
| `setclm` | Modify CLM header values |
| `bin2cdf` | Convert raw binary output to NetCDF |

---

## Unit Conversion Traps

| Trap | Source Unit | LPJmL Unit | Conversion | Impact if wrong |
|------|-----------|------------|------------|-----------------|
| Temperature | K | deg C | T_C = T_K - 273.15 | Photosynthesis failure, wrong phenology |
| Precipitation | kg/m2/s | mm/day | P * 86400 | Extreme drought or flood |
| Shortwave radiation | J/m2/day | W/m2 | SW / 86400 | Wrong GPP magnitude |
| CO2 concentration | mol/mol | ppm | CO2 * 1e6 | Wrong CO2 fertilization effect |
| Harvest C to yield | gC/m2 | t DM/ha | / 0.45 * 0.01 | Wrong yield values |
| Fertilizer | kg N/ha | gN/m2 | / 10.0 | 10x over/under-fertilization |
| Wind speed | km/h | m/s | / 3.6 | Wrong PET, fire spread |
| Specific humidity | g/kg | kg/kg | / 1000 | Wrong VPD, transpiration |
| Soil depth | cm | mm | * 10 | Wrong water holding capacity |
| Longitude/latitude | radians | degrees | * 180/pi | Grid mismatch |

---

## Configuration File Structure (lpjml_config.cjson)

The configuration file is a JSON file with C preprocessor directives. It has five sections:

1. **Simulation description**: `sim_name`, `sim_id`, `version`, model switches (fire, nitrogen, permafrost, etc.)
2. **Input parameters**: Includes PFT, soil, hydro, management parameter files from `par/` directory
3. **Input data**: Paths to all forcing, land use, and static input files
4. **Output data**: List of output variables to write, format, paths
5. **Run settings**: `startgrid`/`endgrid`, spinup years, first/last year, restart settings

### Key simulation switches

| Switch | Options | Description |
|--------|---------|-------------|
| `landuse` | "no", "yes", "const", "all_crops" | Land use mode |
| `irrigation` | "no", "lim", "pot", "all" | Irrigation mode |
| `with_nitrogen` | "lim", "unlim" | Nitrogen limitation |
| `fire` | "no_fire", "fire", "spitfire" | Fire module |
| `sowing_date_option` | "no_fixed_sdate", "fixed_sdate", "prescribed_sdate" | Sowing date handling |
| `crop_phu_option` | "bondeau2017", "prescribed" | PHU calculation |
| `fertilizer_input` | "no", "yes", "auto" | Fertilizer handling |
| `equilsoil` | true/false | Soil carbon equilibration |
| `river_routing` | true/false | Enable river routing |
| `reservoir` | true/false | Enable reservoir operations |

---

## Running LPJmL

### Basic execution

```bash
# Sequential
./bin/lpjml lpjml_config.cjson

# With preprocessor macros (spinup, then transient)
./bin/lpjml -DFROM_RESTART lpjml_config.cjson

# Parallel (MPI)
mpirun -np 32 ./bin/lpjml lpjml_config.cjson
```

### Runtime options

| Option | Description |
|--------|-------------|
| `-Dmacro=value` | Define preprocessor macro |
| `-Ipath` | Add include path |
| `-v` | Print version and compile flags |
| `-vv` | Verbose configuration reading |
| `-pedantic` | Stop on warnings |
| `-inpath dir` | Set input directory |
| `-outpath dir` | Set output directory |
| `-restartpath dir` | Set restart directory |

### Typical workflow

```bash
# Step 1: Configure
./configure.sh
make

# Step 2: Create output directories
make test

# Step 3: Run spinup (natural vegetation, ~4000 years)
./bin/lpjml lpjml_config.cjson

# Step 4: Run transient (with land use, from restart)
./bin/lpjml -DFROM_RESTART lpjml_config.cjson
```

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_climate_to_clm` | s1 | `tools/convert_climate_to_clm.py` | Convert NetCDF climate to CLM binary |
| `convert_soil_to_lpjml` | s2 | `tools/convert_soil_to_lpjml.py` | Convert HWSD soil data to LPJmL codes |
| `run_lpjml` | s5-s6 | `tools/run_lpjml.py` | Execute LPJmL with preflight checks |
| `parse_lpjml_output` | s7 | `tools/parse_lpjml_output.py` | Parse binary output to CSV |

---

## 11. Validated Results

This section restates `docs/validation_convention.yaml`; the convention file is the source of
truth for metric choice, direction, cited pass-bands, and verdicts. A model run should be judged
against these bars rather than against intuition. No achieved run score is stated here unless it
is produced by the KI's validation workflow.

### Convention Bars

| Dag variable | Metric | Direction | Very good band | Good band | Satisfactory band |
|--------------|--------|-----------|----------------|-----------|-------------------|
| `pft_harvestc` | `nrmse` | minimize | no cited threshold (`li2021crop`) | no cited threshold (`li2021crop`) | `10.0` (`li2021crop`) |
| `npp` | `nmse` | minimize | no cited threshold (`schaphoff2018eval`, `kelley2012benchmark`) | no cited threshold (`schaphoff2018eval`, `kelley2012benchmark`) | `1.0` (`schaphoff2018eval`, `kelley2012benchmark`) |

### Current Validation State

| Item | Status | Source |
|------|--------|--------|
| Headline dag output | `discharge`, `hm3/day` | `dag.yaml` |
| Headline output description | River discharge at the cell, produced by lateral routing through the drainage network. | `dag.yaml` |
| Other dag outputs | `pft_harvestc`, `npp`, `gpp`, `runoff`, `transp`, `vegc`, `soilc` | `dag.yaml` |
| Stated convention bars | `pft_harvestc`, `npp` | `docs/validation_convention.yaml` |
| Achieved validation metrics | Not stated in this body; produce them with the KI validation workflow before assigning a verdict. | validation workflow |

---

## Error Codes

| Code | Description | Type |
|------|-------------|------|
| 1 | Error reading configuration | External |
| 2 | Error initializing input data | External |
| 3 | Error initializing grid | External |
| 4 | Invalid carbon balance | Internal |
| 5 | Invalid water balance | Internal |
| 6 | Negative discharge | Internal |
| 9 | Error allocating memory | External |
| 15 | Invalid year in getco2() | External |
| 37 | Invalid nitrogen balance | Internal |
| 38 | Invalid climate data | External |

---

## PFT/CFT Reference

### Natural PFTs (9 types)
1. Tropical broadleaved evergreen tree
2. Tropical broadleaved raingreen tree
3. Temperate needleleaved evergreen tree
4. Temperate broadleaved evergreen tree
5. Temperate broadleaved summergreen tree
6. Boreal needleleaved evergreen tree
7. Boreal broadleaved summergreen tree
8. Boreal needleleaved summergreen tree
9. C4 grass, C3 grass (temperate + polar)

### Crop Functional Types (12 CFTs)
1. Temperate cereals (wheat)
2. Rice
3. Maize
4. Tropical cereals (millet/sorghum)
5. Pulses
6. Temperate roots (potato/sugar beet)
7. Tropical roots (cassava)
8. Oil crops sunflower
9. Oil crops soybean
10. Oil crops groundnut
11. Oil crops rapeseed
12. Sugarcane

Each CFT has rainfed and irrigated variants in the land-use input (total 64 bands in landuse file: 16 CFTs x 2 water management x 2 irrigation systems).
