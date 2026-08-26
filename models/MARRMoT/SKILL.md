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
| on ANY error, before debugging | `diagnostics/triplets.yaml` (20 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (18 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/calib_run.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/calib_run.py --help` |
| `tools/convert_forcing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing.py --help` |
| `tools/convert_parameters.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_parameters.py --help` |
| `tools/parse_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output.py --help` |
| `tools/run_marrmot.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_marrmot.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# MARRMoT Knowledge Infrastructure

**Package**: hydrocraft-marrmot v1.0.0
**Model**: MARRMoT v2.1.2 (Modular Assessment of Rainfall-Runoff Models Toolbox)
**Domain**: Conceptual rainfall-runoff hydrology
**Language**: MATLAB / GNU Octave (with Python BMI interface)
**License**: GNU GPL v3
**Created**: 2026-03-25

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## Overview

MARRMoT is a MATLAB/Octave toolbox containing **47 unique conceptual hydrological
model structures** with standardized parameter ranges and robust numerical solvers.
It enables objective comparison of lumped rainfall-runoff models under identical
numerical and data conditions.

Key characteristics:

- 47 model structures ranging from 1-parameter/1-store to 24-parameter/6-store
- 111 reusable flux functions (evaporation, baseflow, infiltration, percolation, etc.)
- 8 unit hydrograph routing methods (half/full triangle, gamma, uniform, delay)
- Object-oriented architecture: all models inherit from `MARRMoT_model` superclass
- Implicit Euler ODE solver with Newton-Raphson + fallback strategies
- Built-in calibration via CMA-ES optimiser
- Built-in objective functions: KGE, NSE, RMSE, inverse-KGE, log-NSE, etc.
- Python interface via BMI (Basic Model Interface) using oct2py bridge
- Docker support for containerised execution
- All fluxes computed in mm/d; storages in mm

---

## Installation

### Option A: MATLAB (native)

Requires MATLAB R2016b+ (R2021b+ recommended) with Optimization Toolbox.

```bash
git clone https://github.com/wknoben/MARRMoT
# In MATLAB: addpath(genpath('MARRMoT/MARRMoT'))
```

### Option B: GNU Octave

Requires Octave 6.4.0+ with `optim` package.

```bash
apt-get install octave octave-optim
git clone https://github.com/wknoben/MARRMoT
# In Octave: addpath(genpath('MARRMoT/MARRMoT'))
# pkg load optim  % auto-loaded by MARRMoT_model constructor
```

### Option C: Docker (Octave-based)

```bash
docker build -t marrmot .
docker run -v $PWD:/data --entrypoint octave marrmot /data/run_script.m
```

### Option D: Python BMI bridge

```bash
pip install oct2py numpy scipy
# Requires Octave installed on system
```

### Dependencies

| Component     | Required          | Purpose                          |
|---------------|-------------------|----------------------------------|
| MATLAB/Octave | Yes               | Core runtime                     |
| Optim Toolbox | Yes (calibration) | CMA-ES, fsolve, lsqnonlin       |
| oct2py        | Python BMI only   | MATLAB/Octave-Python bridge      |
| numpy/scipy   | Python BMI only   | Numerical support                |
| Docker        | Optional          | Containerised execution          |

### Test installation

```matlab
m = feval('m_01_collie1_1p_1s');
m.theta = 100;
m.input_climate = [ones(365,1)*5, ones(365,1)*2, ones(365,1)*15];
m.delta_t = 1;
m.S0 = 50;
m.get_output();
% Should print water balance summary
```

---

## Pipeline

The MARRMoT workflow converts global hydrometeorological data into
catchment-scale rainfall-runoff simulations using one of 47 model structures.

| # | Stage                  | Tool                       | Description                                           |
|---|------------------------|----------------------------|-------------------------------------------------------|
| 1 | Forcing preparation    | `convert_forcing.py`       | Convert global met data to [P, Ep, T] in mm/d and C   |
| 2 | Parameter setup        | `convert_parameters.py`    | Map soil/land properties to model parameter ranges     |
| 3 | Model selection        | (manual)                   | Choose from 47 model structures                       |
| 4 | Initial conditions     | (manual)                   | Set S0 vector (typically zeros or spin-up)             |
| 5 | Execution              | `run_marrmot.py`           | Run model via Octave subprocess                       |
| 6 | Output parsing         | `parse_output.py`          | Extract Q, Ea, storage to CSV                         |
| 7 | Validation             | `parse_output.py`          | Compute NSE, KGE, PBIAS against observations          |
| 8 | Calibration            | `run_marrmot.py` (loop)    | CMA-ES or Monte Carlo parameter optimisation          |
| 9 | Multi-model comparison | (manual)                   | Compare structures using consistent metrics           |

**Parallelism**: Stages 1-2 can run in parallel. Stages 3-4 are manual decisions.
Stage 5 depends on 1-4. Stages 6-7 depend on 5. Stage 8 is iterative on 5-7.

---

## Unit Trap Table

These are the critical unit conversions that cause **silent failures** if wrong.
Every value enters the model in specific units; no internal conversion is performed.

| Variable            | MARRMoT expects | Common source unit | Conversion                          | Trap ID |
|---------------------|-----------------|--------------------|-------------------------------------|---------|
| Precipitation       | mm/d            | mm/3h (CMFD)       | sum 8 values per day                | dt_001  |
| Precipitation       | mm/d            | kg/m2/s (ERA5)     | x 86400                             | dt_002  |
| Precipitation       | mm/d            | m/d (some GCMs)    | x 1000                              | dt_003  |
| PET                 | mm/d            | W/m2 (net rad)     | Penman-Monteith or Hargreaves       | dt_004  |
| PET                 | mm/d            | mm/month           | / days_in_month                     | dt_005  |
| PET (cold/high-alt) | mm/d            | Oudin/Hargreaves under-est | check Ep>=P-Q; use --pet-method priestley_taylor | dt_019  |
| Temperature         | deg C           | K (ERA5/CMFD)      | - 273.15                            | dt_006  |
| Temperature         | deg C           | deg F              | (F - 32) x 5/9                     | dt_007  |
| Storage (Smax)      | mm              | m                  | x 1000                              | dt_008  |
| Time step (delta_t) | days            | hours              | / 24                                | dt_009  |
| Streamflow (obs)    | mm/d            | m3/s               | x 86400 / (area_km2 x 1e6) x 1000  | dt_010  |

---

## Tools Reference

| Tool                  | Stage       | Script                           | Lines | Purpose                                         |
|-----------------------|-------------|----------------------------------|-------|--------------------------------------------------|
| `convert_forcing`     | s1_forcing  | `tools/convert_forcing.py`       | ~300  | Global met data to MARRMoT climate array         |
| `convert_parameters`  | s2_params   | `tools/convert_parameters.py`    | ~280  | Soil/land data to model parameter vector         |
| `run_marrmot`         | s5_execute  | `tools/run_marrmot.py`           | ~250  | Execute model via Octave subprocess              |
| `parse_output`        | s6_output   | `tools/parse_output.py`          | ~250  | Parse Octave output to CSV with metrics          |

---

## Critical Domain Knowledge

These non-obvious facts cause silent failures. Each is linked to a diagnostic triplet.

1. **dt_001 / dt_002 / dt_003**: Precipitation units must be mm/d. ERA5 provides
   kg/m2/s (multiply by 86400). CMFD provides mm/3h (sum 8 per day). GCMs may
   provide m/d (multiply by 1000). Wrong units produce runoff 1000x too high/low.

2. **dt_004 / dt_005 / dt_019**: PET must be pre-computed externally. MARRMoT does NOT compute
   PET from radiation. Common trap: passing radiation (W/m2) as PET. Use Hargreaves
   or Penman-Monteith to convert. Monthly PET must be divided by days_in_month.
   **PET-method choice (dt_019):** Oudin and Hargreaves are temperature-index formulae
   calibrated on temperate lowlands and structurally UNDER-estimate atmospheric demand on
   cold, high-altitude, high-radiation basins (e.g. the Tibetan Plateau / upper Yellow R).
   BEFORE calibrating, check `Ep_annual >= (P - Q_obs)_annual`. If it fails and downwelling
   radiation is available (CMFD ALWAYS supplies srad/lrad/pres), rebuild forcing with
   `convert_forcing.py --pet-method priestley_taylor --srad-col ... --lrad-col ... --pres-col ...`
   (always pass `--pres-col`; the 101325 Pa sea-level fallback inflates gamma and
   under-estimates Ep exactly at altitude). The trap tell: water_balance FAIL with GR4J x2
   (groundwater exchange) pinned near its bound while NSE/r still look respectable.

3. **dt_006**: Temperature in Kelvin silently produces wrong snow/rain partitioning
   in models with temperature thresholds (m_06, m_12, m_37, etc.). No error raised.

4. **dt_009**: delta_t must match the actual time step of forcing data. If forcing is
   daily but delta_t=24 (hours), all fluxes are scaled by 24x. Always use delta_t=1
   for daily data.

5. **dt_011**: Input climate array column order is [P, Ep, T], NOT [P, T, Ep].
   Swapping Ep and T is silent and produces nonsensical evaporation.

6. **dt_012**: Initial storage S0 vector length must equal number of stores. Too few
   elements cause MATLAB index error; too many are silently ignored. Check
   `m.numStores` before setting S0.

7. **dt_013**: Newton-Raphson solver may fail silently on stiff problems (high Smax
   with very low initial storage). Increase `resnorm_maxiter` to 12+ or check
   `solverSteps` output for solver fallback warnings.

8. **dt_014**: Water balance check is printed to console but NOT enforced. A water
   balance error > 1 mm indicates numerical problems, but the model does not stop.

9. **dt_015**: Unit hydrograph routing assumes delta_t matches the routing time base.
   Using sub-daily time steps with daily UH parameters shifts the hydrograph peak.

---

## Output Description

MARRMoT's `get_output()` method returns a structure containing three main arrays: (1) `Q` -- simulated streamflow in mm/d (same length as forcing time series), (2) `Ea` -- actual evapotranspiration in mm/d, and (3) `S` -- storage time series in mm for each model store (columns = stores). A water balance summary is printed to the console. The `parse_output.py` tool extracts these into a CSV with columns `date, Q_sim (mm/d), Ea (mm/d), S1, S2, ...` and computes validation metrics (NSE, KGE, PBIAS) against observed streamflow. To convert Q from mm/d to m^3/s, multiply by `catchment_area_km2 * 1e6 / 86400 / 1000`.

## 6. Output Description -- dag-sourced

This section restates `dag.yaml`. If this section and `dag.yaml` disagree, `dag.yaml` wins.

**Headline output**: `Q` -- Total simulated streamflow at the catchment outlet (sum of fluxes in FluxGroups.Q, after unit-hydrograph routing). (`mm/d`)

| Output variable (dag `var`) | validation rank | Unit | Emitted in | Description |
|-----------------------------|-----------------|------|------------|-------------|
| `Q` | 1 | mm/d | `fluxOutput.Q (get_output / get_streamflow)` | Total simulated streamflow at the catchment outlet (sum of fluxes in FluxGroups.Q, after unit-hydrograph routing). |
| `Ea` | 2 | mm/d | `fluxOutput.Ea (get_output)` | Actual evapotranspiration -- catchment water flux to the atmosphere, aggregated from the model's evaporation fluxes. |
| `S` | 3 | mm | `storeInternal (get_output)` | Storage time series per model store (e.g. soil moisture, fast reservoir, slow/baseflow reservoir, snow store); number of stores varies by structure (1 to 8). |
| `waterBalance` | 4 | mm | `waterBalance (check_waterbalance)` | Scalar water-balance closure residual over the run; should be near zero (<1 mm). Computed and printed but NOT enforced by the model. |

Other dag outputs are `Ea`, `S`, and `waterBalance`. Scoring and observation binding should treat `Q` as the rank-1 output.

## 8. Unit Conversion Table -- source-restated

This table restates the KI's existing unit traps and `docs/format_spec.yaml`. MARRMoT performs no internal unit conversion on the forcing array or parameter vector.

| Variable | Source unit | MARRMoT / comparison unit | Conversion | Source in KI |
|----------|-------------|---------------------------|------------|--------------|
| Precipitation | mm/3h (CMFD) | mm/d | sum 8 values per day | `Unit Trap Table`, `docs/format_spec.yaml` |
| Precipitation | kg/m2/s (ERA5) | mm/d | x 86400 | `Unit Trap Table`, `docs/format_spec.yaml` |
| Precipitation | m/d (some GCMs) | mm/d | x 1000 | `Unit Trap Table`, `docs/format_spec.yaml` |
| Potential evapotranspiration | W/m2 (net radiation) | mm/d | compute PET externally with Penman-Monteith or Hargreaves; do not pass radiation as PET | `Unit Trap Table`, `docs/format_spec.yaml` |
| Potential evapotranspiration | mm/month | mm/d | divide by `days_in_month` | `Unit Trap Table`, `docs/format_spec.yaml` |
| Temperature | K | deg C | subtract 273.15 | `Unit Trap Table`, `docs/format_spec.yaml` |
| Temperature | deg F | deg C | `(F - 32) x 5/9` | `Unit Trap Table`, `docs/format_spec.yaml` |
| Storage parameter (`Smax`, `x1`, `x3`) | m | mm | x 1000 | `Unit Trap Table`, `docs/format_spec.yaml` |
| Time step (`delta_t`) | hours | days | divide by 24 | `Unit Trap Table`, `docs/format_spec.yaml` |
| Observed streamflow | m3/s | mm/d | `Q_mm = Q_m3s * 86400 / (area_km2 * 1e6) * 1000` | `Unit Trap Table`, `dag.yaml`, `docs/format_spec.yaml` |
| Simulated streamflow `Q` | mm/d | m3/s | `Q_m3s = Q_mm_d * area_km2 * 1e6 / 86400 / 1000` | `Output Description`, `dag.yaml` |

## 11. Validated Results -- convention-sourced

**Status**: body campaign pending. This SKILL body does not claim achieved calibration, validation, or full-period scores until they are produced by the actual MARRMoT package and parsed by the KI tools.

**Rank-1 validation target**: `Q` (`mm/d`) -- Total simulated streamflow at the catchment outlet (sum of fluxes in FluxGroups.Q, after unit-hydrograph routing).

| Dag variable | Metric | Direction | Convention bands, with citation key on each band | Validation status in this body |
|--------------|--------|-----------|--------------------------------------------------|--------------------------------|
| `Q` | `nse` | maximize | very_good: 0.8 (`moriasi2015`, `moriasi2007`); good: 0.6 (`moriasi2015`, `moriasi2007`); satisfactory: 0.5 (`moriasi2015`, `moriasi2007`) | pending |
| `Q` | `pbias` | zero_centered | very_good: 3.0 (`moriasi2015`); good: 10.0 (`moriasi2015`); satisfactory: 15.0 (`moriasi2015`) | pending |
| `Q` | `pbias` | zero_centered | very_good: 3.0 (`moriasi2015`); good: 10.0 (`moriasi2015`); satisfactory: 15.0 (`moriasi2015`) | pending |
| `Ea` | `nse` | maximize | satisfactory: no cited threshold (`ershadi2014`) | pending |

For `Q` PBIAS, apply the bands to absolute PBIAS magnitude because the convention direction is zero-centered. For `Ea` NSE, do not substitute a numeric pass line: the convention records the satisfactory band as null, so this body states `no cited threshold`.

---

## Validation

### Test case: Buffalo River, Tennessee, USA

- **Model**: m_01_collie1_1p_1s (simplest, 1 parameter)
- **Period**: Included in MARRMoT_example_data.mat
- **Source**: BMI test case data

### HyMOD benchmark (m_29_hymod_5p_5s)

- **Parameters**: [Smax=200, b=0.5, a=0.7, kf=0.1, ks=0.01]
- **Typical KGE**: 0.6-0.85 after calibration on daily streamflow
- **Typical NSE**: 0.5-0.80

---

## Calibration Parameters

For HyMOD (m_29), the most commonly used benchmark model:

| Parameter | Symbol | Range       | Unit  | Sensitivity | Description                    |
|-----------|--------|-------------|-------|-------------|--------------------------------|
| Smax      | S_max  | [1, 2000]   | mm    | High        | Maximum soil moisture storage  |
| b         | b      | [0, 10]     | -     | Medium      | Distribution function shape    |
| a         | alpha  | [0, 1]      | -     | High        | Flow split fast/slow           |
| kf        | k_f    | [0, 1]      | 1/d   | Medium      | Fast reservoir rate constant   |
| ks        | k_s    | [0, 1]      | 1/d   | Low         | Slow reservoir rate constant   |

For other models, parameter ranges are defined in each model file's `parRanges`
property. Run `m = feval('m_XX_name'); m.parRanges` to retrieve bounds.

### Calibration optimisers (`run_marrmot.py --calibrate`)

Two optimisers are available via `--optimizer`:

- `mc` (default, legacy): uniform Monte-Carlo over `parRanges`. Fine for ≤3-4
  parameters; **hopeless beyond ~6** because the good region is an
  exponentially small fraction of the hypercube. Writes incremental best
  (timeout-safe).
- `cmaes` (**recommended**): MARRMoT's own CMA-ES (`my_cmaes`) via the
  `MARRMoT_model.calibrate` method — the optimiser the toolbox ships and
  documents (`User manual/Examples/workflow_example_4.m`). Scales to the
  6-15 parameter snow/soil/GW structures. Options:
  - `--of-name` : objective function (`of_NSE`, `of_KGE`, `of_log_NSE`, ...).
    KGE-family take a 3-weight vector (auto-handled); NSE-family take none.
    `check_and_select` natively drops NaN / negative obs, so **seasonal/gappy
    HYDAT records (e.g. prairie creeks gauged only Mar-Oct) need no masking**.
  - `--restarts N` : **IPOP restarts (doubled popsize each)**. A single
    mean-start CMA-ES run gets trapped in a local optimum on the rugged
    conceptual-hydrology objective surface — observed at 05CG004:
    mean-start cal_NSE **0.199**, with `--restarts 6` cal_NSE **0.329**.
    Always use ≥5 restarts for a real calibration.
  - `--max-fun-evals` : total eval budget across restarts. Each eval is one
    full simulation over `1:cal_end`. **Cost scales sharply with numStores**:
    m_12 alpine2 (2 stores) ≈ 1.6 s/eval (~550 evals ≈ 15 min); m_37 hbv
    (5 stores) ≈ **50 s/eval** under the implicit Euler solver — not
    "uncalibratable", but budget-limited: pair it with `--timeout` (below) and
    report how many evals it actually got.
  - `--lb/--ub` : optional tightened sampling bounds (JSON arrays).
  - `--timeout` : wall-clock cap, and it is **safe to rely on**. BOTH optimisers
    persist their incumbent to `best_theta.json` on every improvement (CMA-ES via
    the `kdt_of_persist` objective shim), and expiry is handled as a normal
    budget-limited outcome (`status: "partial"`, `timed_out: true`) rather than an
    exception. This is what makes a whole-toolbox sweep tractable: give every
    structure the same wall-clock cap, let the cheap ones converge and the
    expensive ≥5-store ones return their best-so-far. **Always report the eval
    budget next to a partial structure's metric** — a low NSE there means
    "under-searched", not "structurally unsuitable".

### Snowfall undercatch correction (`convert_forcing.py --cold-precip-scale`)

NASA POWER (MERRA-2) under-catches **solid** precip far more than rain. For
snowmelt-dominated basins the spring freshet — the NSE-dominant signal — is
driven by accumulated winter snow, so under-caught snowfall systematically
damps the simulated freshet. `--cold-precip-scale F --cold-precip-threshold T`
multiplies precip by `F` only on days with mean-T < `T` (default 0 °C),
boosting winter accumulation **without** inflating ET-dominated summer months
(which a global `--precip-scale` does, over-producing runoff). At 05CG004
(Bullpound Ck), `--cold-precip-scale 1.7` lifted held-out val NSE
0.152→0.209 and improved r at every period.

---

## Coupling Points

| Source              | Target           | Variable     | Unit    | Notes                          |
|---------------------|------------------|--------------|---------|--------------------------------|
| ERA5/CMFD/MSWX      | MARRMoT forcing  | Precip       | mm/d    | Aggregated to daily            |
| Hargreaves/PM        | MARRMoT forcing  | PET          | mm/d    | Pre-computed externally        |
| ERA5/CMFD            | MARRMoT forcing  | Temperature  | deg C   | Mean daily                     |
| MARRMoT output Q     | Routing model    | Streamflow   | mm/d    | Convert to m3/s for routing    |
| Observed discharge   | Validation       | Streamflow   | mm/d    | Convert from m3/s using area   |
| HWSD/SoilGrids       | Parameters       | Soil props   | various | Map to Smax, percolation rates |

---

## Data Requirements

| Data Type            | Source            | Status    | Path / Notes                             |
|----------------------|-------------------|-----------|------------------------------------------|
| Precipitation        | ERA5 / CMFD       | Required  | Must convert to mm/d                     |
| Temperature          | ERA5 / CMFD       | Required  | Must convert to deg C                    |
| PET                  | Pre-computed      | Required  | Hargreaves from Tmin/Tmax or PM          |
| Observed streamflow  | GRDC / local      | Optional  | For calibration/validation, convert mm/d |
| Catchment area       | Shapefile / known | Optional  | For m3/s <-> mm/d conversion             |
| Soil properties      | HWSD / SoilGrids  | Optional  | For parameter estimation                 |

---

## Quick Start

```bash
# 1. Prepare forcing
python tools/convert_forcing.py \
  --input /path/to/era5_daily.nc \
  --output forcing.csv \
  --lat 35.5 --lon 117.3 \
  --start 2000-01-01 --end 2010-12-31

# 2. Estimate parameters from soil data
python tools/convert_parameters.py \
  --model m_29_hymod_5p_5s \
  --soil-data /path/to/hwsd.csv \
  --output params.json

# 3. Run model
python tools/run_marrmot.py \
  --forcing forcing.csv \
  --model m_29_hymod_5p_5s \
  --params params.json \
  --output run_output.json

# 4. Parse and validate output
python tools/parse_output.py \
  --input run_output.json \
  --observed /path/to/observed_q.csv \
  --output results.csv \
  --figure validation.png
```

---

## Diagnostic Triplets Summary

| ID     | Stage      | Failure Domain    | Severity | Symptom (short)                           |
|--------|------------|-------------------|----------|-------------------------------------------|
| dt_001 | s1_forcing | unit_conversion   | silent   | Precip 1000x too high (mm/3h not mm/d)    |
| dt_002 | s1_forcing | unit_conversion   | silent   | Precip wrong from kg/m2/s                  |
| dt_003 | s1_forcing | unit_conversion   | silent   | Precip wrong from m/d                      |
| dt_004 | s1_forcing | unit_conversion   | silent   | PET given as radiation W/m2                |
| dt_005 | s1_forcing | unit_conversion   | silent   | Monthly PET not divided by days            |
| dt_006 | s1_forcing | unit_conversion   | silent   | Temperature in K not C                     |
| dt_007 | s1_forcing | unit_conversion   | silent   | Temperature in F not C                     |
| dt_008 | s2_params  | unit_conversion   | silent   | Storage parameter in m not mm              |
| dt_009 | s5_execute | parameter_format  | degraded | delta_t mismatch (hours vs days)           |
| dt_010 | s6_output  | unit_conversion   | silent   | Observed Q in m3/s not mm/d               |
| dt_011 | s1_forcing | parameter_format  | silent   | Climate columns swapped [P,T,Ep]           |
| dt_012 | s5_execute | parameter_format  | fatal    | S0 length != numStores                     |
| dt_013 | s5_execute | runtime           | degraded | Solver fails on stiff ODE                  |
| dt_014 | s5_execute | silent_error      | silent   | Water balance error not enforced            |
| dt_015 | s5_execute | parameter_format  | degraded | UH time base vs delta_t mismatch           |

---

## File Structure

```
ki/
  SKILL.md                           # This file (agent entry point)
  tools/
    convert_forcing.py               # Stage 1: Global met -> MARRMoT climate
    convert_parameters.py            # Stage 2: Soil data -> parameter vector
    run_marrmot.py                   # Stage 5: Execute model via Octave
    parse_output.py                  # Stage 6: Parse output + compute metrics
  docs/
    s1_forcing_preparation.md        # Forcing data conversion skill
    s2_parameter_estimation.md       # Parameter mapping skill
    s3_model_selection.md            # Model selection guide
    s5_execution.md                  # Model execution skill
    s6_output_analysis.md            # Output parsing and validation skill
  diagnostics/
    triplets.yaml                    # 15+ diagnostic triplets
```

---

## All 47 Model Structures

**These are the EXACT names shipped in `Models/Model files/`** — pass the full
name (the `Class / file name` column) to `run_marrmot.py --model`. Derive nothing:
the `Np`/`Ns` counts are part of the filename, and several differ from the
upstream paper's tables (e.g. `m_26` is `flexi`, not "flexis"; `m_47` is
capitalised `IHM19`). Verify at runtime with
`m = feval('<name>'); [m.numParams m.numStores]`.

`Ns` (number of stores) is the cost driver: each store adds a dimension to the
implicit-Euler solve, so per-evaluation cost rises steeply (~1.6 s/eval at 2
stores to ~50 s/eval at 5). Budget calibration accordingly.

| ID | Name | Np | Ns | Class / file name |
|----|------|----|----|-------------------|
| m_01 | collie1 | 1 | 1 | `m_01_collie1_1p_1s` |
| m_02 | wetland | 4 | 1 | `m_02_wetland_4p_1s` |
| m_03 | collie2 | 4 | 1 | `m_03_collie2_4p_1s` |
| m_04 | newzealand1 | 6 | 1 | `m_04_newzealand1_6p_1s` |
| m_05 | ihacres | 7 | 1 | `m_05_ihacres_7p_1s` |
| m_06 | alpine1 | 4 | 2 | `m_06_alpine1_4p_2s` |
| m_07 | gr4j | 4 | 2 | `m_07_gr4j_4p_2s` |
| m_08 | us1 | 5 | 2 | `m_08_us1_5p_2s` |
| m_09 | susannah1 | 6 | 2 | `m_09_susannah1_6p_2s` |
| m_10 | susannah2 | 6 | 2 | `m_10_susannah2_6p_2s` |
| m_11 | collie3 | 6 | 2 | `m_11_collie3_6p_2s` |
| m_12 | alpine2 | 6 | 2 | `m_12_alpine2_6p_2s` |
| m_13 | hillslope | 7 | 2 | `m_13_hillslope_7p_2s` |
| m_14 | topmodel | 7 | 2 | `m_14_topmodel_7p_2s` |
| m_15 | plateau | 8 | 2 | `m_15_plateau_8p_2s` |
| m_16 | newzealand2 | 8 | 2 | `m_16_newzealand2_8p_2s` |
| m_17 | penman | 4 | 3 | `m_17_penman_4p_3s` |
| m_18 | simhyd | 7 | 3 | `m_18_simhyd_7p_3s` |
| m_19 | australia | 8 | 3 | `m_19_australia_8p_3s` |
| m_20 | gsfb | 8 | 3 | `m_20_gsfb_8p_3s` |
| m_21 | flexb | 9 | 3 | `m_21_flexb_9p_3s` |
| m_22 | vic | 10 | 3 | `m_22_vic_10p_3s` |
| m_23 | lascam | 24 | 3 | `m_23_lascam_24p_3s` |
| m_24 | mopex1 | 5 | 4 | `m_24_mopex1_5p_4s` |
| m_25 | tcm | 6 | 4 | `m_25_tcm_6p_4s` |
| m_26 | flexi | 10 | 4 | `m_26_flexi_10p_4s` |
| m_27 | tank | 12 | 4 | `m_27_tank_12p_4s` |
| m_28 | xinanjiang | 12 | 4 | `m_28_xinanjiang_12p_4s` |
| m_29 | hymod | 5 | 5 | `m_29_hymod_5p_5s` |
| m_30 | mopex2 | 7 | 5 | `m_30_mopex2_7p_5s` |
| m_31 | mopex3 | 8 | 5 | `m_31_mopex3_8p_5s` |
| m_32 | mopex4 | 10 | 5 | `m_32_mopex4_10p_5s` |
| m_33 | sacramento | 11 | 5 | `m_33_sacramento_11p_5s` |
| m_34 | flexis | 12 | 5 | `m_34_flexis_12p_5s` |
| m_35 | mopex5 | 12 | 5 | `m_35_mopex5_12p_5s` |
| m_36 | modhydrolog | 15 | 5 | `m_36_modhydrolog_15p_5s` |
| m_37 | hbv | 15 | 5 | `m_37_hbv_15p_5s` |
| m_38 | tank2 | 16 | 5 | `m_38_tank2_16p_5s` |
| m_39 | mcrm | 16 | 5 | `m_39_mcrm_16p_5s` |
| m_40 | smar | 8 | 6 | `m_40_smar_8p_6s` |
| m_41 | nam | 10 | 6 | `m_41_nam_10p_6s` |
| m_42 | hycymodel | 12 | 6 | `m_42_hycymodel_12p_6s` |
| m_43 | gsmsocont | 12 | 6 | `m_43_gsmsocont_12p_6s` |
| m_44 | echo | 16 | 6 | `m_44_echo_16p_6s` |
| m_45 | prms | 18 | 7 | `m_45_prms_18p_7s` |
| m_46 | classic | 12 | 8 | `m_46_classic_12p_8s` |
| m_47 | IHM19 | 16 | 4 | `m_47_IHM19_16p_4s` |
