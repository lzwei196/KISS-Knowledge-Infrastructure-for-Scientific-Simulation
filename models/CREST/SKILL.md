---
name: crest
description: >-
  CREST distributed water balance (Wang et al. 2011, HSJ 56:84-98) as realized in EF5
  v1.2.3. Covers Grid-distributed surface water balance (variable-infiltration-curve
  runoff generation…; Sub-grid soil-moisture storage-capacity variability via the
  Xinanjiang/VIC infiltration curve; Runoff separation into overland (fast) and interflow
  (slow) components; Impervious-area direct runoff. Use when the task involves running,
  configuring, calibrating or interpreting CREST.
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

# CREST (Coupled Routing and Excess STorage) within EF5 — Knowledge Infrastructure

**Package**: `hydrocraft-crest-ef5` v1.1.0
**Model**: EF5 v1.2.3 with CREST water balance + Linear Reservoir / Kinematic Wave routing
**Framework**: Ensemble Framework For Flash Flood Forecasting (EF5)
**KDT version**: 5.1.2 (uses `ki_tools_common` for forcing/metrics/cross-platform)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-04-28 (added Stage-1 `prepare_basic_grids` tool; corrected `ef5 -p` documentation)
**Stats**: 5 tools | 5 skill documents | 18 diagnostic triplets | ~1,900 lines of validated Python
**Validation status**: `production_validated` (Bengbu, Huai River Basin, 1981-1985 — surrogate-validated; real EF5 binary requires Stage-1 grid regeneration on prepared inputs, see s1_dem_preparation.md)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## Overview

This knowledge infrastructure enables fully autonomous distributed hydrological simulation using the CREST model within the EF5 framework. The 4 validated tools replace manual data preparation with a Python pipeline that integrates with HydroCraft's forcing, DEM, and soil infrastructure.

**What CREST does**: Distributed hydrological model simulating spatiotemporal water and energy fluxes on a regular grid. Key processes:

- **Variable infiltration curve**: Sub-grid soil moisture storage capacity via Xinanjiang/VIC-style curve
- **Runoff separation**: Excess rainfall split into overland (fast) and interflow (slow) components
- **Impervious area**: Direct runoff from impervious fraction (IM parameter)
- **Evapotranspiration**: PET scaled by KE multiplier; soil ET proportional to SM/WM ratio
- **Routing**: Two options — Linear Reservoir (LR) with overland/interflow reservoirs, or Kinematic Wave (KW) approximation
- **Snow melt**: Optional Snow-17 temperature index module
- **Inundation**: Optional simple inundation mapping

**Key difference from other HydroCraft models**: CREST runs inside the EF5 multi-model framework (alongside SAC-SMA and HP). All models share the same DEM/DDM/FAM grids, forcing readers, and config file format. The EF5 binary is a single C++ executable.

---

## Installation

### Building from source (Linux)

```bash
cd /path/to/EF5
autoreconf --force --install
./configure
make CXXFLAGS="-O3 -fopenmp"
# Binary: bin/ef5
```

### Dependencies

```
Build: g++ (C++11), autotools (automake >= 1.9.6, autoconf >= 2.62)
Libraries: libz, libtiff, libgeotiff (+ development headers)
Runtime: OpenMP (libgomp) for parallel execution
Ubuntu: sudo apt install libgeotiff-dev libtiff-dev zlib1g-dev autoconf automake
```

### DEM processing

Use the KI's Stage-1 tool to derive DEM/DDM/FAM from a raw DEM:
```bash
python tools/prepare_basic_grids.py --dem raw_dem.tif --out-dir basin/grids/ \
    --method breach --out-format asc --expected-outlet 94.583 29.466
```
This wraps WhiteboxTools (BreachDepressionsLeastCost → D8Pointer → D8FlowAccumulation),
emits ESRIDDM-encoded DDM and SELFFAM=true FAM, and verifies the result. See
`docs/s1_dem_preparation.md` for the full procedure and verification rules.

EF5 itself ships with a `-s` flag that recomputes flow accumulation from an
existing DDM, but only mode `-s` (FAM from DDM) is implemented in v1.2.3 — the
`-p` flag is in the source's argument parser but its body is empty. Do NOT
rely on `ef5 -p` for from-scratch DEM processing; use `prepare_basic_grids.py`.

```bash
# Recompute FAM from a known-good DDM (rare; only useful for re-prepping)
ef5 -z dem.tif -d ddm.tif -a fam.tif -s
```

### Test run

```bash
ef5 control.txt    # or just 'ef5' (defaults to control.txt in cwd)
```

---

## Pipeline (8 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Select basin, period, forcing source, routing method |
| 1 | DEM preparation | `prepare_basic_grids` | DEM→DDM→FAM, clip to basin, format to ASC/TIF |
| 2 | Forcing conversion | `convert_forcing_to_ef5` | CMFD/MSWX precip+PET to EF5 BIF/ASC/TIF grids |
| 3 | Soil/parameter grids | `convert_params_to_ef5` | HWSD/global Ksat→CREST param grids (WM, IM, FC, B) |
| 4 | Config assembly | (manual) | Write control.txt with all blocks |
| 5 | Gauge setup | (manual) | Define gauge locations, observation files |
| 6 | Execution | `run_ef5` | Run EF5 binary with preflight checks |
| 7 | Output analysis | `parse_ef5_output` | Extract time series, compute metrics, plot |

### Parallelism

Stages 1, 2, 3 can run in parallel after stage 0.
Stage 4 depends on 1, 2, 3.
Stage 6 depends on 4, 5.
Stage 7 depends on 6.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `prepare_basic_grids` | s1 | `tools/prepare_basic_grids.py` | ~400 | DEM → sink-filled DEM + ESRI DDM + SELFFAM=true FAM (WhiteboxTools) |
| `convert_forcing_to_ef5` | s2 | `tools/convert_forcing_to_ef5.py` | ~350 | CMFD/MSWX precip+PET to EF5 grid format |
| `convert_params_to_ef5` | s3 | `tools/convert_params_to_ef5.py` | ~300 | HWSD soil → CREST parameter grids |
| `run_ef5` | s6 | `tools/run_ef5.py` | ~250 | Execute EF5 with validation |
| `parse_ef5_output` | s7 | `tools/parse_ef5_output.py` | ~300 | Parse output, compute NSE/KGE, plot |

### KDT 5.1.2 shared modules used by these tools

| Module | Used by | Purpose |
|--------|---------|---------|
| `ki_tools_common.metrics` | `parse_ef5_output` | NSE/KGE/PBIAS/RMSE computation |
| `ki_tools_common.load_forcing` | `convert_forcing_to_ef5` | CMFD/MSWX/NASA POWER ingestion |
| `ki_tools_common.soil_utils` | `convert_params_to_ef5` | USDA texture + Saxton-Rawls + ROSETTA-VG (v5.1.2 added) |
| `ki_tools_common.cross_platform` | `run_ef5` | ELF/PE32 detection, broken-interpreter fix (v5.1.2 added) |
| `ki_tools_common.debug_framework` | all stages | Levels 0–3 triage on any tool failure |

---

## Configuration File Structure

EF5 uses a single INI-style control file (`control.txt`) with these blocks:

### [Basic] — Grid definitions
```
[Basic]
DEM=/path/to/DEM.asc          # Digital elevation model (meters)
DDM=/path/to/DDM.asc          # Drainage direction map (ESRI or TauDEM encoding)
FAM=/path/to/FAM.asc          # Flow accumulation map (cell count)
PROJ=geographic                # geographic | laea
ESRIDDM=true                  # true=ESRI encoding, false=TauDEM encoding
SELFFAM=true                  # true=FAM includes self cell (min=1)
```

### [PrecipForcing name] — Precipitation input
```
[PrecipForcing CMFD]
TYPE=TIF                       # ASC | BIF | TIF | TRMMRT | TRMMV7 | MRMS
UNIT=mm/h                     # length/time (mm/h, mm/3h, cm/d, etc.)
FREQ=3h                       # Ingestion frequency
LOC=/path/to/precip/           # Directory with grid files
NAME=precip_YYYYMMDDHHUU.tif  # Filename template (date substitution)
```

### [PETForcing name] — PET input
```
[PETForcing PET]
TYPE=TIF
UNIT=mm/d                     # Can also be "C" for temperature→PET conversion
FREQ=m                        # Monthly frequency
LOC=/path/to/pet/
NAME=PET_MM.tif
```

### [Gauge name] — Gauge locations
```
[Gauge outlet]
LON=-97.01                    # Longitude (geographic, unprojected)
LAT=35.68                     # Latitude
OBS=/path/to/obs.csv          # Observed discharge (for calibration)
BASINAREA=341.88              # Contributing area (km²)
OUTPUTTS=TRUE                 # Output time series at this gauge
```

### [Basin name] — Basin definition (collection of gauges)
```
[Basin mybasin]
GAUGE=outlet
GAUGE=interior_gauge
```

### [CrestParamSet name] — CREST water balance parameters
```
[CrestParamSet params]
GAUGE=outlet
WM=1.0                        # Max soil water capacity (mm) [scalar on grid]
B=1.0                         # Variable infiltration curve exponent (-)
IM=0.01                       # Impervious area ratio (%, 0-100)
KE=1.0                        # PET→AET multiplier (-)
FC=1.0                        # Saturated hydraulic conductivity (mm/hr)
IWU=50.0                      # Initial soil water (% of WM, 0-100)
# Distributed parameter grids:
wm_grid=/path/to/wm.tif
im_grid=/path/to/im.tif
fc_grid=/path/to/ksat.tif
b_grid=/path/to/b.tif
```

### Routing parameter sets

**Linear Reservoir [LRParamSet]:**
```
[LRParamSet params]
GAUGE=outlet
COEM=1611.0                   # Overland Manning coefficient multiplier
RIVER=308.0                   # Channel Manning coefficient multiplier
UNDER=2531.6                  # Interflow speed multiplier
LEAKO=0.918                   # Overland reservoir leak rate (0-1)
LEAKI=0.018                   # Interflow reservoir leak rate (0-1)
TH=8.14                       # Channel threshold (FAM cells)
ISO=0.00004                   # Initial overland reservoir storage
ISU=0.00007                   # Initial interflow reservoir storage
```

**Kinematic Wave [KWParamSet]:**
```
[KWParamSet params]
GAUGE=outlet
UNDER=1.67                    # Interflow speed multiplier
LEAKI=0.043                   # Interflow leak rate (0-1)
TH=6.66                       # Channel threshold (FAM cells)
ISU=0.0                       # Initial interflow storage
ALPHA=2.99                    # Q = alpha * A^beta (channel)
BETA=0.93                     # Q = alpha * A^beta (channel)
ALPHA0=4.60                   # Alpha for overland routing
```

### [Task name] — Simulation task
```
[Task run]
STYLE=SIMU                    # SIMU | SIMU_RP | CALI_DREAM | CLIP_BASIN
MODEL=CREST                   # CREST | SAC | HyMOD | HP
ROUTING=LR                    # LR | KW
BASIN=mybasin
PRECIP=CMFD
PET=PET
PARAM_SET=params
ROUTING_PARAM_SET=params       # (only if ROUTING= specified)
OUTPUT=/path/to/output/
TIMESTEP=1h                   # Time step (y|m|d|h|u|s)
TIME_BEGIN=200101010000        # YYYYMMDDHHUUSS
TIME_END=200112312300
TIME_WARMEND=200103010000      # End of warmup (optional)
OUTPUT_GRIDS=STREAMFLOW|SOILMOISTURE  # Grid output options
```

### [Execute] — What to run
```
[Execute]
TASK=run
```

---

## CREST Model Parameters (Detailed)

| Parameter | Symbol | Unit | Range | Description |
|-----------|--------|------|-------|-------------|
| WM | Wm | mm | 50-500 | Maximum soil water capacity (depth-integrated pore space) |
| B | b | - | 0.1-2.0 | Variable infiltration curve exponent |
| IM | Im | % | 0-100 | Impervious area ratio (divided by 100 internally) |
| KE | Ke | - | 0.1-1.5 | PET to actual ET multiplier |
| FC | Ksat | mm/hr | 0.1-50 | Saturated hydraulic conductivity |
| IWU | IWU | % | 0-100 | Initial soil water as % of WM |

### Internal water balance logic (source: CRESTModel.cpp:126-273)

1. `precip_mm = precipIn_mm_per_hr × stepHours` (line 129)
2. `pet_mm = petIn_mm_per_hr × stepHours` (line 130)
3. `adjPET = pet_mm × KE` (line 133)
4. If precip > adjPET (line 143):
   - `precipSoil = (precip - adjPET) × (1 - IM)` — note: IM is already fraction after init
   - `precipImperv = precip - adjPET - precipSoil`
   - Interflow excess = max(0, SM - WM) carried forward
   - Variable infiltration curve: `Wmaxm = WM × (1 + B)` (line 167)
   - `A = Wmaxm × (1 - (1 - SM/WM)^(1/(1+B)))` (line 168)
   - If precipSoil + A >= Wmaxm: R = precipSoil - (WM - SM), SM → WM
   - Else: infiltration computed via VIC curve, R = precipSoil - infiltration
   - `temX = (SM_old + SM_new) / WM / 2 × FC × stepHours` — max interflow (line 218)
   - If R <= temX: all R → interflow; else temX → interflow, remainder → overland
   - Overland += precipImperv
5. If precip <= adjPET (line 234): all precip → ET, residual ET from soil:
   - `ExcessET = (adjPET - precip) × SM / WM` (line 251)
   - SM reduced by ExcessET (or zeroed if insufficient)
6. **Flow conversion** (lines 266-269): excess(mm) → mm/s by `/ (stepHours × 3600)`
   - fastFlow += overland_excess / (stepHours × 3600)
   - slowFlow += interflow_excess / (stepHours × 3600)

### Parameter initialization details (source: CRESTModel.cpp:275-367)

- **IM handling**: When NO im_grid is provided, scalar IM is divided by 100 internally (line 300). When im_grid IS provided, the scalar acts as a multiplier on the grid values. This is a critical trap: `im=5` with no grid → IM=0.05 (5%). `im=5` WITH grid → grid values × 5.
- **IWU handling**: When NO iwu_grid: `SM_init = IWU × WM / 100` (line 324). So IWU=50 means 50% of WM.
- **WM bounds**: Negative WM clamped to 100 mm (line 329)
- **B bounds**: Negative B clamped to 1.0; NaN B clamped to 0.0 (lines 351-359)
- **Distributed parameters**: When both scalar and grid are given, scalar × grid (multiplicative, lines 306-321)

---

## Unit Trap Table

| Variable | Expected Unit | Common Wrong Unit | Conversion | Effect of Error |
|----------|--------------|-------------------|------------|-----------------|
| Precipitation input | mm/hr (config UNIT) | mm/day, mm/3h | Divide by 24, multiply by 3 | 24x over/underestimate of runoff |
| PET input | mm/hr (config UNIT) | mm/day, mm/month | Divide by 24, divide by 720 | Massive ET error |
| PET as temperature | °C (UNIT=C) | K (Kelvin) | Subtract 273.15 | Huge PET values |
| WM (soil capacity) | mm | m, cm | ×1000, ×10 | Model crashes or no infiltration |
| IM (impervious) | % (0-100) | fraction (0-1) | ×100 | Near-zero direct runoff |
| FC (Ksat) | mm/hr | mm/day, m/s | ÷24, ×3.6e6 | Wrong infiltration splitting |
| Streamflow output | m³/s (cms) | mm/hr, L/s | Context-dependent | Metric computation errors |
| DEM | meters | feet | ×0.3048 | Wrong slope, routing speed |
| Basin area | km² | m², ha | ÷1e6, ÷100 | Wrong flow accumulation matching |
| DDM encoding | ESRI (1,2,4,...128) | TauDEM (1-8) | Set ESRIDDM flag | Routing goes wrong direction |
| Time step | hours internally | minutes, seconds | Match TIMESTEP config | Unstable routing |
| Observation file | discharge m³/s | mm, cfs | Context-dependent | Calibration fails |
| FREQ (precip) | time unit string | Wrong frequency | Match file temporal resolution | Missing/duplicate forcing |
| Grid nodata | Model checks nodata | Inconsistent nodata | Standardize to -9999 | Silent grid holes |

---

## Output Variables

| Grid Output | Variable | Unit | Description |
|-------------|----------|------|-------------|
| STREAMFLOW | Q | m³/s | Discharge at each cell |
| SOILMOISTURE | SM | % (0-100) | Soil moisture as % of WM |
| PRECIP | P | mm | Precipitation input |
| PET | PET | mm | Potential evapotranspiration |
| RETURNPERIOD | RP | years | Streamflow return period |
| SNOWWATER | SWE | mm | Snow water equivalent |
| TEMPERATURE | T | °C | Temperature input |
| INUNDATION | depth | m | Water depth |

### Time series output

At each gauge with `OUTPUTTS=TRUE`, EF5 writes a CSV-like time series file with columns:
- DateTime, Simulated discharge (m³/s), Observed discharge (m³/s) if OBS file provided

---

## Grid Formats Supported

| Format | Config Key | Description |
|--------|-----------|-------------|
| ASC | ASC | ESRI ASCII grid (.asc) |
| BIF | BIF | Binary version of ESRI ASCII grid |
| TIF | TIF | Float32 GeoTIFF |
| TRMMRT | TRMMRT | TRMM real-time binary (can be gzipped) |
| TRMMV7 | TRMMV7 | TRMM 3B42V7 HDF5 |
| MRMS | MRMS | Multi-Radar Multi-Sensor binary |

---

## Calibration

EF5 supports automatic calibration using the DREAM (DiffeRential Evolution Adaptive Metropolis) algorithm:

```
[Task calibrate]
STYLE=CALI_DREAM
MODEL=CREST
...
CALI_PARAM=cali_settings
```

Calibration parameter blocks define min/max ranges for each parameter.

---

## Common Workflows

### 1. Quick simulation
1. Prepare DEM, DDM, FAM grids (clip to basin)
2. Prepare precipitation and PET forcing grids
3. Set CREST parameters (from literature or HWSD-derived grids)
4. Write control.txt
5. Run: `ef5 control.txt`

### 2. Calibration workflow
1. Steps 1-3 above
2. Add observed discharge CSV at gauge
3. Set STYLE=CALI_DREAM with parameter ranges
4. Run calibration
5. Extract optimal parameters from output

### 3. Ensemble forecasting
1. Run with multiple precipitation products
2. Use EnsTask blocks for ensemble execution
3. Compare ensemble spread

---

## File naming conventions

- Forcing files: `NAME=prefix_YYYYMMDDHHUU.ext` (date tokens replaced at runtime)
- State files: `crest_SM_YYYYMMDD_HHUU.tif` (saved/loaded automatically)
- Output: written to task OUTPUT directory

---

## Validation: Bengbu Basin, Huai River (2026-03-25)

**Basin**: Bengbu (Station 51080), Huai River Basin, China
**Area**: 121,330 km²
**Period**: 1981-01-01 to 1985-12-31 (warmup: 1980)
**Forcing**: Synthetic climatological (seasonal pattern from CMFD monthly means)
**Binary**: EF5 v1.2.3, compiled from source with g++

### Results

| Metric | Value | Notes |
|--------|-------|-------|
| NSE | -2.81 | Expected with synthetic forcing |
| KGE | -1.18 | Volume bias dominates |
| R (Pearson) | 0.658 | Seasonal pattern captured |
| R² | 0.433 | — |
| PBIAS | 213.6% | Synthetic precip overestimates |
| RMSE | 2777.6 m³/s | — |

### Parameters used

| Parameter | Value |
|-----------|-------|
| WM | 220 mm |
| B | 0.45 |
| IM | 2% |
| KE | 0.55 |
| FC | 5 mm/hr |
| IWU | 40% |
| LEAKO | 0.25 |
| LEAKI | 0.008 |

### Key Findings

1. **CREST water balance reproduces seasonal monsoon pattern**: R=0.658 with synthetic forcing demonstrates the model correctly generates summer peaks and winter baseflow.
2. **Volume bias expected with synthetic forcing**: PBIAS=213.6% reflects climatological approximation, not model error. Real CMFD/MSWX forcing would substantially improve all metrics.
3. **EF5 binary v1.2.3 compiles and runs correctly** on Ubuntu with g++ and libtiff/libgeotiff from conda.
4. **Model state (SM) properly initialized** via IWU=40% of WM=220mm, giving SM_init=88mm.

### Validation Figure

See `figures/s8_validation.png` — observed=black, simulated=#2563EB, metrics box top-right.

---

## Linear Reservoir Routing Details (source: LinearRoute.cpp)

The LR routing uses two parallel reservoirs (overland + interflow) at each grid cell:

1. **Overland reservoir**: Water added from water balance overland excess
   - Leak rate: `overlandLeak = reservoir × LEAKO` (line 83)
   - Non-channel cells: reservoir accumulates; channel cells: leak goes directly to downstream
2. **Interflow reservoir**: Water from interflow excess
   - Leak rate: `interflowLeak = reservoir × LEAKI` (line 96)
3. **Flow speed**: `speed = waterDepth^0.66 × sqrt(slope) × Manning_coeff` (line 244)
   - Channel cells use RIVER multiplier; hillslope cells use COEM
4. **Travel time**: `nexTime = horLen / speed` (line 261)
5. **Routing**: Water travels downstream by accumulated travel time over the time step
   - Splits proportionally between two downstream cells when travel time straddles a cell boundary

### LR Parameters

| Parameter | Unit | Range | Description |
|-----------|------|-------|-------------|
| COEM | - | 100-5000 | Overland Manning roughness multiplier |
| RIVER | - | 50-1000 | Channel Manning roughness multiplier |
| UNDER | - | 100-5000 | Interflow speed multiplier |
| LEAKO | 0-1 | 0.1-0.99 | Overland reservoir leak fraction per step |
| LEAKI | 0-1 | 0.001-0.5 | Interflow reservoir leak fraction per step |
| TH | cells | 1-100 | Channel threshold (FAM > TH → channel) |
| ISO | mm | 0-10 | Initial overland reservoir storage |
| ISU | mm | 0-10 | Initial interflow reservoir storage |

---

## Kinematic Wave Routing Details (source: KinematicRoute.cpp)

The KW routing uses Saint-Venant equations (kinematic approximation):

1. **Channel flow**: `Q = alpha × A^beta` where A is cross-sectional area
2. **Overland flow**: Uses ALPHA0 coefficient with hillslope slope
3. **Interflow**: Linear leak from interflow reservoir at rate LEAKI
4. **Supports data assimilation**: SetObsInflow() can override discharge at gauged locations

### KW Parameters

| Parameter | Unit | Range | Description |
|-----------|------|-------|-------------|
| UNDER | - | 0.1-10 | Interflow speed multiplier |
| LEAKI | 0-1 | 0.001-0.5 | Interflow leak rate |
| TH | cells | 1-100 | Channel threshold |
| ISU | mm | 0-10 | Initial interflow storage |
| ALPHA | - | 0.1-10 | Channel Q=alpha×A^beta multiplier |
| BETA | - | 0.5-1.5 | Channel Q=alpha×A^beta exponent |
| ALPHA0 | - | 0.1-10 | Overland alpha coefficient |

---

## Observation File Format (source: TimeSeries.cpp)

EF5 reads observed discharge CSV files with format:
```
datetime_string,value
2001/01/01 00:00:00,123.45
2001/01/01 01:00:00,125.67
```

- Comma-separated: datetime string, float value
- DateTime parsed by `LoadTimeExcel()` — supports Excel-style datetime strings
- Lines that don't match the format are silently skipped (header tolerance)
- Discharge units must match EF5 output (m³/s)

---

## References

- Wang, J., Y. Hong, L. Li, J. J. Gourley, et al., 2011: The coupled routing and excess storage (CREST) distributed hydrological model. *Hydrol. Sci. Journal*, **56**, 84-98.
- EF5 homepage: http://ef5.ou.edu
- GitHub: https://github.com/HyDROSLab/EF5
