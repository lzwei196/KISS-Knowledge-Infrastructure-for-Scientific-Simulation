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
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (32 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (22 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing_to_pcrglobwb.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_pcrglobwb.py --help` |
| `tools/convert_soil_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_params.py --help` |
| `tools/fetch_pcrglobwb_inputs.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/fetch_pcrglobwb_inputs.py --help` |
| `tools/make_clone_map.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/make_clone_map.py --help` |
| `tools/parse_pcrglobwb_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_pcrglobwb_output.py --help` |
| `tools/run_pcrglobwb.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_pcrglobwb.py --help` |

*6 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# PCR-GLOBWB 2 (PCRaster Global Water Balance) — Knowledge Infrastructure

**Package**: `hydrocraft-pcrglobwb2` v1.0.0
**Model**: PCR-GLOBWB 2 — Global Hydrological & Water Resources Model
**Created by**: Department of Physical Geography, Utrecht University (Model); HydroCraft KI Dissection (Package)
**Last updated**: 2026-03-25
**Stats**: 4 tools | 5 skill documents | 15+ diagnostic triplets | ~1,500 lines of validated Python
**Validation status**: `initial_dissection`

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing`
(or `load_daily_forcing_points` for a whole clone grid in one decompression pass)
for CMFD/MSWX/GSWP3/NASA POWER. `convert_forcing_to_pcrglobwb.py --clone-json`
wraps this and writes the two forcing NetCDFs directly on the clone grid.

**CMFD units** (verified against `data/forcing/Data_forcing_01dy_010deg/`):
`prec` is **kg m-2 s-1** (NOT mm/day) and `temp` is **K**. There is no `pet`
variable. `ki_tools_common.load_forcing` already returns mm/day and °C, so the
only remaining PCR-GLOBWB conversion is mm/day → m/day (dt_001).

**Data Validation Reference**: soil properties and observed-discharge layouts are
described in `KISSPATH_DATA_KI/dataset_index.yaml` and
`kdt_dataset_layouts.yaml`. (Earlier revisions of this file pointed at
`data_ki/CMFD/SKILL.md`, `data_ki/HWSD/SKILL.md` and `data_ki/ObservedQ/SKILL.md`
— those paths do not exist under KDT 5.0.)


## Overview

This knowledge infrastructure enables autonomous simulation of global/regional hydrology using PCR-GLOBWB 2 (PCRaster Global Water Balance model version 2) developed at Utrecht University. PCR-GLOBWB 2 is a grid-based global hydrological and water resources model that simulates the terrestrial water cycle at 5 arcmin (~10 km) or 30 arcmin (~50 km) resolution.

**What PCR-GLOBWB 2 does**: Spatially distributed, process-based water balance model. Simulates:
- Meteorological forcing (precipitation, temperature, reference ET)
- Snow accumulation and melt (degree-day method)
- Interception by vegetation canopy
- Soil water dynamics (2 or 3 layer Improved Arno scheme)
- Surface runoff, interflow, and baseflow generation
- Groundwater recharge and storage (linear reservoir)
- River routing (accuTravelTime or kinematic wave)
- Lake and reservoir dynamics
- Water demand and abstraction (irrigation, domestic, industrial, livestock)
- Desalination water supply
- Dynamic floodplain inundation

**Key difference from other HydroCraft models**: PCR-GLOBWB 2 operates on a global/regional grid (not a single point or single lake). It uses the PCRaster spatial modeling framework and reads all parameters/forcing from NetCDF files via OPeNDAP (remote) or local storage. The model runs on a **daily timestep only**.

**Reference paper**: Sutanudjaja et al. (2018), PCR-GLOBWB 2: a 5 arcmin global hydrological and water resources model, Geosci. Model Dev., 11, 2429-2453.

---

## 6. Output Description (dag-sourced)

**Source of truth**: `dag.yaml`. If this section ever disagrees with the dag, the dag wins and this section is wrong.

**Headline output** (`validation_rank: 1`):

> `discharge` — River channel discharge at each cell. (`m3/s`)

| Output variable (dag `var`) | rank | Unit | Description |
|---|---:|---|---|
| `discharge` | 1 | `m3/s` | River channel discharge at each cell. |
| `totalRunoff` | 2 | `m/day` | Total runoff (surface plus subsurface) generated per cell. |
| `actualET` | 3 | `m/day` | Actual evapotranspiration — water flux from the land surface to the atmosphere. |
| `gwRecharge` | 4 | `m/day` | Groundwater recharge flux from the lower soil store. |
| `storGroundwater` | 5 | `m` | Groundwater reservoir storage (S3). |
| `totalWaterStorageThickness` | 6 | `m` | Total water storage (snow + interception + soil + groundwater + surface water), comparable to satellite total-water-storage-anomaly retrievals. |
| `snowCoverSWE` | 7 | `m` | Snow water equivalent. |

For quick answers to "what does this model predict", answer with the dag rank-1 output first: `discharge` in `m3/s`. Other dag outputs are `totalRunoff`, `actualET`, `gwRecharge`, `storGroundwater`, `totalWaterStorageThickness`, and `snowCoverSWE`.

---

## 8. Unit Conversion Table

**Source of truth**: `docs/format_spec.yaml`, `dag.yaml`, and `diagnostics/triplets.yaml`. PCR-GLOBWB uses meters for depth-based water quantities internally; most silent failures are 1000x unit mistakes.

| Variable | Source unit (verified or expected) | Model unit | Conversion | Type | Trap |
|---|---|---|---|---|---|
| CMFD precipitation `prec` | `kg m-2 s-1` | `mm/day` from `ki_tools_common.load_forcing`, then `m/day` for PCR-GLOBWB | `x86400`, then `/1000`; direct raw-CMFD-to-model factor is `86.4` | multiplicative | dt_001, dt_028 |
| Generic precipitation forcing | `mm/day` | `m/day` | `/1000` | multiplicative | dt_001 |
| CMFD temperature `temp` | `K` | `degC` from `ki_tools_common.load_forcing`, then PCR-GLOBWB `degC` | `-273.15` | additive | dt_002 |
| Generic temperature forcing | `K` | `degC` | `-273.15` | additive | dt_002 |
| Reference potential ET | `mm/day` | `m/day` | `/1000` | multiplicative | dt_003 |
| Soil storage / soil water capacity | `mm` | `m` | `/1000` | multiplicative | dt_004 |
| Water demand | `mm/day` or `m3/day` | `m/day` depth | `mm/day / 1000` or `m3/day / cell_area_m2` | multiplicative / area-normalized | dt_005 |
| Groundwater abstraction | `m3/day` if supplied as volume | `m/day` depth | `m3/day / cell_area_m2` | area-normalized | dt_006 |
| Specific yield | `%` | fraction `m3/m3` | `/100` | multiplicative | dt_007 |
| Aquifer saturated hydraulic conductivity `kSatAquifer` | `cm/hr` | `m/day` | `x0.24` | multiplicative | dt_008 |
| `discharge` output | computed internally | `m3/s` | none | output unit | dag rank 1 |
| `totalRunoff` output | computed internally | `m/day` | none | output unit | dag rank 2 |
| `actualET` output | computed internally | `m/day` | none | output unit | dag rank 3 |
| `gwRecharge` output | computed internally | `m/day` | none | output unit | dag rank 4 |
| `storGroundwater` output | computed internally | `m` | none | output unit | dag rank 5 |
| `totalWaterStorageThickness` output | computed internally | `m` | none | output unit | dag rank 6 |
| `snowCoverSWE` output | computed internally | `m` | none | output unit | dag rank 7 |

**Output unit verification checklist**:

- Read the NetCDF variable attributes before scoring: `python -c "import xarray as xr; ds=xr.open_dataset('file.nc'); print(ds['discharge'].attrs)"`.
- Print the first values and their range; `discharge` is absolute river channel discharge in `m3/s`, not a depth.
- Extract daily discharge with `--aggregation dailyTot`; otherwise the first alphabetical file can be an annual aggregate.
- Treat flux outputs such as `totalRunoff`, `actualET`, and `gwRecharge` as `m/day` unless the NetCDF metadata proves otherwise.

---

## 9. Diagnostic Triplets (Top 5)

Use `diagnostics/triplets.yaml` before debugging. These five are the most likely silent or early-fail traps for this KI; the YAML remains the full source of truth.

| # | Error | Diagnosis | Remedy |
|---|---|---|---|
| dt_001 | Extreme flooding, unrealistic runoff values; river discharge 1000x too high. | Precipitation in `mm/day` instead of `m/day`. | Divide precipitation by `1000` when source values are `mm/day`. |
| dt_002 | No snow accumulation in cold regions; wrong ET calculation; temperature values above `200`. | Temperature in Kelvin instead of Celsius. | Subtract `273.15` from Kelvin forcing. |
| dt_003 | Soil is always dry; excessive actual ET; groundwater depletes rapidly. | Reference ET in `mm/day` instead of `m/day`. | Divide reference ET by `1000`. |
| dt_009 | Model reads zero forcing with no precipitation and zero temperature. | NetCDF variable names do not match the expected names. | Rename forcing variables exactly to `precipitation`, `temperature`, `evapotranspiration`, or `referencePotET`. |
| dt_021 | Startup crash: `IndexError: list index out of range` at `virtualOS.py:1842`. | `mapattr` binary is not on the subprocess PATH. | Prepend the active conda environment `bin` directory to PATH before running the model. |

---

## 11. Validated Results

**Status**: body campaign pending. This section records the cited validation bars from `docs/validation_convention.yaml`; it does not claim achieved model skill unless a run-specific result is present.

### Headline Validation Target

| Property | Value |
|---|---|
| Dag rank-1 variable | `discharge` |
| Unit | `m3/s` |
| Description | River channel discharge at each cell. |
| Observation shape | point time series |
| Validation source | `docs/validation_convention.yaml` |

### Performance Metrics - judged against the field's bar, not intuition

| Dag variable | Metric | Direction | Convention bar (cited) | Achieved |
|---|---|---|---|---|
| `discharge` | `nse` | maximize | satisfactory `0.5` (moriasi2015); good `0.7` (moriasi2015); very_good `0.8` (moriasi2015) | body campaign pending |
| `discharge` | `pbias` | zero_centered | satisfactory `15` (moriasi2015); good `10` (moriasi2015); very_good `5` (moriasi2015) | body campaign pending |
| `totalRunoff` | `nse` | maximize | satisfactory `0.55` (moriasi2015); good `0.65` (moriasi2015) | body campaign pending |
| `totalRunoff` | `pbias` | zero_centered | satisfactory `20` (moriasi2015) | body campaign pending |
| `actualET` | `nse` | maximize | no cited threshold | body campaign pending |

For zero-centered `pbias`, apply the cited bands to absolute percent bias. A null convention band is written as `no cited threshold`; do not replace it with a guessed threshold.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|---|---|---|---|
| Forcing | Pipeline via `convert_forcing_to_pcrglobwb` / `ki_tools_common.load_forcing` | Pending per run | CMFD `prec` is `kg m-2 s-1`; CMFD `temp` is `K`; no CMFD `pet` variable. |
| Soil | Pipeline via `convert_soil_params` | Pending per run | Soil storage and depth quantities must be in `m`. |
| Land cover | PCR-GLOBWB input tree / configured datasets | Pending per run | Four cover types: forest, grassland, irrPaddy, irrNonPaddy. |
| DEM / routing | Clone map, landmask, LDD, cell area | Pending per run | Clone map must be local and aligned; gauge snapping must follow the LDD. |
| Initial conditions | PCR-GLOBWB initial condition files or spin-up | Pending per run | Start on 1 January of `ic_year + 1` when using shipped non-natural initial conditions. |

---

## Installation

### Environment Setup

```
# Create conda environment with PCRaster
conda env create --name pcrglobwb_python3 -f conda_env/pcrglobwb_py3.yml
conda activate pcrglobwb_python3
```

### Dependencies

```
Core:     python>=3.6, pcraster (spatial modeling framework)
Python:   numpy, netCDF4, python-dateutil, six
Optional: cdsapi (ERA5 data download), cdo, nco, ncview
```

### Source Location

```
Model scripts:  model/                     # All Python modules
Entry point:    model/deterministic_runner.py
Configuration:  config/*.ini               # Example .ini files
Clone maps:     clone_landmask_maps/       # PCRaster spatial extent maps
Exercises:      exercise/                  # Tutorial documents
```

### Input Data (~250 GB for global extent)

```
OPeNDAP server: https://opendap.4tu.nl/thredds/dodsC/data2/pcrglobwb/version_2019_11_beta/pcrglobwb2_input/
Structure:
  global_05min/
    cloneMaps/          # Clone and landmask maps (PCRaster format)
    landSurface/        # Soil properties, topography, land cover
    groundwater/        # Aquifer properties, thickness
    routing/            # LDD map, channel properties, water bodies
    waterUse/           # Irrigation, domestic/industry/livestock demand
    initialConditions/  # IC files for all state variables
    meteo/              # Downscaling parameters
  global_30min/
    meteo/forcing/      # CRU-ERA-Interim daily precipitation, temperature, refET
    landSurface/        # 30min parameters
    waterUse/           # 30min water use data
```

---

## Pipeline (9 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Edit .ini file: set cloneMap, inputDir, outputDir, dates |
| 1 | Clone/Landmask | `make_clone_map` | Trace the gauge's upstream catchment on the model's own LDD; write clone + landmask PCRaster maps |
| 1b | Input Acquisition | `fetch_pcrglobwb_inputs` | Download a bbox subset (~5 MB) of `global_30min` from 4TU OPeNDAP; resumable |
| 2 | Forcing Preparation | `convert_forcing_to_pcrglobwb` | Convert global forcing data to PCR-GLOBWB format (NetCDF, correct units), or build it on the clone grid straight from `ki_tools_common.load_forcing` |
| 3 | Soil/Parameter Setup | `convert_soil_params` | Prepare soil properties, topography, and land cover parameters |
| 4 | INI Configuration | (manual) | Configure all sections: global, meteo, landSurface, groundwater, routing, reporting |
| 5 | Spin-up | `run_pcrglobwb` | Run spin-up cycles for state variable convergence |
| 6 | Transient Run | `run_pcrglobwb` | Execute the main simulation with `deterministic_runner.py` |
| 7 | Output Analysis | `parse_pcrglobwb_output` | Extract discharge, storage, fluxes from NetCDF outputs |
| 8 | Post-processing | (manual) | Merge parallel outputs, compute statistics, validate against observations |

### Parallelism

- Stages 2 and 3 can run in parallel
- Spin-up (stage 5) runs years cyclically until convergence
- For large domains, the model supports parallelization by splitting clone maps (e.g., 53 clones for global 5 arcmin)

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `make_clone_map` | s1 | `tools/make_clone_map.py` | Build clone + landmask maps from a gauge lat/lon by tracing the LDD |
| `fetch_pcrglobwb_inputs` | s1b | `tools/fetch_pcrglobwb_inputs.py` | Fetch a bbox subset of `global_30min` inputs from 4TU OPeNDAP |
| `convert_forcing_to_pcrglobwb` | s2 | `tools/convert_forcing_to_pcrglobwb.py` | Convert meteorological forcing to PCR-GLOBWB NetCDF format |
| `convert_soil_params` | s3 | `tools/convert_soil_params.py` | Convert HWSD/SoilGrids data to PCR-GLOBWB soil parameters |
| `run_pcrglobwb` | s5/s6 | `tools/run_pcrglobwb.py` | Execute PCR-GLOBWB with preflight checks |
| `parse_pcrglobwb_output` | s7 | `tools/parse_pcrglobwb_output.py` | Parse output NetCDF to CSV time series |

### New-basin recipe (validated at Songhua @ 哈尔滨, 2026-07-09)

A 30-arcmin regional run needs no manual file authoring. For a gauge at
(`LAT`, `LON`) with reported drainage area `AREA` km²:

```bash
PCR_PY=<...>/miniconda/envs/pcrglobwb_python3/bin/python

# s1  clone + landmask (extent derived from the LDD, so it always contains the
#     full contributing area; corners auto-snapped -> dt_011 cannot happen)
$PCR_PY tools/make_clone_map.py --out-dir $O/clone --prefix MyBasin30min \
    --gauge-lat LAT --gauge-lon LON --target-area-km2 AREA --buffer-cells 1
# -> writes MyBasin30min.clone.json with rows/cols/xUL/yUL, the snapped gauge
#    cell, and the traced upstream area (CHECK it against AREA before running)

# s1b  localise inputs (~5 MB for a 22x20 clone; skip files already present)
$PCR_PY tools/fetch_pcrglobwb_inputs.py --bbox LON_MIN LAT_MIN LON_MAX LAT_MAX \
    --local-dir $O/input --year-start 2000 --year-end 2010 --ic-year 1999

# s2  forcing on the clone grid, straight from the shared loader
#     (mode (b): --clone-json; needs an interpreter with ki_tools_common)
python tools/convert_forcing_to_pcrglobwb.py --source cmfd \
    --clone-json $O/clone/MyBasin30min.clone.json \
    --forcing-dir KISSPATH_FORCING/Data_forcing_01dy_010deg \
    --output-dir $O/input/global_30min/meteo/forcing \
    --start-date 2000-01-01 --end-date 2010-12-31 --subsample 2

# s6  run, s7 extract at the SNAPPED gauge cell (not the reported lat/lon)
$PCR_PY tools/run_pcrglobwb.py $O/setup.ini --model-dir <repo>/model
$PCR_PY tools/parse_pcrglobwb_output.py $O/netcdf --variable discharge \
    --aggregation dailyTot --lat <gauge_cell_lat> --lon <gauge_cell_lon> -o sim.csv
```

**Hard constraints discovered on the Songhua run:**

- **Simulation end date ≤ 2010-12-31** with the shipped water-use inputs.
  `domestic/industrial/desalination` water demand and `irrigationArea30ArcMin`
  all stop at 2010; `livestock` stops at 2012. Running past the last year of a
  water-demand file with `includeIrrigation = True` reads past the end of the
  series.
- **Initial conditions** are only published for a few years under
  `initialConditions/non-natural/consistent_run_201903XX/<year>/`. Start the run
  on 1 January of `ic_year + 1` and treat the first year as warm-up
  (`maxSpinUpsInYears = 0` is then fine — this is what the Rhine/Kaub reference
  run does).
- **Derive reference ET whenever the forcing allows it.** CMFD V0200 ships
  `srad`, `wind`, `shum` and `pres` alongside `prec`/`temp`, so FAO-56
  Penman-Monteith refET is computable. Call
  `build_from_ki_forcing(..., refet_method="penman")` from
  `tools/convert_forcing_to_pcrglobwb.py` -- `penman` is already the default --
  to write `referencePotET.nc`. Then set, in `[meteoOptions]`:
  `referenceETPotMethod = Input` and
  `refETPotFileNC = global_30min/meteo/forcing/referencePotET.nc`.
  The NetCDF variable must be named `evapotranspiration` (`model/meteo.py:177`)
  unless you override `referenceEPotVariableName`.
  Reserve `referenceETPotMethod = Hamon` for forcings that genuinely lack
  radiation/wind/humidity. Temperature-only Hamon under-estimates PET in cold
  continental monsoon basins (~665 vs ~907 mm/yr at Songhua); PCR-GLOBWB caps
  actualET by referencePotET, so the water the basin fails to evaporate routes
  to the outlet and inflates discharge (+76% PBIAS while r stayed 0.864).
  See dt_031.
- **Always pass `--aggregation dailyTot`** when extracting a daily series
  (see dt_027).

### Before fetching anything: LOOK FOR AN EXISTING LOCAL INPUT TREE

The 4TU OPeNDAP endpoint is frequently unreachable (every REQUIRED file failed
the preflight on 2026-07-12/13, and again on 2026-07-19: the host answers at
`/` but DAP requests stall). `fetch_pcrglobwb_inputs.py` is resumable, so a
down endpoint does not crash — it retries for hours in a detached run where
nobody is watching. **Do not launch a run that depends on a fetch you have not
proved reachable.**

Complete 30 arcmin trees already exist locally and cover whole regions:

```
KISSPATH_OUTPUTS_ALT/pcrglobwb2_huai_bengbu/input      # Huai   111.5-118.0E, 30.5-35.0N
KISSPATH_OUTPUTS_ALT/pcrglobwb2_araguaia_araguatins/input
KISSPATH_OUTPUTS_ALT/pcrglobwb2_rhine_kaub_2000_2005/input
```

Each holds ~100 NetCDFs (LDD, cell area, soil, topography, groundwater, all
four landCover sets, the full waterUse stack) plus initial conditions and, for
the Huai tree, CMFD forcing with Penman-Monteith refET for 1979-01-01..1997-12-31.
**A gauge anywhere inside one of those bboxes needs NO fetch at all** — point
`inputDir` at the existing tree and reuse its clone/landmask if your catchment
is a topological subset of it.

**TRAP — the orphaned cache (2026-07-19).**
`KISSPATH_OUTPUTS` is now a SYMLINK to
`KISSPATH_DATA/hc_outputs`, but the real trees live in
`outputs_disk1/`. The absolute paths baked into the older `.ini` files and
`*.clone.json` still say `KISSPATH_OUTPUTS/...`, which now
resolves to an EMPTY directory. A runner reusing those paths therefore finds no
cache, decides it must fetch, and hangs on the dead OPeNDAP server — which is
exactly how the 2026-07-12/13 runs burned out with null metrics. Always
`ls` the tree and count `*.nc` before trusting a cached path.

### Gauge snapping picks a river, not just an area (dt_032)

`make_clone_map.py` now applies a **river-identity guard**: the cell containing
the reported lon/lat must lie on the snapped cell's flow path. Area alone is
NOT sufficient — at Wangjiaba the area-only rule chose a Shaying tributary cell
at +0.83% over the correct Huai mainstem cell at +45%. Check
`river_identity_guard: PASS|FAIL` in the emitted `clone.json`.

At 30 arcmin the Huai mainstem is legitimately over-aggregated, so a *large*
area error is the honest answer there and a *tiny* one is the suspicious one:

| gauge | cell | traced km² | reported km² | err |
|---|---|---|---|---|
| Xixian 息县 | (32.25, 114.75) | 15,751 | 10,190 | +54.6% |
| Huaibin 淮滨 | (32.25, 115.25) | 21,006 | 16,005 | +31.2% |
| Wangjiaba 王家坝 | (32.25, 115.75) | 44,414 | 30,630 | +45.0% |
| Lutaizi 鲁台子 | (32.75, 116.75) | 104,178 | 88,630 | +17.5% |
| **Zhoukou 周口** | (33.75, 114.75) | **25,701** | **25,800** | **−0.4%** |
| Fuyang 阜阳 | (32.75, 115.75) | 33,489 | 35,246 | −5.0% |

For a 30 arcmin Huai validation, **Zhoukou (Shaying) is the well-posed gauge**;
Fuyang's record starts in 2001 and so misses the 1979-1997 forcing window.
Bengbu (51080) is the excluded guardrail gauge and must not be scored.

---

## Configuration (.ini) File Structure

PCR-GLOBWB is configured via a single `.ini` file with these sections:

### [globalOptions]
```ini
outputDir    = /path/to/output/            # Output directory (absolute path)
inputDir     = https://opendap.4tu.nl/...  # Input data (OPeNDAP or local)
cloneMap     = /local/path/clone.map       # PCRaster clone map (MUST be local)
landmask     = /local/path/landmask.map    # Area of interest (None = use LDD)
startTime    = 2000-01-01                  # Start date (YYYY-MM-DD)
endTime      = 2010-12-31                  # End date (YYYY-MM-DD)
maxSpinUpsInYears = 0                      # Spin-up cycles (0 = no spin-up)
```

### [meteoOptions]
```ini
precipitationNC = global_30min/meteo/forcing/daily_precipitation_*.nc
temperatureNC   = global_30min/meteo/forcing/daily_temperature_*.nc
referenceETPotMethod = Input               # "Hamon" or "Input"
refETPotFileNC  = global_30min/meteo/forcing/daily_referencePotET_*.nc
```

### [landSurfaceOptions]
```ini
numberOfUpperSoilLayers = 2                # 2 or 3 soil layers
topographyNC     = global_05min/landSurface/topography/*.nc
soilPropertiesNC = global_05min/landSurface/soil/*.nc
includeIrrigation = True
includeDomesticWaterDemand = True
includeIndustryWaterDemand = True
includeLivestockWaterDemand = True
```

### [forestOptions] / [grasslandOptions] / [irrPaddyOptions] / [irrNonPaddyOptions]
Four land cover types, each with:
```ini
snowModuleType      = Simple
freezingT           = 0.0                  # degrees Celsius
degreeDayFactor     = 0.0025               # m/day/degC
snowWaterHoldingCap = 0.1                  # fraction
refreezingCoeff     = 0.05                 # fraction
cropCoefficientNC   = ...                  # Kc time series
interceptCapNC      = ...                  # Interception capacity
coverFractionNC     = ...                  # Vegetation cover fraction
```

### [groundwaterOptions]
```ini
groundwaterPropertiesNC = ...              # specificYield, kSatAquifer, recessionCoeff
minRecessionCoeff = 1.0e-4                 # day-1
limitFossilGroundWaterAbstraction = True
```

### [routingOptions]
```ini
lddMap      = global_05min/routing/.../lddsound_05min.nc   # Drainage direction
cellAreaMap  = global_05min/routing/.../cellsize05min.nc    # Cell area (m2)
routingMethod = accuTravelTime             # or "kinematicWave"
manningsN   = 0.04                         # Manning's coefficient
dynamicFloodPlain = True                   # Flood plain simulation
```

### [reportingOptions]
```ini
outDailyTotNC  = discharge,totalRunoff,gwRecharge,...
outMonthTotNC  = actualET,precipitation,totalRunoff,...
outMonthAvgNC  = discharge,temperature,surfaceWaterStorage,...
outAnnuaTotNC  = totalEvaporation,precipitation,...
```

---

## Unit Convention Table (CRITICAL)

| Variable | Internal Unit | Common Source Unit | Conversion | Trap ID |
|----------|--------------|-------------------|------------|---------|
| Precipitation | m/day | mm/day (CRU, ERA5) | divide by 1000 | dt_001 |
| Temperature | degrees Celsius | Kelvin (ERA5) | subtract 273.15 | dt_002 |
| Reference ET | m/day | mm/day | divide by 1000 | dt_003 |
| Soil storage | m | mm | divide by 1000 | dt_004 |
| Discharge | m3/s | - | computed internally | - |
| Cell area | m2 | - | from clone map | - |
| Water demand | m/day | mm/day or m3/day | must be m/day depth | dt_005 |
| Groundwater abstraction | m/day | - | depth over cell area | dt_006 |
| Specific yield | m3/m3 (fraction) | percentage | divide by 100 | dt_007 |
| kSat aquifer | m/day | cm/hr | multiply by 0.24 | dt_008 |
| Recession coefficient | day-1 | - | - | - |

**CRITICAL TRAP**: PCR-GLOBWB uses **meters** for all depth-based quantities (precipitation, ET, soil storage, etc.) — NOT millimeters. Most global datasets provide values in mm. Forgetting to divide by 1000 causes floods or droughts.

---

## Input Variable Requirements

### Meteorological Forcing (3 required variables)

| Variable | NetCDF var name | Unit | Temporal | Spatial |
|----------|----------------|------|----------|---------|
| Precipitation | `precipitation` | m/day | daily | 30 or 5 arcmin |
| Temperature | `temperature` | degrees Celsius | daily | 30 or 5 arcmin |
| Reference Potential ET | `evapotranspiration` or `referencePotET` | m/day | daily | 30 or 5 arcmin |

**Variable names in NetCDF MUST match exactly**: `precipitation`, `temperature`, `evapotranspiration`/`referencePotET`.

### Soil Parameters (from soilPropertiesNC)

- `KSat1`, `KSat2` — saturated hydraulic conductivity (m/day)
- `satVolWC1`, `satVolWC2` — saturated volumetric water content (m3/m3)
- `resVolWC1`, `resVolWC2` — residual volumetric water content (m3/m3)
- `airEntryValue1`, `airEntryValue2` — air entry suction head (m)
- `poreSizeBeta1`, `poreSizeBeta2` — pore-size distribution parameter (-)
- `percolationImp` — percolation impervious fraction (-)

### Topography Parameters (from topographyNC)

- `tanslope` — dimensionless
- `slopeLength` — m
- `orographyBeta` — dimensionless

---

## Output Variables

PCR-GLOBWB outputs NetCDF files in `outputDir/netcdf/` with variables controlled by `[reportingOptions]`.

### Key Output Variables

| Variable | Unit | Description |
|----------|------|-------------|
| `discharge` | m3/s | River discharge at each cell |
| `totalRunoff` | m/day | Total runoff (surface + subsurface) |
| `gwRecharge` | m/day | Groundwater recharge |
| `actualET` | m/day | Actual evapotranspiration |
| `precipitation` | m/day | Precipitation (as read) |
| `temperature` | deg C | Temperature (as read) |
| `storGroundwater` | m | Groundwater storage |
| `channelStorage` | m3 | Channel storage |
| `waterBodyStorage` | m3 | Lake/reservoir storage |
| `surfaceWaterStorage` | m3 | Total surface water storage |
| `snowCoverSWE` | m | Snow water equivalent |
| `totalWaterStorageThickness` | m | Total water storage |

### Output Directory Structure

```
outputDir/
  netcdf/          # All NetCDF output files
  states/          # End-of-run state maps (PCRaster)
  maps/            # Intermediate PCRaster maps
  log/             # Log and debug files
  tmp/             # Temporary files (cleaned each run)
  scripts/         # Backup of Python scripts used
```

---

## Execution

### Basic Run

```bash
conda activate pcrglobwb_python3
cd model/
python deterministic_runner.py /path/to/setup.ini
```

### With Debug Mode

```bash
python deterministic_runner.py /path/to/setup.ini debug
```

### With Custom Output Directory

```bash
python deterministic_runner.py /path/to/setup.ini normal --output_dir /custom/output/
```

### Parallelized Global Run

For global 5 arcmin runs, split into multiple clones (subdomains):
```bash
# Each clone has its own .ini file with different cloneMap and landmask
python deterministic_runner.py setup_clone_01.ini &
python deterministic_runner.py setup_clone_02.ini &
...
# Then merge outputs using merge_netcdf.py
python merge_netcdf.py
```

---

## Critical Domain Knowledge

### 1. All depths in meters, NOT millimeters (dt_001)

PCR-GLOBWB uses meters for all water depth quantities. Most global datasets (CRU, ERA5, CMFD) provide precipitation/ET in mm/day. Always divide by 1000 when preparing forcing data.

### 2. Temperature in Celsius, NOT Kelvin (dt_002)

ERA5 provides temperature in Kelvin. Subtract 273.15. CRU-ERA-Interim already provides Celsius.

### 3. NetCDF variable names must match exactly (dt_009)

The forcing reader expects specific variable names: `precipitation`, `temperature`, `evapotranspiration`/`referencePotET`. Any mismatch causes a silent failure where the model reads zeros.

### 4. Clone map MUST be stored locally (dt_010)

The clone map (PCRaster format) defines spatial resolution and extent. It cannot be read from OPeNDAP — must be a local file. Other inputs CAN use OPeNDAP.

### 5. Clone map corners must be "nicely-rounded" (dt_011)

The corner coordinates of the clone map must be integer values without decimals. Non-integer corners cause spatial misalignment with input data.

### 6. Daily timestep ONLY (dt_012)

PCR-GLOBWB runs exclusively on daily timestep (`timeStep = 1.0`, `timeStepUnit = day`). Attempting sub-daily or multi-day steps causes an error.

### 7. Spin-up convergence criteria (dt_013)

Spin-up checks convergence of: soil storage, groundwater storage, channel storage, and total storage. Set `maxSpinUpsInYears > 0` to enable. Typical: 5-30 years depending on domain.

### 8b. `mapattr` must be on PATH (dt_021)

`virtualOS.getMapAttributesALL()` shells out to `mapattr -p <cloneMap>` with
`Popen(shell=True)`. If the conda env's `bin/` is not on the subprocess PATH the
call returns empty output and the model dies with a *misleading*
`IndexError: list index out of range` at `virtualOS.py:1842`, immediately
followed by a cascading `KeyError: 'time'` — neither of which mentions PATH or
`mapattr`. Read the FIRST traceback, not the last. `run_pcrglobwb.py` now
prepends `dirname(sys.executable)` to PATH and hard-fails early if `mapattr`
still isn't resolvable, so this trap only bites hand-rolled invocations.

### 8c. Selecting the right output file (dt_027)

The same variable is written once per temporal aggregation. Extract daily series
with `--aggregation dailyTot`; `discharge_annuaAvg_output.nc` sorts first
alphabetically and will otherwise be picked.

### 8. OPeNDAP input access (dt_014)

Input data can be read directly from `https://opendap.4tu.nl/...` without downloading ~250 GB. However, network latency makes this 10-100x slower than local files. For production runs, download inputs locally.

---

## Calibration Parameters (Priority Order)

| Parameter | Section | Range | Controls | Sensitivity |
|-----------|---------|-------|----------|-------------|
| `degreeDayFactor` | landCover | 0.001-0.01 m/day/degC | Snow melt rate | HIGH (snow-dominated) |
| `minRecessionCoeff` | groundwater | 1e-5 - 1e-2 day-1 | Baseflow recession | HIGH |
| `manningsN` | routing | 0.01-0.10 | Channel flow velocity | MEDIUM |
| `kSatAquifer` | groundwater | 0.01-100 m/day | Groundwater flow | MEDIUM |
| `arnoBeta` | landCover | 0.01-1.2 | Runoff generation curve | MEDIUM |
| `irrigationEfficiency` | landSurface | 0.3-1.0 | Irrigation water use | LOW |

---

## Coupling Points

| Direction | Partner Model | Variable | Unit | Method |
|-----------|--------------|----------|------|--------|
| Input | CRU-ERA-Interim / W5E5 | Precipitation, Temperature, ET | m/day, degC, m/day | NetCDF forcing files |
| Output | CaMa-Flood | Total runoff | m/day per cell | Discharge routing |
| Output | MODFLOW | Groundwater head, baseflow | m, m/day | Online coupling |
| Input | MODFLOW | Groundwater recharge | m/day | Online coupling |

---

## Known Issues

1. **Allocation segments float32 error**: When using allocation segments for surface water abstraction, yearly accumulated values of `actSurfaceWaterAbstract` and `allocSurfaceWaterAbstract` may differ slightly due to PCRaster float32 numerical precision.

2. **Script backup incomplete**: The output backup of Python scripts does not include subfolders (e.g., `evaporation/`).

3. **Variable name inconsistency**: Some initial condition key names changed between versions — the model includes `repair_ini_key_names()` to handle backward compatibility.

---

## Model Architecture

```
deterministic_runner.py          # Entry point, DynamicModel framework
  ├── configuration.py           # Parse .ini file, setup paths
  ├── currTimeStep.py            # Time step management
  ├── pcrglobwb.py               # Main model class
  │   ├── meteo.py               # Meteorological forcing reader
  │   ├── landSurface.py         # Land surface processes
  │   │   ├── landCover.py       # Per-cover-type processes
  │   │   └── parameterSoilAndTopo.py  # Soil & topography params
  │   ├── groundwater.py         # Groundwater module
  │   └── routing.py             # River routing
  │       └── waterBodies.py     # Lakes and reservoirs
  ├── reporting.py               # NetCDF output writer
  │   ├── ncConverter.py         # PCR-to-NetCDF conversion
  │   └── variable_list.py       # Variable metadata
  ├── spinUp.py                  # Spin-up convergence checks
  └── virtualOS.py               # File I/O utilities
```

### Four Land Cover Types

1. **forest** — Natural tall vegetation
2. **grassland** — Natural short vegetation
3. **irrPaddy** — Irrigated paddy (rice) fields
4. **irrNonPaddy** — Irrigated non-paddy cropland

Each has its own snow, interception, soil water, and crop coefficient parameters.

### Soil Layer Configuration

- **2-layer mode** (`numberOfUpperSoilLayers = 2`): Upper soil (storUpp) + Lower soil (storLow)
- **3-layer mode** (`numberOfUpperSoilLayers = 3`): 0-5cm (storUpp000005) + 5-30cm (storUpp005030) + 30-150cm (storLow030150)

---

## Quick Start Recipe

1. Install conda environment: `conda env create -f conda_env/pcrglobwb_py3.yml`
2. Activate: `conda activate pcrglobwb_python3`
3. Download clone map from examples (e.g., Rhine-Meuse 5 arcmin)
4. Edit `config/setup_05min.ini`:
   - Set `outputDir` to a local writable directory
   - Set `cloneMap` to local clone map path
   - Set `landmask` to local landmask path or `None`
5. Run: `cd model/ && python deterministic_runner.py ../config/setup_05min.ini`
6. Check outputs in `outputDir/netcdf/`
