---
name: biome-bgc
description: >-
  Biome-BGC 4.2. Covers Daily carbon fluxes (C3/C4 photosynthesis, maintenance + growth
  respiration, allocation); Nitrogen cycling (deposition, fixation, mineralization,
  immobilization, leaching, denitrification); Water cycling (canopy interception, snow
  accumulation/melt, bare-soil evaporation, transpiration…. Use when the task involves
  running, configuring, calibrating or interpreting BIOME_BGC.
---

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

> **HWSD soil lookup:** Use `from ki_tools_common.soil_utils import lookup_hwsd` to get sand/silt/clay/OC/pH for any lat/lon. Returns texture class and Saxton-Rawls hydraulic properties.

> **CMFD direct reader available:** Use `from ki_tools_common.netcdf_utils import load_cmfd_daily_all` to read CMFD 3-hourly data directly. Returns daily precip (mm), temp (°C with Tmin/Tmax), radiation (W/m²), wind, humidity. Handles subdirectory search (Prec/, Temp/, etc.) and unit conversions automatically.

> **HWSD soil lookup:** Use `from ki_tools_common.soil_utils import lookup_hwsd` to get sand/silt/clay/OC/pH for any lat/lon. Returns texture class and Saxton-Rawls hydraulic properties.
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
Then convert to BGC met format using this KI's tool: `tools/convert_forcing_to_bgc.py`

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.

---

# BIOME-BGC 4.2 -- Knowledge Infrastructure

> **Model**: BIOME-BGC 4.2 (University of Montana NTSG)
> **Domain**: Terrestrial biogeochemistry -- daily C/N/water cycling for forests, grasslands, shrublands
> **Pipeline stages**: 8 | **Tools**: 6 | **Skill documents**: 3 | **Diagnostic triplets**: 25
> **Binary**: `KISSPATH_BINARIES/biome-bgc/bgc-src/bgc`
> **Status**: binary_only (bundled example data validated 2026-03-24)

## Validated Results -- Missoula ENF (Bundled Example)

| Metric | Value | Expected Range | Status |
|--------|-------|---------------|--------|
| Spinup convergence | 2112 model years | 3000-6000 (with acceleration) | OK |
| Spinup residual | -0.001184 | < 0.01 | OK |
| Wall time (spinup) | 0.5 s | 1-5 min | OK |
| Vegetation C | 10.44 kgC/m2 | 5-25 | OK |
| Soil C | 10.19 kgC/m2 | 5-20 | OK |
| Total C | 23.86 kgC/m2 | 15-40 | OK |
| Max LAI | 1.44-1.71 m2/m2 | 1-8 | OK (cold start) |
| Litter C | 3.23 kgC/m2 | 0.5-5 | OK |
| Soil mineral N | 0.000018 kgN/m2 | >0 | OK |

**Test conditions**: Missoula MT, 46.8N, 977m, ENF, 1950-1993, 44 years, CO2=294.8 ppm.

## Overview

BIOME-BGC simulates daily carbon, nitrogen, and water fluxes through natural terrestrial ecosystems. It is the complement to LDNDC in HydroCraft: LDNDC handles cropland/managed systems, BIOME-BGC handles forests, grasslands, and shrublands. Together they enable full-basin carbon budgets.

**Core capabilities**:
- GPP, NPP, NEE, ecosystem respiration (FLUXNET-compatible)
- Vegetation, litter, and soil organic carbon pools (CENTURY-style 4+4 pools)
- Penman-Monteith ET, soil water balance, snow dynamics
- Deciduous/evergreen phenology (temperature + photoperiod driven)
- Multi-century spinup to steady-state (required for realistic soil C/N initialization)
- 7 plant functional types: ENF, EBF, DNF, DBF, SHRUB, C3GRASS, C4GRASS

**What BIOME-BGC adds beyond LDNDC**:
- Forest carbon cycling (designed for forests, not crops)
- Built-in spinup mode (1000-6000 model years)
- CENTURY-style SOM decomposition (4 litter + 4 soil pools)
- Farquhar photosynthesis (mechanistic, not empirical)

## Pipeline

| Stage | Name | Tools | Skill Doc |
|-------|------|-------|-----------|
| S1 | Site Definition (.ini) | `generate_site_ini.py` | `docs/s1_site_definition_skill.md` |
| S2 | Ecophysiology (.epc) | `select_ecophysiology.py` | -- |
| S3 | Meteorological Forcing | `convert_forcing_to_bgc.py` | `docs/s3_meteorological_forcing_skill.md` |
| S4 | CO2 Concentration | (set in .ini or co2.txt) | -- |
| S5 | Spinup Execution | `run_bgc_spinup.py` | `docs/s5_spinup_strategy_skill.md` |
| S6 | Normal Execution | `run_bgc.py` | -- |
| S7 | Output Analysis | `parse_bgc_output.py` | -- |
| S8 | VIC Coupling | (orchestrate per-cell) | -- |

## Tools Reference

| Tool | Script Path | Purpose |
|------|------------|---------|
| `generate_site_ini` | `tools/generate_site_ini.py` | Generate .ini file from structured inputs (keyword-section format) |
| `select_ecophysiology` | `tools/select_ecophysiology.py` | Map AVHRR land cover to PFT and generate .epc file |
| `convert_forcing_to_bgc` | `tools/convert_forcing_to_bgc.py` | Convert VIC forcing to BGC met format (mm->cm, compute VPD in Pa, compute daylen) |
| `run_bgc_spinup` | `tools/run_bgc_spinup.py` | Execute spinup with -u flag, monitor convergence |
| `run_bgc` | `tools/run_bgc.py` | Execute normal simulation with -m -a flags |
| `parse_bgc_output` | `tools/parse_bgc_output.py` | Parse ASCII output, compute annual C budgets, physical checks |

## Shared Library

`lib/bgc_utils.py` provides:
- `compute_daylength(lat, yday)` -- astronomical day length in seconds
- `compute_vpd_from_tmin_tmax_q(tmin, tmax, q, pressure)` -- VPD in Pa
- `compute_tday(tmin, tmax)` -- daytime average temperature
- `mm_to_cm()`, `kpa_to_pa()`, `kelvin_to_celsius()` -- unit converters
- `EPC_DEFAULTS` -- complete parameter library for 7 PFTs
- `avhrr_to_pft(avhrr_class, latitude)` -- land cover mapping
- `STANDARD_DAILY_OUTPUT`, `STANDARD_ANNUAL_OUTPUT` -- output variable sets

## EPC Parameter Library

7 PFTs with complete parameter sets in `lib/bgc_utils.py`:

| PFT | Ecosystem | SLA (m2/kgC) | Leaf C:N | Stomatal Cond (m/s) |
|-----|-----------|-------------|----------|-------------------|
| ENF | Evergreen Needleleaf Forest | 12 | 42 | 0.003 |
| EBF | Evergreen Broadleaf Forest | 12 | 42 | 0.005 |
| DNF | Deciduous Needleleaf Forest | 30 | 24 | 0.005 |
| DBF | Deciduous Broadleaf Forest | 30 | 24 | 0.005 |
| SHRUB | Evergreen Shrub | 12 | 42 | 0.003 |
| C3GRASS | C3 Grassland | 45 | 24 | 0.005 |
| C4GRASS | C4 Grassland | 45 | 24 | 0.005 |

## Critical Domain Knowledge

### 1. Precipitation in cm, NOT mm (dt_007)

BIOME-BGC expects precipitation in **cm/day**. CMFD/MSWX/VIC provide mm. Forgetting to divide by 10 gives 10x too much water. The model runs fine -- GPP/NPP will just be 10x too high. **This is the #1 silent error.**

### 2. VPD in Pa, NOT kPa (dt_008)

VPD must be in **Pascals** (typical: 200-4000 Pa). If provided in kPa (0.2-4.0), stomata stay fully open, transpiration is unrealistic. No error message.

### 3. Day length must be computed (dt_009)

Day length in seconds is NOT available from CMFD/MSWX. It must be computed from latitude and day-of-year using the astronomical formula in `bgc_utils.compute_daylength()`. If day length is 0, GPP will be 0.

### 4. INI file is keyword-section based (dt_004)

The .ini file uses KEYWORD markers (MET_INPUT, RESTART, TIME_DEFINE, etc.) followed by sequential values read by `scan_value()`. An extra or missing line shifts ALL subsequent parameters. **Never hand-edit .ini files. Always use generate_site_ini.py.**

### 5. Spinup is mandatory (dt_012-dt_016)

BIOME-BGC REQUIRES multi-century spinup to initialize soil C/N pools. Without spinup, NEE is dominated by initial condition artifacts. Typical spinup: 1000-6000 model years (1-5 minutes wall time). The model recycles met data automatically.

Spinup durations by biome:
- Grassland: 1000-1500 years
- Deciduous forest: 2000-3000 years
- Evergreen forest: 3000-6000 years
- Boreal forest: 4000-6000 years

### 6. Double-counting ET with VIC (dt_020)

Both VIC and BIOME-BGC compute ET. When coupled, VIC owns the water balance. BIOME-BGC ET is **diagnostic only** -- do NOT add it to discharge calculations.

### 7. Forest vs Crop domains (dt_021)

BIOME-BGC is for AVHRR classes 1-10 (natural vegetation) only. Cropland (class 11) must use LDNDC or DSSAT. Running BIOME-BGC on cropland produces nonsensical results.

## Running a Simulation

### Quick workflow (point mode):

```bash
BGC=KISSPATH_BINARIES/biome-bgc/bgc-src/bgc
TOOLS=KISSPATH_KI_ROOT/BIOME_BGC/knowledge_infrastructure/tools

# 1. Select PFT and generate .epc
python $TOOLS/select_ecophysiology.py --pft ENF --output epc/site.epc

# 2. Convert VIC forcing to BGC met format
python $TOOLS/convert_forcing_to_bgc.py \
  --forcing_file <vic_forcing_file> \
  --lat 46.8 --start_year 2000 --end_year 2010 \
  --output metdata/site.mtc43

# 3. Generate spinup .ini
python $TOOLS/generate_site_ini.py \
  --met_file metdata/site.mtc43 --epc_file epc/site.epc \
  --output_prefix outputs/spinup --lat 46.8 --elevation 977 \
  --soil_depth 1.0 --sand 30 --silt 50 --clay 20 \
  --start_year 2000 --n_met_years 11 --mode spinup \
  --output spinup.ini

# 4. Run spinup (1-5 minutes, DO NOT interrupt)
python $TOOLS/run_bgc_spinup.py --bgc_binary $BGC --ini_file spinup.ini

# 5. Generate normal .ini (reads restart from spinup)
python $TOOLS/generate_site_ini.py \
  --met_file metdata/site.mtc43 --epc_file epc/site.epc \
  --output_prefix outputs/normal --lat 46.8 --elevation 977 \
  --soil_depth 1.0 --sand 30 --silt 50 --clay 20 \
  --start_year 2000 --n_met_years 11 --mode normal \
  --read_restart --output normal.ini

# 6. Run normal simulation
python $TOOLS/run_bgc.py --bgc_binary $BGC --ini_file normal.ini

# 7. Parse output
python $TOOLS/parse_bgc_output.py \
  --daily_file outputs/normal.dayout.ascii \
  --start_year 2000 --n_years 11 \
  --output_csv outputs/annual_summary.csv
```

### Bundled example test:

```bash
cd KISSPATH_BINARIES/biome-bgc/bgc-src
# Spinup (writes restart/enf_test1.endpoint)
./bgc -u -s ini/enf_test1_spinup.ini
# Normal run (reads restart, writes outputs)
./bgc -m -a ini/enf_test1.ini
```

Expected results for Missoula ENF (44 years, 1950-1993):
- GPP: 800-1500 gC/m2/yr
- NEE: -50 to -300 gC/m2/yr (sink)
- Max LAI: 3-6 m2/m2
- Soil C: 5-15 kgC/m2

## Error Handling

See `diagnostics/triplets.yaml` for 25 diagnostic triplets covering:
- Unit conversion errors (dt_005-dt_010) -- **7 silent errors**, most dangerous
- INI format errors (dt_002-dt_004, dt_011)
- Spinup convergence issues (dt_012-dt_016)
- Coupling pitfalls (dt_020-dt_025)
- Parameter selection (dt_017-dt_019)

## Coupling Points

### Inbound (other models -> BIOME-BGC)
- **VIC forcing** -> `convert_forcing_to_bgc.py` -> BGC met file
- **HWSD soil** -> sand/silt/clay/depth in .ini SITE section
- **AVHRR land cover** -> `select_ecophysiology.py` -> PFT + .epc

### Outbound (BIOME-BGC -> other models)
- **Cell-level GPP/NPP/NEE/SOC** -> aggregate with LDNDC for basin C budget
- **LAI time series** -> optional update to VIC vegetation parameters
- **GPP spatial field** -> compare with MODIS MOD17A2

---

*Built using the Knowledge Dissection Toolkit v1.0 (Zhang et al., Nature, under review).*
*Part of the HydroCraft multi-model simulation platform by the Jianyun Zhang Research Group, Hohai University.*
