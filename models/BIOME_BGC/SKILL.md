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

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (6 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (3 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (27 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (19 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-26 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing_to_bgc.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_bgc.py --help` |
| `tools/generate_site_ini.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/generate_site_ini.py --help` |
| `tools/parse_bgc_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_bgc_output.py --help` |
| `tools/run_bgc.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_bgc.py --help` |
| `tools/run_bgc_spinup.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_bgc_spinup.py --help` |
| `tools/select_ecophysiology.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/select_ecophysiology.py --help` |

*6 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

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

## 1. Model Identity

| Property | Value |
|----------|-------|
| Full name | BIOME-BGC 4.2 |
| Version | 4.2 |
| Language | C (ANSI C89) |
| License | Copyrighted, free download from NTSG, no redistribution |
| Repository | https://www.umt.edu/numerical-terradynamic-simulation-group/project/biome-bgc.php |
| Primary domain | Terrestrial biogeochemistry |
| Spatial mode | 0-D point; gridded coverage is one execution per cell |
| Temporal mode | Daily, 365-day year |

## Bundled Example Sanity Check -- Missoula ENF

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

## 2. What This Model Does

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

## 3. Input Requirements

**Exact shapes live in `docs/format_spec.yaml`** (projected from `dag.yaml` + `diagnostics/triplets.yaml`; regenerate it, never hand-edit it). This section explains intent and traps; the spec file is the contract.

### 3.1 Meteorological Forcing

| Variable | Unit model expects | Model input format | Source dataset | Source unit | Conversion |
|----------|-------------------|--------------------|----------------|-------------|------------|
| Tmax | deg C | daily met file column 3 | CMFD/MSWX/NASA POWER or VIC-derived forcing | deg C or K | keep deg C; subtract 273.15 if K |
| Tmin | deg C | daily met file column 4 | CMFD/MSWX/NASA POWER or VIC-derived forcing | deg C or K | keep deg C; subtract 273.15 if K |
| Tday | deg C | daily met file column 5 | computed | deg C | `Tmin + 0.45*(Tmax-Tmin)` |
| prcp | cm/day | daily met file column 6 | CMFD/MSWX/NASA POWER or VIC-derived forcing | mm/day | divide by 10 |
| VPD | Pa | daily met file column 7 | computed from humidity or source VPD | kPa or Pa | multiply kPa by 1000 |
| srad | W/m2 **daylight average** (`metv.swavgfd`) | daily met file column 8 | CMFD/MSWX/NASA POWER/FLUXNET or VIC-derived forcing | W/m2 **24-h mean** | multiply by 86400/daylen (energy-conserving; done by `convert_forcing_to_bgc.py`, dt_027) |
| daylen | s | daily met file column 9 | computed from latitude and day-of-year | s | compute astronomically |
| atmospheric CO2 | ppm | constant or annual file in CO2_CONTROL | user/scenario | ppm | none |
| atmospheric N deposition | kgN/m2/yr | constant, ramped, or annual file | user/scenario | kgN/m2/yr | none |

### 3.2 Static Inputs

| Input | Source | Tool that prepares it |
|-------|--------|----------------------|
| Site latitude/elevation/soil depth | user or gridded domain metadata | `tools/generate_site_ini.py` |
| Sand/silt/clay fractions | HWSD lookup or supplied soil database | `ki_tools_common.soil_utils.lookup_hwsd`, then `tools/generate_site_ini.py` |
| Land cover / PFT | AVHRR land-cover class or explicit PFT | `tools/select_ecophysiology.py` |
| Ecophysiology parameters | PFT defaults in `lib/bgc_utils.py` or site-specific `.epc` | `tools/select_ecophysiology.py` |
| Spinup restart endpoint | BIOME-BGC spinup run | `tools/run_bgc_spinup.py` |

### 3.3 Configuration Files

| File | Format | Notes |
|------|--------|-------|
| `.ini` | keyword-section text | Sequential `scan_value()` format; generate with `tools/generate_site_ini.py`, do not hand-edit. |
| `.epc` | line-ordered ecophysiology text | PFT-specific parameter file generated by `tools/select_ecophysiology.py`. |
| `.mtc43` / met file | space-separated daily meteorological columns | 365-day years; `Tday` is required for column alignment even though the model discards it. |
| `.endpoint` | binary restart | Must be written and read by the same compatible BIOME-BGC binary. |

## 4. Build Instructions

The KI uses the compiled binary at `KISSPATH_BINARIES/biome-bgc/bgc-src/bgc`. Before any run, execute `python preflight_check.py` in this KI directory.

```bash
cd KISSPATH_BINARIES/biome-bgc/bgc-src
./bgc
```

Known build issue from `diagnostics/triplets.yaml`: `dt_001` covers modern compiler failures from C99/C11 strict mode on ANSI C89 code; use the pre-compiled binary when available.

## 5. Execution

Use the wrappers in `tools/` for generated inputs, spinup, normal execution, and parsing. A normal scientific run requires spinup first; do not cold-start production carbon-flux analysis.

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

## 6. Output Description

**Source: `dag.yaml`. If this section and the dag disagree, `dag.yaml` wins.**

**Headline output** (the dag's `validation_rank: 1` variable; the one this model is judged by):

> `daily_gpp` -- Gross primary production (sunlit + shaded canopy photosynthesis) (`kgC/m2/d`)

| Output variable (dag `var`) | rank | Emitted in | Unit | Description |
|-----------------------------|------|------------|------|-------------|
| `daily_gpp` | 1 | `.dayout` (binary, optional `.dayout.ascii`); annual summary as ann NPP/NPB text | `kgC/m2/d` | Gross primary production (sunlit + shaded canopy photosynthesis) |
| `daily_npp` | 2 | `.dayout`; annual ann NPP (`gC/m2/yr`) in text summary | `kgC/m2/d` | Terrestrial ecosystem net primary production = GPP - maintenance - growth respiration |
| `ET` | 3 | `.dayout` / annual ann ET text summary | `kgH2O/m2/d` | Evapotranspiration (Penman-Monteith): transpiration + canopy + bare-soil evaporation |
| `daily_nee` | 4 | `.dayout`; annual NBP in text summary | `kgC/m2/d` | Net ecosystem exchange = NEP - fire losses (negative = sink) |
| `daily_nep` | 5 | `.dayout` | `kgC/m2/d` | Net ecosystem production = NPP - heterotrophic respiration |
| `daily_hr` | 6 | `.dayout` | `kgC/m2/d` | Soil and litter heterotrophic (decomposition) respiration |
| `proj_lai` | 7 | `.dayout` (binary index 509); annual max LAI in text summary | `m2/m2` | Vegetation canopy projected leaf area index |
| `vegc` | 8 | `.annout` (annual index 636) | `kgC/m2` | Total vegetation carbon stock |
| `soilc` | 9 | `.annout` (annual index 638) | `kgC/m2` | Soil organic carbon stock (4 CENTURY-style SOM pools) |
| `soilw` | 10 | `.dayout` (binary index 20) | `kgH2O/m2` | Single-bucket soil water content |
| `net_nmin` | 11 | `.dayout` | `kgN/m2/d` | Soil daily net nitrogen mineralization |

Other dag outputs, in dag terms: `daily_npp`, `daily_nee`, `daily_nep`, `daily_hr`, `proj_lai`, `vegc`, `soilc`, `soilw`, `net_nmin`, `ET`.

## 7. Tool Inventory

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

## 8. Unit Conversion Table

**Critical**: this table documents the unit conversions the KI pipeline must preserve. The model-facing input units are sourced from `dag.yaml` / `docs/format_spec.yaml`, and the silent failure modes are cross-checked against `diagnostics/triplets.yaml`.

| Variable | Source unit | Model unit | Factor / operation | Type |
|----------|-------------|------------|--------------------|------|
| Precipitation (`prcp`) | `mm/day` | `cm/day` | divide by 10 | multiplicative |
| Temperature (`Tmax`, `Tmin`) | `K` when source is Kelvin | `deg C` | subtract 273.15 | additive |
| Daytime temperature (`Tday`) | `deg C` computed from Tmax/Tmin | `deg C` | `Tmin + 0.45*(Tmax-Tmin)` | derived |
| VPD | `kPa` | `Pa` | multiply by 1000 | multiplicative |
| Shortwave radiation (`srad`) | `W/m2` 24-h mean | `W/m2` daylight average | multiply by `86400 / daylen` (dt_027; `--srad_is_daylight_avg` only for MTCLIM-style input) | multiplicative, day-varying |
| Day length (`daylen`) | latitude + day-of-year | `s` | compute with `compute_daylength()` | derived |
| CO2 | `ppm` | `ppm` | no conversion; do not use mole fraction or ppb | identity |
| N deposition | `kgN/m2/yr` | `kgN/m2/yr` | no conversion | identity |
| Soil depth | `cm` if source provides centimeters | `m` | divide by 100 | multiplicative |
| Soil texture | `%` | `%` | sand + silt + clay must sum to 100 | validation |
| GPP/NPP/NEE/NEP/HR outputs | `kgC/m2/d` | `kgC/m2/d` | no conversion for dag variables | identity |
| `ET` output | `kgH2O/m2/d` | `kgH2O/m2/d` | no conversion for dag variable | identity |

### 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| `daily_gpp` | positive carbon uptake through photosynthesis, `kgC/m2/d` | negative uptake convention in some flux datasets | sign-flipped GPP skill and carbon budget |
| `daily_nee` | negative = sink, `kgC/m2/d` | positive uptake convention | source/sink verdict reverses |
| `daily_nep` | NPP - heterotrophic respiration, `kgC/m2/d` | NEE-style atmospheric exchange sign | NEP and NEE are conflated |
| `ET` | diagnostic evapotranspiration, `kgH2O/m2/d` | hydrology-owned ET in VIC | double-counting ET in water balance |
| `soilw` | single-bucket soil water content, `kgH2O/m2` | multi-layer VIC soil moisture | false layer-by-layer comparison |

**Output unit verification checklist:**
- Read `dag.yaml` before deciding what a variable means.
- Print the first 10 parsed values and check order of magnitude.
- For `daily_gpp`, verify units remain `kgC/m2/d` before comparing against tower or gridded GPP products.
- For `ET`, treat BIOME-BGC ET as diagnostic when VIC owns hydrology.
- For carbon exchange, confirm sign convention before computing bias metrics.

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

## 9. Diagnostic Triplets (Top 5)

The full corpus is `diagnostics/triplets.yaml`; check it before debugging. These are the most likely silent or fatal failures for BIOME-BGC runs:

| # | Error | Diagnosis | Remedy |
|---|-------|-----------|--------|
| 1 | `dt_007`: GPP and NPP approximately 10x higher than expected for the biome | Precipitation provided in `mm/day` instead of `cm/day` | Divide precipitation by 10 when converting from mm to cm; use `convert_forcing_to_bgc.py`. |
| 2 | `dt_008`: stomata always fully open, transpiration unrealistically high (`>10 mm/day`) | VPD provided in `kPa` instead of `Pa` | Multiply VPD by 1000 to convert kPa to Pa. |
| 3 | `dt_009`: GPP=0 every day but LAI grows normally from initial conditions | Day length column is 0, missing, or extremely small | Compute day length from latitude and day-of-year using the astronomical formula. |
| 4 | `dt_004`: model completes but fluxes have wrong magnitude or sign | Extra blank line or missing keyword shifts `.ini` parameters by one line | Regenerate `.ini` with `generate_site_ini.py`; never hand-edit. |
| 5 | `dt_012`: spinup never converges, SOC keeps increasing after 6000 model years | N deposition set to modern value instead of pre-industrial for spinup | Use pre-industrial N deposition (`0.0001-0.0002 kgN/m2/yr`) for spinup. |

## Critical Domain Knowledge

### 1. Precipitation in cm, NOT mm (dt_007)

BIOME-BGC expects precipitation in **cm/day**. CMFD/MSWX/VIC provide mm. Forgetting to divide by 10 gives 10x too much water. The model runs fine -- GPP/NPP will just be 10x too high. **This is the #1 silent error.**

### 2. VPD in Pa, NOT kPa (dt_008)

VPD must be in **Pascals** (typical: 200-4000 Pa). If provided in kPa (0.2-4.0), stomata stay fully open, transpiration is unrealistic. No error message.

### 3. Day length must be computed (dt_009)

Day length in seconds is NOT available from CMFD/MSWX. It must be computed from latitude and day-of-year using the astronomical formula in `bgc_utils.compute_daylength()`. If day length is 0, GPP will be 0.

### 3b. Shortwave is the DAYLIGHT average, not the 24-h mean (dt_027)

Met column 8 is `metv.swavgfd`, "daylight avg shortwave flux density" (`bgc_struct.h`, users guide met-file item 8; MTCLIM writes exactly that — the bundled Missoula file has ~470 W/m² in July). Every daily forcing product (CMFD/MSWX/NASA POWER/FLUXNET `SW_IN_F`, VIC 3-hourly averaged) is a 24-h mean. Feeding it unchanged delivers only daylen/86400 of the day's energy (≈0.65 in June, ≈0.3 in December at 55°N) and biases GPP/LAI/ET low by 30-60% with the seasonal timing intact. `convert_forcing_to_bgc.py` now scales by `86400/daylen`; pass `--srad_is_daylight_avg` only for MTCLIM-style input. (VPD column 7 is likewise the daylight average; FLUXNET `VPD_F` is a 24-h mean and is currently used as-is — smaller, opposite-sign effect.)

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

### 8. File paths in the .ini are length-limited — use SHORT RELATIVE paths (dt_026)

The binary copies every .ini file name into a fixed C buffer with an unbounded `fscanf("%s")`: the output prefix into `char outprefix[100]` (`pointbgc_struct.h`), met/epc/restart/co2 names into `char name[128]` (`ini.h`). An output prefix of 100+ characters (any deep absolute path) overflows **silently**: the model prints `Opened binary daily output file in write mode`, exits 0, and writes **no output files**. Always pass a short prefix relative to the run directory (e.g. `--output_prefix outputs/normal`) and run the model with `run_bgc.py --workdir <run dir>`; `generate_site_ini.py` now rejects over-long paths and `run_bgc.py` now fails when a run produced no output. The spinup restart file is exactly `sizeof(restart_data_struct)` = 584 bytes in this build (same as the bundled `restart/enf_test1.endpoint`) — a 584-byte endpoint is complete, not truncated.

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

## 10. Coupling Interfaces

### Inbound (other models -> BIOME-BGC)
- **VIC forcing** -> `convert_forcing_to_bgc.py` -> BGC met file
- **HWSD soil** -> sand/silt/clay/depth in .ini SITE section
- **AVHRR land cover** -> `select_ecophysiology.py` -> PFT + .epc

### Outbound (BIOME-BGC -> other models)
- **Cell-level GPP/NPP/NEE/SOC** -> aggregate with LDNDC for basin C budget
- **LAI time series** -> optional update to VIC vegetation parameters
- **GPP spatial field** -> compare with MODIS MOD17A2

## 11. Validated Results

### Test Site: Missoula ENF Bundled Example

| Property | Value |
|----------|-------|
| Location | Missoula MT, 46.8N |
| Elevation | 977 m |
| Period | 1950-1993 |
| Duration | 44 years |
| PFT | ENF |
| CO2 | 294.8 ppm |
| Validation status | binary_only sanity check; field pass/fail must use `docs/validation_convention.yaml` |

### Performance Metrics -- judged against the field's bar, not intuition

**Source: `docs/validation_convention.yaml`. A metric value without the field's pass-band is not a verdict. Null convention bands are written as `no cited threshold`; do not substitute guesses.**

Headline variable from `dag.yaml`: `daily_gpp` (`kgC/m2/d`), Gross primary production (sunlit + shaded canopy photosynthesis).

| Dag variable | Obs shape | Metric | Direction | Bar (convention, cited) |
|--------------|-----------|--------|-----------|--------------------------|
| `daily_gpp` | point_time_series | `nse` | maximize | satisfactory >= 0.5 (`hamm2018`) |
| `daily_gpp` | spatial_time_series | `r2` | maximize | satisfactory >= 0.5, good >= 0.7, very_good >= 0.8 (`stocker2020`) |
| `daily_gpp` | spatial_time_series | `pbias` | zero_centered | satisfactory absolute PBIAS <= 20% (`turner2006`) |
| `daily_npp` | point_time_series | `nrmse` | minimize | very_good <= 0.13, good <= 0.26, satisfactory <= 0.53 (`turner2006`) |

Other convention examples that have null bands in `docs/validation_convention.yaml` must be reported as `no cited threshold`, for example `daily_nep` point-time-series `nse`, `daily_hr` point-time-series `nse`, `vegc` `pbias`, `soilc` `pbias`, and `net_nmin` `nse`.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | Pipeline | Available | Use `load_daily_forcing` or CMFD direct reader, then `tools/convert_forcing_to_bgc.py`. |
| Soil | HWSD or supplied soil database | Available | Use `lookup_hwsd`; sand/silt/clay must sum to 100. |
| Land cover | AVHRR or explicit PFT | Available | BIOME-BGC is for natural vegetation classes 1-10. |
| Initial conditions | Spinup endpoint | Required | Multi-century spinup is mandatory for realistic NEE. |
| Validation convention | `docs/validation_convention.yaml` | Available | Per-variable metrics, directions, pass-bands, and citations. |

## 12. Parameter Selection by Region

Use these as physically informed starting points when no site-specific calibration exists; do not treat them as calibration results.

| Climate / Region | Key parameters | Rationale |
|---|---|---|
| Evergreen needleleaf forest | ENF PFT defaults; SLA 12 m2/kgC; leaf C:N 42; stomatal conductance 0.003 m/s | Matches bundled Missoula ENF example and cold/temperate forest use. |
| Deciduous broadleaf forest | DBF PFT defaults; SLA 30 m2/kgC; leaf C:N 24; stomatal conductance 0.005 m/s | Higher SLA and lower leaf C:N than ENF reflect deciduous canopy traits. |
| Grassland | C3GRASS or C4GRASS PFT defaults; SLA 45 m2/kgC; leaf C:N 24; stomatal conductance 0.005 m/s | Use C3/C4 choice by climate/ecoregion; spinup is shorter than forest. |
| Tropical natural vegetation | Prefer EBF for evergreen broadleaf tropical forest rather than temperate DBF/ENF defaults | Avoid false temperate phenology behavior and underpredicted tropical GPP. |

---

*Built using the Knowledge Dissection Toolkit v1.0 (Zhang et al., Nature, under review).*
*Part of the HydroCraft multi-model simulation platform by the Jianyun Zhang Research Group, Hohai University.*
