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
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (22 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (21 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing_to_ef5.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_ef5.py --help` |
| `tools/convert_params_to_ef5.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_params_to_ef5.py --help` |
| `tools/parse_ef5_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_ef5_output.py --help` |
| `tools/prepare_basic_grids.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/prepare_basic_grids.py --help` |
| `tools/run_ef5.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_ef5.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# EF5 v1.2.3 (Ensemble Framework For Flash Flood Forecasting) — Knowledge Infrastructure

**Package**: `hydrocraft-ef5-flash-flood` v1.1.0
**Model**: EF5 v1.2.3
**KDT version**: 5.1.2 (uses `ki_tools_common` for forcing/metrics/cross-platform)
**Created by**: HyDROSLab, University of Oklahoma (Zac Flamig, Humberto Vergara, Race Clark, JJ Gourley, Yang Hong)
**Last updated**: 2026-04-28 (added Stage-1 `prepare_basic_grids` tool; corrected `ef5 -p` documentation)
**Stats**: 5 tools | 6 skill documents | 22 diagnostic triplets | ~1,600 lines of validated Python
**Validation status**: `source_dissected` (binary executes end-to-end at any prepared site; obs validation requires hourly TIMESTEP — see s5_execution.md)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## Overview

This knowledge infrastructure enables autonomous distributed hydrologic simulation using EF5 (Ensemble Framework For Flash Flood Forecasting). EF5 is a C++ framework for distributed hydrologic modeling designed for flash flood forecasting at continental scales with rapid update cycles.

**What EF5 does**: Distributed gridded hydrologic modeling framework. Supports:
- **Water balance models**: CREST, SAC-SMA, HyMOD, HP (Hydrophobic)
- **Routing models**: Linear Reservoir (LR), Kinematic Wave (KW)
- **Snow melt**: Snow-17 (temperature-index)
- **Inundation**: Simple Inundation, VC Inundation
- **Calibration**: DREAM (DiffeRential Evolution Adaptive Metropolis), ARS
- **Ensemble**: Multi-model ensemble task support
- **DEM processing**: Built-in flow direction and accumulation computation

**Key design**: EF5 couples any water balance model with any routing model via a single configuration file (`control.txt`). Forcing data (precipitation, PET, temperature) are ingested as gridded files (ASC, BIF, TIF, TRMM, MRMS). Output is streamflow time series at gauge points and optional gridded fields (streamflow, soil moisture, SWE, return period, inundation depth).

**Execution**: `ef5 [control.txt]` — single binary, single config file, no external runtime dependencies.

---

## Installation

### Build from source (Linux)

```bash
# Dependencies
sudo apt-get install libgeotiff-dev libtiff-dev zlib1g-dev g++ automake autoconf

# Build
cd source/repo
autoreconf --force --install
./configure
make CXXFLAGS="-O3 -fopenmp"
# Binary: bin/ef5
```

### Dependencies

```
libz         — zlib compression (for gzipped TRMM files)
libtiff      — TIFF raster I/O
libgeotiff   — GeoTIFF spatial metadata
libgomp      — OpenMP parallel processing (Linux)
```

### DEM processing

Use the KI's Stage-1 tool to derive DEM/DDM/FAM from a raw DEM:
```bash
python tools/prepare_basic_grids.py --dem raw_DEM.tif --out-dir basin/grids/ \
    --method breach --out-format asc --expected-outlet 117.35 33.05
```
Wraps WhiteboxTools (BreachDepressionsLeastCost → D8Pointer ESRI → D8FlowAccumulation
cells) and writes ESRIDDM-encoded DDM with SELFFAM=true convention. See
`docs/s1_basic_grids.md` for the full procedure.

EF5 v1.2.3's argument parser also accepts `-p` and `-s` flags, but only `-s`
(recompute FAM from existing DDM) is implemented — `-p` (pit-fill + D8 from
scratch) is in the parser but `ProcessDEM(mode=1)` falls through silently
(verified at `src/DEMProcessor.cpp:23`). **Do not use `ef5 -p`. Use
`prepare_basic_grids.py`.**

```bash
# Recompute FAM from a known-good DDM (rare; only useful for re-prepping)
ef5 -z DEM.tif -d DDM.tif -a FAM.tif -s
```

---

## Pipeline (8 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Basin selection, model choice, time period, forcing source |
| 1 | Basic grids | `prepare_basic_grids` | DEM, DDM (drainage direction), FAM (flow accumulation) in ASC/TIF |
| 2 | Forcing prep | `convert_forcing_to_ef5` | Precipitation + PET gridded files with unit conversion |
| 3 | Parameter prep | `convert_params_to_ef5` | Soil/land parameters (WM, Ksat, B, IM) from HWSD/STATSGO |
| 4 | Config generation | (manual/template) | Assemble control.txt with all blocks |
| 5 | Execution | `run_ef5` | Run EF5 binary with preflight validation |
| 6 | Output parsing | `parse_ef5_output` | Extract time series to CSV, compute metrics |
| 7 | Calibration | (built-in) | DREAM/ARS calibration via STYLE=CALI_DREAM |

### Stage Dependencies

- Stages 1, 2, 3 can run in parallel after stage 0.
- Stage 4 depends on 1, 2, 3.
- Stage 5 depends on 4.
- Stages 6, 7 depend on 5.

---

## Configuration File Structure

EF5 uses a single plain-text control file with INI-style sections. Case-insensitive except file paths.

### Section blocks

| Block | Purpose | Required |
|-------|---------|----------|
| `[Basic]` | DEM, DDM, FAM paths; projection; DDM format | Yes |
| `[PrecipForcing NAME]` | Precipitation file type, units, frequency, location, naming | Yes |
| `[PETForcing NAME]` | PET file type, units, frequency, location, naming | Yes |
| `[TempForcing NAME]` | Temperature (required if using Snow-17) | Conditional |
| `[Gauge NAME]` | Gauge location (lon, lat), observed data, basin area | Yes |
| `[Basin NAME]` | Collection of gauges defining modeling domain | Yes |
| `[CrestParamSet NAME]` | CREST water balance parameters | Per model |
| `[SacParamSet NAME]` | SAC-SMA water balance parameters | Per model |
| `[LRParamSet NAME]` | Linear Reservoir routing parameters | Per routing |
| `[KWParamSet NAME]` | Kinematic Wave routing parameters | Per routing |
| `[Snow17ParamSet NAME]` | Snow-17 parameters | Conditional |
| `[SimpleInundationParamSet NAME]` | Simple inundation parameters | Optional |
| `[Task NAME]` | Model run specification (style, model, routing, time, output) | Yes |
| `[Execute]` | Which tasks to run | Yes |

### Complete example

```ini
[Basic]
DEM=/data/basic/DEM.asc
DDM=/data/basic/DDM.asc
FAM=/data/basic/FAM.asc
PROJ=geographic
ESRIDDM=true
SELFFAM=true

[PrecipForcing RAIN]
TYPE=TIF
UNIT=mm/h
FREQ=1h
LOC=/data/precip
NAME=precip_YYYYMMDDHH.tif

[PETForcing PET]
TYPE=TIF
UNIT=mm/h
FREQ=m
LOC=/data/pet
NAME=PET_MM.tif

[Gauge outlet]
LON=117.38
LAT=32.95
OBS=/data/obs/outlet.csv
BASINAREA=5000.0
OUTPUTTS=TRUE

[Basin test]
GAUGE=outlet

[CrestParamSet test]
wm_grid=/data/params/wm.tif
fc_grid=/data/params/ksat.tif
b_grid=/data/params/b.tif
im_grid=/data/params/im.tif
GAUGE=outlet
WM=1.0
B=1.0
IM=0.01
KE=1.0
FC=1.0
IWU=50.0

[KWParamSet test]
GAUGE=outlet
UNDER=1.0
LEAKI=0.04
TH=6.0
ISU=0.0
ALPHA=3.0
BETA=0.93
ALPHA0=4.6

[Task run1]
STYLE=SIMU
MODEL=CREST
ROUTING=KW
BASIN=test
PRECIP=RAIN
PET=PET
OUTPUT=/data/output/
PARAM_SET=test
ROUTING_PARAM_SET=test
TIMESTEP=1h
TIME_BEGIN=200901010000
TIME_END=200912312300

[Execute]
TASK=run1
```

> **DAILY-FORCING NAME TRAP (see triplet dt_030).** The `NAME=` example above
> (`precip_YYYYMMDDHH.tif`) is for `FREQ=1h`. EF5 only substitutes date tokens
> **down to the FREQ resolution** (`DatedName::ProcessName` loops `i<=resolution`).
> For daily forcing (`FREQ=d`) use `NAME=forcing_YYYYMMDD0000.asc` — the `0000` is a
> LITERAL (HH/UU are below daily resolution and are NOT substituted). This matches
> what `convert_forcing_to_ef5.py` writes. Using `...HHUU.asc` with `FREQ=d` makes
> EF5 search for a nonexistent `forcing_YYYYMMDDHHUU.asc`, log a non-fatal
> `Missing precip ... Assuming zeros` for every step, and still finish — producing
> plausible-looking but all-zero-precip output. **Always grep the run log for
> "Missing precip" before trusting metrics.**

---

## Unit Trap Table

| Variable | EF5 Internal Unit | Common Source Unit | Conversion | Trap |
|----------|-------------------|--------------------|------------|------|
| Precipitation | mm/hr (rate) | mm/hr, mm/3hr, mm/day | Set UNIT= in config | Wrong UNIT= silently miscales P |
| PET | mm/hr (rate) | mm/month, mm/day, degC | Set UNIT= in config; degC auto-converts | PET as mm/month with UNIT=mm/h → 720x too large |
| Temperature | degC | degC, K | Must be Celsius | Kelvin input → no snow melt (always >0 threshold) |
| Streamflow output | m^3/s (cms) | — | Native output | — |
| Soil moisture output | % of WM | — | SM/WM*100 | — |
| CREST WM | mm | mm | Grid * scalar | If grid already calibrated, scalar must be 1.0 |
| CREST IM | % (0-100) | 0-100 | Divided by 100 internally | If grid is 0-1, no extra /100 needed (check source) |
| CREST FC (Ksat) | mm/hr | mm/hr | Grid * scalar | — |
| CREST IWU | % of WM (0-100) | 0-100 | SM = IWU*WM/100 | IWU=100 means fully saturated start |
| KW ALPHA | Q=alpha*A^beta | — | Manning's derived | Wrong alpha → orders-of-magnitude Q error |
| KW TH | grid cells | — | Channel threshold | Too low → every cell is channel; too high → no channels |
| Basin area | km^2 | km^2 | — | Wrong area → gauge snaps to wrong cell |
| Gauge coords | decimal degrees | decimal degrees | Reprojected internally | Swapped lat/lon → gauge outside domain |
| DEM | meters | meters | — | DEM in feet → wrong slope, wrong routing speed |
| DDM | ESRI or TauDEM codes | — | Set ESRIDDM=true/false | Wrong DDM format → water routes in wrong direction |
| FAM | cell count | — | Set SELFFAM=true/false | Off-by-one if SELFFAM wrong → gauge mismatch |
| Time step | flexible (y,m,d,h,u,s) | — | TIMESTEP=5u means 5 min | "u" = minutes, not "m" (which is months) |
| Time format | YYYYMMDDHHUUSS | — | — | Missing seconds → parse error |

---

## Unit Conversion Table

This table is the explicit unit table required by the 2026-08-18 skill template.
Use it with `docs/format_spec.yaml`, `dag.yaml`, and the task control file; when a
source dataset is involved, verify the source unit from its own data KI before running.

| Variable | Source unit (verified) | Model / output unit | Factor or conversion | Type | Source |
|----------|------------------------|---------------------|----------------------|------|--------|
| Precipitation forcing | Config-dependent (`UNIT=`) | mm/hr internal rate | EF5 uses `UNIT=` and converts to timestep depth internally | model-unit declaration | EF5 control file + Unit Trap Table |
| PET forcing | Config-dependent (`UNIT=`) | mm/hr internal rate | EF5 uses `UNIT=`; monthly PET must not be declared as `mm/h` | model-unit declaration | EF5 control file + Unit Trap Table |
| Temperature forcing | degC | degC | none when already Celsius; convert K to degC before EF5 | additive if source is K | Unit Trap Table |
| `cout` | EF5 native output | m^3/s | none | output unit | `dag.yaml` |
| `snow` | EF5 optional gridded output / dag output | mm | none | output unit | `dag.yaml` + Gridded Output Options |
| Streamflow gridded output | EF5 native output | m^3/s | none | output unit | Gridded Output Options |
| Soil moisture gridded output | EF5 native output | % | EF5 reports soil moisture as percent of WM | output convention | Unit Trap Table + Gridded Output Options |
| Snow water equivalent gridded output | EF5 native output | mm | none | output unit | Gridded Output Options |
| Inundation gridded output | EF5 native output | m | none | output unit | Gridded Output Options |

---

## Input File Formats

### Gridded formats supported
- **ASC**: ESRI ASCII grid (text, `.asc`)
- **BIF**: Binary version of ESRI ASCII grid (custom EF5 format, 50-byte header)
- **TIF**: Float32 GeoTIFF
- **TRMMRT**: TRMM real-time binary (can be gzipped)
- **TRMMV7**: TRMM 3B42V7 HDF5
- **MRMS**: Multi-Radar Multi-Sensor binary

### BIF header structure (50 bytes, packed)
```
int32   ncols
int32   nrows
float32 xllcorner
float32 yllcorner
float32 cellsize
float32 nodata
char[26] padding
```

### Observed time series format (CSV)
```
YYYY/MM/DD HH:UU:SS,value
2009/06/01 00:00:00,15.3
2009/06/01 01:00:00,16.1
```
Date format follows Excel-style parsing. Comma-separated.

### DDM direction encoding

**ESRI format** (ESRIDDM=true):
```
 32  64  128
 16   X    1
  8   4    2
```

**TauDEM format** (ESRIDDM=false):
```
  4   3   2
  5   X   1
  6   7   8
```

---

## Models Reference

### Water Balance Models

| Model | Key | Parameters | Description |
|-------|-----|------------|-------------|
| CREST | `CREST` | WM, B, IM, KE, FC, IWU | Variable infiltration curve, dual-layer excess storage |
| SAC-SMA | `SAC` | UZTWM, UZFWM, UZK, PCTIM, ADIMP, RIVA, ZPERC, REXP, LZTWM, LZFSM, LZFPM, LZSK, LZPK, PFREE, SIDE, RSERV + 6 state inits | NWS Sacramento model, 5 soil zones |
| HyMOD | `HYMOD` | HUZ, B, ALP, NQ, KQ, KS, XCUZ, XQ, XS, PRECIP | Parsimonious conceptual model |
| HP | `HP` | PRECIP, SPLIT | Fully impervious (100% runoff) |

### Routing Models

| Model | Key | Parameters | Description |
|-------|-----|------------|-------------|
| Linear Reservoir | `LR` | COEM, RIVER, UNDER, LEAKO, LEAKI, TH, ISO, ISU | Dual reservoir (overland + interflow) |
| Kinematic Wave | `KW` | UNDER, LEAKI, TH, ISU, ALPHA, BETA, ALPHA0 | Q=alpha*A^beta routing |

### Snow Model

| Model | Key | Parameters |
|-------|-----|------------|
| Snow-17 | `SNOW17` | UADJ, MBASE, MFMAX, MFMIN, TIPM, NMF, PLWHC, SCF |

### Inundation Models

| Model | Key | Parameters |
|-------|-----|------------|
| Simple Inundation | `SIMPLEINUNDATION` | ALPHA, BETA |
| VC Inundation | `VCINUNDATION` | ALPHA, BETA |

---

## Task Styles

| Style | Purpose |
|-------|---------|
| `SIMU` | Standard simulation run |
| `SIMU_RP` | Simulation with return period statistics |
| `CALI_DREAM` | Calibration using DREAM algorithm |
| `CALI_ARS` | Calibration using ARS algorithm |
| `CLIP_BASIN` | Clip basic grids to basin extent |
| `CLIP_GAUGE` | Clip basic grids around a gauge |
| `BASIN_AVG` | Compute basin-averaged values |

---

## Gridded Output Options

Combine with `|` in OUTPUT_GRIDS:

| Option | Variable | Unit |
|--------|----------|------|
| `STREAMFLOW` | Streamflow | m^3/s |
| `SOILMOISTURE` | Soil moisture | % |
| `RETURNPERIOD` | Return period | years |
| `PRECIP` | Precipitation | mm |
| `PET` | Potential ET | mm |
| `SNOWWATER` | Snow water equivalent | mm |
| `TEMPERATURE` | Temperature | degC |
| `INUNDATION` | Water depth | m |
| `MAXSTREAMFLOW` | Max streamflow during run | m^3/s |
| `MAXSOILMOISTURE` | Max soil moisture during run | % |
| `MAXRETURNPERIOD` | Max return period during run | years |
| `MAXSNOWWATER` | Max SWE during run | mm |

---

## Output Description

EF5 produces two main output types: (1) time series CSV files at gauge points with columns `datetime, simulated_Q (m^3/s)`, written to the OUTPUT directory specified in the Task block, and (2) optional gridded output fields (GeoTIFF or ASC) for streamflow, soil moisture, SWE, return period, and inundation depth, controlled by the `OUTPUT_GRIDS` task parameter. Calibration tasks output a CSV of calibrated parameter sets with objective function values. Use `parse_ef5_output.py` to extract gauge time series, compute performance metrics (NSE, KGE, PBIAS), and generate comparison plots against observed data.

### DAG-sourced output contract

This subsection restates the KI's `dag.yaml` output facts. If this body and
`dag.yaml` ever disagree, `dag.yaml` wins.

**Headline output** (`validation_rank: 1`):

> `cout` — Simulated outflow (discharge) from the outlet lake / subbasin (`m^3/s`)

| Output variable (dag `var`) | Rank | Unit | Description / status |
|-----------------------------|------|------|----------------------|
| `cout` | 1 | m^3/s | Simulated outflow (discharge) from the outlet lake / subbasin |
| `snow` | other dag output | see `dag.yaml` | Other dag output listed by the KI |
| `evap` | other dag output | see `dag.yaml` | Other dag output listed by the KI |
| `soim` | other dag output | see `dag.yaml` | Other dag output listed by the KI |
| `gwat` | other dag output | see `dag.yaml` | Other dag output listed by the KI |
| `wcom` | other dag output | see `dag.yaml` | Other dag output listed by the KI |
| `c1TN` | other dag output | see `dag.yaml` | Other dag output listed by the KI |
| `c1TP` | other dag output | see `dag.yaml` | Other dag output listed by the KI |

---

## Projections

| Key | Description |
|-----|-------------|
| `GEOGRAPHIC` | Standard geographic (lat/lon WGS84) |
| `LAEA` | Lambert Azimuthal Equal Area (std parallel 45N, central meridian -100W) |

---

## Calibration

### DREAM (Recommended)
- Set `STYLE=CALI_DREAM` in Task block
- Requires `CALI_PARAM` block with min/max bounds for each parameter
- Requires `ROUTING_CALI_PARAM` block for routing parameters
- Objective functions: NSCE (Nash-Sutcliffe), CC (Correlation Coefficient), SSE (Sum of Squared Errors)
- Output: CSV with calibrated parameter sets

### Ensemble Calibration
- `[EnsTask]` block wraps multiple tasks for joint calibration
- All ensemble members calibrated simultaneously via DREAM

---

## Validated Results

The KI body does not claim a completed validation campaign. Its current validation
status is `source_dissected`: the binary executes end-to-end at prepared sites, while
observation validation requires hourly `TIMESTEP` as described in `docs/s5_execution.md`.
Use the convention bars below to judge any produced metrics; do not replace missing
bars with remembered thresholds.

### Headline output and convention bars

The rank-1 dag output is:

> `cout` — Simulated outflow (discharge) from the outlet lake / subbasin (`m^3/s`)

| Variable | Metric | Direction | Convention bar, cited |
|----------|--------|-----------|-----------------------|
| `cout` | NSE | maximize | satisfactory >= 0.5 (`moriasi2015`, `moriasi2007`); good >= 0.7 (`moriasi2015`, `moriasi2007`); very_good >= 0.8 (`moriasi2015`, `moriasi2007`) |
| `cout` | PBIAS | zero_centered | satisfactory <= 15.0 (`moriasi2015`); good <= 10.0 (`moriasi2015`); very_good <= 5.0 (`moriasi2015`) |
| `cout` | CSI | maximize | satisfactory: no cited threshold |
| `snow` | NSE | maximize | satisfactory: no cited threshold |

### Performance metrics

| Metric | Calibration | Validation | Full period | Bar (convention, cited) |
|--------|-------------|------------|-------------|-------------------------|
| NSE for `cout` | pending | pending | pending | satisfactory >= 0.5 (`moriasi2015`, `moriasi2007`); good >= 0.7 (`moriasi2015`, `moriasi2007`); very_good >= 0.8 (`moriasi2015`, `moriasi2007`) |
| PBIAS for `cout` | pending | pending | pending | satisfactory <= 15.0 (`moriasi2015`); good <= 10.0 (`moriasi2015`); very_good <= 5.0 (`moriasi2015`) |
| CSI for `cout` | pending | pending | pending | no cited threshold |
| NSE for `snow` | pending | pending | pending | no cited threshold |

### Data replacement tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | Pipeline | pending validation | Use `convert_forcing_to_ef5` and source data KIs |
| Soil / parameters | Pipeline | pending validation | Use `convert_params_to_ef5` |
| DEM / routing grids | Pipeline | pending validation | Use `prepare_basic_grids`; do not use `ef5 -p` |
| Execution | EF5 binary | source dissected | Run with `tools/run_ef5.py` after `python preflight_check.py` |
| Observation scoring | `tools/parse_ef5_output.py` | pending validation | Scores point streamflow time series with temporal metrics |

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `prepare_basic_grids` | s1 | `tools/prepare_basic_grids.py` | DEM → sink-filled DEM + ESRI DDM + SELFFAM=true FAM (WhiteboxTools) |
| `convert_forcing_to_ef5` | s2 | `tools/convert_forcing_to_ef5.py` | CMFD/MSWX/GPM to EF5 precip+PET grids |
| `convert_params_to_ef5` | s3 | `tools/convert_params_to_ef5.py` | HWSD/STATSGO soil to CREST/SAC parameter grids |
| `run_ef5` | s5 | `tools/run_ef5.py` | Execute EF5 with preflight checks |
| `parse_ef5_output` | s6 | `tools/parse_ef5_output.py` | Extract time series, compute NSE/KGE/PBIAS |

### KDT 5.1.2 shared modules used by these tools

| Module | Used by | Purpose |
|--------|---------|---------|
| `ki_tools_common.metrics` | `parse_ef5_output` | NSE/KGE/PBIAS/RMSE computation |
| `ki_tools_common.load_forcing` | `convert_forcing_to_ef5` | CMFD/MSWX/NASA POWER ingestion |
| `ki_tools_common.soil_utils` | `convert_params_to_ef5` | USDA texture + Saxton-Rawls + ROSETTA-VG (added v5.1.2) |
| `ki_tools_common.cross_platform` | `run_ef5` | ELF/PE32 detection, broken-interpreter fix (added v5.1.2) |
| `ki_tools_common.debug_framework` | all stages | Levels 0–3 triage on tool failure |

---

## Key Source Files

| File | Purpose |
|------|---------|
| `src/EF5.cpp` | Main entry point, CLI parsing |
| `src/Config.cpp` | Configuration file parser |
| `src/Simulator.cpp` | Core simulation loop |
| `src/ExecutionController.cpp` | Task dispatch (SIMU, CALI, CLIP) |
| `src/CRESTModel.cpp` | CREST water balance implementation |
| `src/SAC.cpp` | SAC-SMA implementation |
| `src/KinematicRoute.cpp` | Kinematic wave routing |
| `src/LinearRoute.cpp` | Linear reservoir routing |
| `src/Snow17Model.cpp` | Snow-17 temperature-index model |
| `src/ObjectiveFunc.cpp` | NSE, CC, SSE objective functions |
| `src/BasicGrids.cpp` | DEM/DDM/FAM grid loading and basin carving |
| `src/TifGrid.cpp` | GeoTIFF reader |
| `src/BifGrid.cpp` | BIF binary grid reader |
| `src/AscGrid.cpp` | ESRI ASCII grid reader |
| `src/Models.tbl` | Parameter definitions for all models |

---

## Critical Implementation Details

1. **Precipitation internally as mm/hr rate**: `precipIn * stepHours` converts to depth (mm) in water balance
2. **CREST IM divided by 100 internally**: If no IM grid provided, the scalar IM (0-100) is divided by 100 in `InitializeParameters`
3. **CREST IWU as % of WM**: Initial soil moisture = `IWU * WM / 100`
4. **Excess to flow conversion**: `excess / (stepHours * 3600)` converts mm excess to m/s flow rate
5. **Grid parameters are multiplicative**: When both grid and scalar are specified, `param = scalar * grid_value`
6. **NaN check via self-comparison**: `x == x` is false for NaN (used throughout for missing data)
7. **Default control file**: `control.txt` in current directory if no argument given
8. **OpenMP parallelism**: Water balance loop can be parallelized (currently commented out in CREST)
9. **Preload forcings**: Calibration mode caches all forcing data to `califorcings.bin` for speed
10. **Time unit codes**: y=year, m=month, d=day, h=hour, u=minute, s=second — "u" for minutes is non-standard

---

## Scoring Contract & Out-of-Domain Observations

**What this KI scores.** The only scorer shipped is `tools/parse_ef5_output.py`, which
computes TEMPORAL metrics (NSE / KGE / PBIAS / r / RMSE) on **point streamflow time
series** at gauge outlets. `list_gridded_outputs` / `extract_grid_stats` only report
min/max/mean of a gridded field — they do NOT score spatial patterns.

**Out-of-contract observation types (SKIP, no retry).** This KI ships **no spatial
extent scorer**: there is no CSI/POD/FAR (critical-success-index) tool, no flood-extent
GeoTIFF reader/thresholder, and no wrapper that runs EF5's `SimpleInundation` /
`VCInundation` to emit water-depth grids. Therefore observations with
`variable=flood_inundation_extent` and `obs_shape=spatial_snapshot` (e.g. the Global
Flood Database, MODIS-derived per-event flood maps) are OUT OF CONTRACT. Their valid
metric families are `spatial_pattern_match` / `event_detection` (CSI/POD/FAR), which this
KI cannot deliver. Skip such obs; do not score them with temporal NSE/KGE/PBIAS.

**KI-INTEGRITY CAVEAT — dag.yaml is HYPE's, not EF5's.** The installed `dag.yaml`
(and its source `KISSPATH_DATA/EF5_dag_v3_5_auto.yaml`) both carry
`identity.model_id: "HYPE"` with HYPE outputs (`cout`/`snow`/`evap`/`soim`/`gwat`).
The dag-driven obs-shape gate therefore reads HYPE metadata for EF5 runs and CANNOT be
trusted as an EF5 output contract. Prior EF5 streamflow PASSes matched on `var=cout`,
which happens to exist in HYPE's dag as channel discharge, so they passed by luck.
A genuine EF5 dag (declaring streamflow `point_time_series`, and optionally an
inundation-depth `spatial_snapshot` output) must be regenerated upstream by a human /
the auto-dag pipeline before any non-discharge comparison can be considered valid.
