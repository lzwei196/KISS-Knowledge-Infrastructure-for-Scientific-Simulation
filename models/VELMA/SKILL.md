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
| before running a stage | `docs/s*_*.md` (7 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (30 entries; 001-024 written for the SURROGATE, 025-030 for the real engine) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity = the REAL EPA VELMA 2.1 engine (the Python SURROGATE's separate contract is `docs/surrogate_velma_4layer_dag.yaml`): every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (12 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |
| what past runs learned | `.kdt_evolution.jsonl` | append-only memory of previous runs and fixes on this KI. |

*Projected 2026-10-07 from the KI's actual contents — 10 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_velma_weather_from_source.py` (**REAL engine weather drivers**) | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_velma_weather_from_source.py --help` |
| `tools/convert_forcing_to_velma.py` (**SURROGATE input, not VELMA**) | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_velma.py --help` |
| `tools/convert_soil_to_velma.py` (**SURROGATE input, not VELMA**) | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_velma.py --help` |
| `tools/parse_output_velma.py` (**SURROGATE output, not VELMA**) | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output_velma.py --help` |
| `tools/run_velma.py` (**SURROGATE, not VELMA**) | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_velma.py --help` |
| `tools/run_velma_engine.py` (**REAL engine, default run route**) | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_velma_engine.py --help` |

*6 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# VELMA Knowledge Infrastructure

**Package**: hydrocraft-velma v1.0.0
**Model**: VELMA (Visualizing Ecosystem Land Management Assessments)
**Domain**: Spatially distributed ecohydrology (water, carbon, nitrogen) on a DEM grid
**Language**: Java — the REAL EPA VELMA 2.1 engine (`tools/run_velma_engine.py`).
Python `tools/run_velma.py` is a SURROGATE (lumped 4-layer stand-in), not VELMA.

## REAL ENGINE — EPA VELMA 2.1 (use this for every result)

The real engine is installed: `KISSPATH_HOME/engine_builds_20261006/VELMA/run_velma_headless.sh`
(= `java -Djava.awt.headless=true -Xmx8g -cp jars/JVelma.jar gov.epa.velmasimulator.VelmaSimulatorCmdLine`,
reports `VELMA_2.1.1.0`). Build log and official example run:
`KISSPATH_HOME/engine_builds_20261006/VELMA/BUILD_LOG.md`.

**SURROGATE WARNING.** `tools/run_velma.py` (and `convert_forcing_to_velma.py` /
`convert_soil_to_velma.py` / `parse_output_velma.py`, which feed it) is a Python
re-implementation written for this KI: one lumped 4-layer bucket with linear
reservoirs. It is NOT the EPA model and its numbers must never be reported as
VELMA results. Every section below whose heading says SURROGATE (1, 2's Python part,
4, 6b, 7, 8, 9, 10, 11, 12) describes that stand-in, not EPA VELMA. Its full I/O
contract is `docs/surrogate_velma_4layer_dag.yaml`; `dag.yaml` describes the real engine.

### Real-engine tools

| Stage | Tool | What it does |
|---|---|---|
| weather drivers | `tools/build_velma_weather_from_source.py` | cmfd / mswx / nasa_power at --lat/--lon via `ki_tools_common.load_forcing` -> one-column daily files: P **mm/day**, mean air T **deg C** (never Kelvin). MSWX read SERIALLY (exfat), P+Tair only, per-year cache (resumable). |
| run + check | `tools/run_velma_engine.py` | drives the engine headless with `--kv` overrides (the xml is never edited), does the 2.0->2.1 humus migration, and judges success from the log + `DailyResults.csv`. Writes `velma_engine_summary.json` and `velma_daily_runoff.csv` (date, runoff_mm_d, Q_sim_m3s). Exit 0 ok / 2 refused input / 3 engine failed / 4 exit 0 but checks failed. |

### Official example (reproduce first)

```bash
PY=KISSPATH_PYTHON_ENV/bin/python
W=<work dir>; mkdir -p $W/inputs
cp -r KISSPATH_HOME/engine_builds_20261006/VELMA/runs/inputs/BlueRiver_Example $W/inputs/
$PY tools/run_velma_engine.py \
  --config $W/inputs/BlueRiver_Example/BlueRiver_WS10_Example_Configuration.xml \
  --input-root $W/inputs --output-root $W/out
# expect: status success, engine_nse = 0.7954119608437563, RMSE 3.6089 mm/d,
#         14610 days 1969-2008, ~60 s; DailyResults.csv byte-identical to the build-log run
#         (sha256 d690b67f2af3acd11721eb27f5c7e5f2d6ad8155cadd9f645ae670634b053ce8)
```

### Validated results (real engine)

| Case | Weather | Period | Engine NSE (mm/d) | Notes |
|---|---|---|---|---|
| Official BlueRiver_Example, HJA WS10 (OR) | HJA station P/T shipped with the example | 1969-2008 | 0.7954 (RMSE 3.609 mm/d) | 2026-10-06, `run_velma_engine.py`, matches the build log exactly; official parameters, no calibration |
| HJA WS10 real case | MSWX (nearest 0.1 deg cell), P + Tair via `build_velma_weather_from_source.py` | 1981-2008 scored (1980 warm-up) | 0.5933 | **Validation** (no calibration by us). Daily Q, 10,227 days: NSE 0.593, KGE 0.560, PBIAS -14.3 %, r 0.787 -> meets the convention bands (NSE >= 0.5, abs PBIAS <= 15 %). Spin-up 1969-79 on station weather (1975 clearcut), state carried into 1980. Same window with station weather: NSE 0.796. EPA set the parameters up for WS10 with station weather, so this tests the weather input, not a new site. Reproduce: `KISSPATH_HOME/ki_fix_campaign/kdt_real_engine/review_VELMA/score_ws10_mswx.py` |

Mean annual (official example): rain+snow 2217 mm, simulated runoff 1715 mm (observed 1483 mm), ET 698 mm.

### Real-engine traps (see triplets dt_velma_025..030)

- **2.0 config on the 2.1 engine stops on day 1** with `NaN TRAPPED! nitrificationAmount=NaN`:
  in 2.1 `humusCtoN`, `initialHumusCarbon`, `humusNmaxDecay` are SOIL keys.
  `run_velma_engine.py` copies them from the cover block (default `--humus-migration auto`);
  with `--humus-migration off` the same run exits 3 (proven).
- **Weather files are deg C and mm/day, one value per row, no header, row 1 = forcing_start-01-01**,
  every day present. The Kelvin JSON of `convert_forcing_to_velma.py` is for the surrogate only.
  `run_velma_engine.py` refuses temperatures outside -60..50 (Kelvin) and short files.
- **Observed runoff (`input_runoff`) and stream chemistry files are read BY ROW from
  `forcing_start`** — when you move forcing_start, cut these files to the same first day.
- **Spin-up / restart**: `--end-state-dir D` saves the end-of-run spatial maps; the next run
  takes `--start-state-dir D` (VELMA manual 2.0 sec. 20-21). Tested at WS10: a 1969-78 spin-up +
  1979-80 restart matches the continuous run to 0.06 mm/d runoff. Use it when the new weather
  product starts after the site history you need (e.g. the 1975 WS10 clearcut, MSWX from 1980).
- **Exit code 0 is not enough**: the tool also needs `Simulation run completed`, no `FAIL!`/
  `NaN TRAPPED`/exception lines, and one DailyResults row per day.
- **Outputs**: `Runoff_All(mm/day)_Delineated_Average` is the outlet runoff the engine
  scores against `input_runoff` (mm/day over the DELINEATED area, from ReachSummary.csv;
  WS10: 162 cells x 30 m = 14.6 ha vs 10.2 ha gauged). `Soil_Moisture(mm)_..._Layer_n`
  columns hold a volumetric fraction (start value = porosity), despite the "(mm)" label.
- **Water balance**: the engine's own outputs do not close: official example 1969-2008
  P 2217 - ET 698 - Q 1715 = -196 mm/yr (-8.8 % of P). This is engine accounting, not
  a unit error in your inputs; report it, do not "fix" it.
- The output folder `<output-root>/<run_index>` must not exist (use `--overwrite`).
- MSWX `P/P_1979.nc` has a faulty time axis: the shared loader refuses 1979; start MSWX runs in 1980.

---

**License**: Public domain (USEPA)
**Created**: 2026-03-30

The facts block below is the OLD Python SURROGATE's (Bengbu, Huai River); it is not a VELMA result.

**Surrogate validation**: Bengbu station (51080), Huai River Basin, China (1980--1990)

| Metric | Value |
|--------|-------|
| Tools (surrogate era) | 4 |
| Pipeline stages | 7 |
| Diagnostic triplets (surrogate era) | 14 |
| Validation basin | Huai River at Bengbu |
| Calibration NSE (surrogate) | 0.80 |
| Validation KGE (surrogate) | 0.80 |

---

## Repair scope and runtime identity

`tools/convert_forcing_to_velma.py` now rejects missing fields, dates, active-grid
values and invalid physical values before writing output. It performs no filling,
interpolation, date intersection, truncation or rounding of forcing values.
The calendar must contain every day of every requested year, including leap days.
Already-daily input is required; subdaily records must be validated and aggregated
upstream. All polygon features are reprojected from their declared CRS and used;
no selected grid-cell centres is an error. Spatial means retain the existing equal
cell weights and require all selected values to be present.

The hydrology equations, JSON schema and Kelvin temperature contract described
below belong to the local **Python analytic approximation** in `run_velma.py`.
They are not evidence of equivalence to EPA's original distributed Java model.
The historical Bengbu performance numbers below apply only to that local
approximation and have not been independently reproduced by this repair.
The KI preflight now checks the REAL engine (launcher, JVelma.jar banner,
`run_velma_engine.py`) as critical, and the Python surrogate as non-critical.

EPA Java uses precipitation in mm and air temperature in Celsius in its weather
files, plus the native spatial maps and XML configuration. The converter's
explicit `--solar-mode unused` omits solar (never fabricates it) for preparing
P/T inputs for that native route. Export `temp_K - 273.15` to the native Celsius
file exactly once; the JSON itself is not a native Java input. Do not pass the
solar-omitting JSON to the Python runner. (2026-10-07: `dag.yaml` now describes the
real engine; the surrogate's contract moved to `docs/surrogate_velma_4layer_dag.yaml`.)

Official documentation: [required inputs](https://usepa.github.io/VELMA_Public/version/2.1/getting_started/Required_Input_Files.html),
[Java example](https://usepa.github.io/VELMA_Public/version/2.1/getting_started/Quickstart.html),
[command line](https://usepa.github.io/VELMA_Public/version/2.1/getting_started/VelmaSimRunner.html).

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.
See `data_ki/ObservedQ/SKILL.md` for observed discharge data.


## 1. Overview of the Python SURROGATE (NOT EPA VELMA)

EPA VELMA itself is a spatially distributed ecohydrological model (DEM grid,
4-layer soil column per cell, coupled water, carbon and nitrogen); `dag.yaml`
describes it. Everything in this section is the Python SURROGATE
(`tools/run_velma.py`), a lumped stand-in written for this KI.

Surrogate physics:

- **Multi-layer soil water balance (4 layers)**: Tracks water storage in 4
  vertical layers (L1: 0-10 cm, L2: 10-50 cm, L3: 50-150 cm, L4: 150-300 cm).
  Each layer has independently specified porosity, field capacity, wilting point,
  and hydraulic conductivity. Layer capacities are `porosity * thickness` (mm).

- **Vertical percolation**: Gravity-driven drainage from each layer to the one
  below, operating on the excess above field capacity:
  `perc_i = (SW_i - FC_i) * perc_rate_i` when `SW_i > FC_i`.
  If a receiving layer saturates, the excess returns upward as interflow.
  Percolation rates decrease with depth (L1: ~0.5/d, L2: ~0.3/d, L3: ~0.1/d).

- **Lateral subsurface flow (Darcy-based)**: Each layer generates lateral flow
  proportional to its excess above field capacity:
  `lat_i = (SW_i - FC_i) * klat_i`. Coefficients decrease with depth
  (L1: ~0.15/d, L2: ~0.08/d, L3: ~0.03/d, L4: ~0.005/d), reflecting
  decreasing hydraulic gradient and conductivity.

- **Snow accumulation / melt (degree-day method)**: Precipitation falls as
  snow when temperature < T_snow (default 273.15 K). Melt occurs when
  temperature > T_melt: `melt = min(SWE, DDF * (T - T_melt))` where DDF is
  the degree-day factor (mm/K/day, typically 1-8).

- **Evapotranspiration (Hargreaves/Priestley-Taylor hybrid)**: PET is estimated
  from temperature and solar radiation using a modified Hargreaves approach:
  `PET = 1.26 * s_ratio * Rn_mm * pet_scale` where `s_ratio` varies with
  temperature (0.3 + 0.025*T_C, capped at 0.8) and `Rn_mm` converts solar
  radiation to equivalent evaporation (W/m2 * 0.0864 / 2.45). Actual ET is
  extracted from layers L1-L3 weighted by root fractions (0.30, 0.40, 0.25,
  0.05), with a linear stress function below field capacity.

- **Surface runoff**: Saturation excess mechanism -- runoff occurs when L1
  water content exceeds layer capacity, plus a direct runoff fraction
  (f_direct, ~0.05) representing impervious area / channel precipitation.

- **Dual reservoir routing**: Total runoff is split between fast and slow
  parallel linear reservoirs:
  `S_fast += Q_total * split; q_fast = S_fast * k_fast`
  `S_slow += Q_total * (1-split); q_slow = S_slow * k_slow`
  where k_fast (~0.3/d) and k_slow (~0.02/d) are recession constants.

Key characteristics:
- 4-layer vertical soil column (not spatially distributed)
- 14 calibration parameters (see Section 7)
- Driven by daily precipitation (mm/d), temperature (K), solar radiation (W/m2)
- Temperature passed in Kelvin; the model converts to Celsius internally (line 454)
- PET computed internally via modified Hargreaves
- Output: daily discharge (m3/s)

**Important**: VELMA is designed for small-to-medium catchments with explicit
spatial cells. Application as a lumped model for large basins (>10,000 km2) is
a simplification of its distributed architecture.

---

## 2. Installation

### Python SURROGATE (not VELMA)

The VELMA Java source is available from USEPA but requires specific runtime
configuration. This KI provides a Python analytic reimplementation of the
core hydrological physics.

```bash
# No compilation needed -- pure Python
pip install numpy pandas xarray geopandas scipy matplotlib shapely netCDF4
```

### Real EPA VELMA 2.1 engine (installed)

Installed at `KISSPATH_HOME/engine_builds_20261006/VELMA/` (Java 21, `jars/JVelma.jar`,
launcher `run_velma_headless.sh`). Always run it through `tools/run_velma_engine.py`
(see REAL ENGINE above); `preflight_check.py` checks the launcher, the jar banner and the tool.

### Dependencies

| Component      | Required | Purpose                                   |
|----------------|----------|-------------------------------------------|
| numpy          | Yes      | Numerical computation                     |
| pandas         | Yes      | Time series handling                      |
| xarray         | Yes      | NetCDF forcing data                       |
| geopandas      | Yes      | Shapefile basin masking                   |
| netCDF4        | Yes      | Reading CMFD data                         |
| scipy          | Yes      | Calibration (differential_evolution)      |
| matplotlib     | Optional | Validation plots                          |
| shapely        | Yes      | Geometry operations for basin masking     |

---

## 3. Pipeline

**Real engine pipeline** (use this): `build_velma_weather_from_source.py` -> `run_velma_engine.py`
(official example config + site maps; optional spin-up with `--end-state-dir` / `--start-state-dir`).
The table below is the **Python SURROGATE** pipeline (not VELMA):

| # | Stage                  | Tool                           | Description                                               |
|---|------------------------|--------------------------------|-----------------------------------------------------------|
| 1 | Forcing preparation    | `convert_forcing_to_velma.py`  | CMFD NetCDF to daily precip (mm/d) + temp (K) + srad      |
| 2 | Soil parameter setup   | `convert_soil_to_velma.py`     | HWSD soil data to 4-layer Ksat, porosity, FC, WP          |
| 3 | Model configuration    | (manual)                       | Set basin area, routing params, calibration bounds         |
| 4 | PET computation        | (internal to run_velma.py)     | Modified Hargreaves from temp + srad                       |
| 5 | Execution              | `run_velma.py`                 | Run lumped 4-layer soil hydrology model                    |
| 6 | Output parsing         | `parse_output_velma.py`        | Extract discharge timeseries, compute validation metrics   |
| 7 | Calibration            | `run_velma.py --mode calibrate`| Differential evolution against observed Q                  |

**Parallelism**: Stages 1--2 can run in parallel. Stage 5 depends on 1--2.
Stage 6 depends on 5. Stage 7 is iterative on 5--6.

### Stage documents

Per-stage operating docs live under `docs/`:

- [Stage 1: Forcing preparation](docs/s1_forcing_preparation.md)
- [Stage 2: Soil parameter setup](docs/s2_soil_parameter_setup.md)
- [Stage 3: Model configuration](docs/s3_model_configuration.md)
- [Stage 4: PET computation](docs/s4_pet_computation.md)
- [Stage 5: Execution](docs/s5_execution.md)
- [Stage 6: Output parsing](docs/s6_output_parsing.md)
- [Stage 7: Calibration](docs/s7_calibration.md)

---

## 4. Unit Table and Unit Trap Table (Python SURROGATE inputs)

The REAL engine takes precipitation in mm/day and air temperature in deg C (one value per line); see REAL ENGINE above and dt_velma_026. The rest of this section is the surrogate's.

These unit conversions cause **silent failures** if wrong. VELMA expects
specific units at each interface -- errors propagate without warnings.

| Variable              | Model expects   | Common source unit | Conversion                             | Trap ID |
|-----------------------|-----------------|--------------------|----------------------------------------|---------|
| Precipitation         | **mm/d**        | kg/m2/s (CMFD)     | x 86400                                | dt_001  |
| Precipitation         | **mm/d**        | mm/3h (CMFD)       | sum 8 values per day                   | dt_002  |
| Precipitation         | **mm/d**        | m/d (some GCMs)    | x 1000                                 | dt_003  |
| Temperature           | **K** (internal)| deg C              | + 273.15                               | dt_004  |
| Temperature           | **K** (internal)| deg F              | (F - 32) x 5/9 + 273.15               | dt_005  |
| Solar radiation       | **W/m2**        | MJ/m2/d            | / 0.0864                               | dt_006  |
| Solar radiation       | **W/m2**        | kJ/m2/d            | / 86.4                                 | dt_007  |
| Ksat (per layer)      | **mm/d**        | mm/h (HWSD)        | x 24                                   | dt_008  |
| Ksat (per layer)      | **mm/d**        | cm/h (some tables) | x 240                                  | dt_009  |
| Porosity              | **fraction**    | percent             | / 100                                  | dt_010  |
| Layer thickness       | **mm**          | cm                  | x 10                                   | dt_011  |
| Basin area            | **km2**         | ha                  | / 100                                  | dt_012  |
| Observed Q            | **m3/s**        | mm/d                | x area_km2 x 1e6 / 86400 / 1000       | dt_013  |
| mm/d to m3/s          | conversion      | mm/d over basin     | x area_km2 x 1e6 / 86400 x 1e-3       | dt_014  |

### Unit conversion table

Exact I/O shapes live in `docs/format_spec.yaml`; this table restates the
pipeline-level conversions that agents must verify before execution.

| Variable | Source unit (verified) | Model / output unit | Factor | Type |
|----------|-------------------------|---------------------|--------|------|
| Precipitation | kg/m2/s (CMFD) | mm/d | x 86400 | multiplicative |
| Precipitation | mm/3h (CMFD) | mm/d | sum 8 values per day | aggregation |
| Precipitation | m/d (some GCMs) | mm/d | x 1000 | multiplicative |
| Temperature | deg C | K | + 273.15 | additive |
| Temperature | deg F | K | (F - 32) x 5/9 + 273.15 | affine |
| Solar radiation | MJ/m2/d | W/m2 | / 0.0864 | multiplicative |
| Solar radiation | kJ/m2/d | W/m2 | / 86.4 | multiplicative |
| Ksat (per layer) | mm/h (HWSD) | mm/d | x 24 | multiplicative |
| Ksat (per layer) | cm/h (some tables) | mm/d | x 240 | multiplicative |
| Porosity | percent | fraction | / 100 | multiplicative |
| Layer thickness | cm | mm | x 10 | multiplicative |
| Basin area | ha | km2 | / 100 | multiplicative |
| Observed Q | mm/d | m3/s | x area_km2 x 1e6 / 86400 / 1000 | basin-area conversion |
| Simulated runoff depth | mm/d over basin | m3/s | x area_km2 x 1e6 / 86400 x 1e-3 | basin-area conversion |

**Rule**: If simulated discharge is 86400x too high or too low, precipitation
units are almost certainly wrong (kg/m2/s vs mm/d). If PET is absurdly high
(>50 mm/d), temperature is probably still in Kelvin being subtracted by 273.15
a second time.

**CRITICAL (SURROGATE only)**: the Python surrogate expects temperature in Kelvin (the REAL VELMA engine expects deg C). The surrogate converts to Celsius
internally (line 454 of run_validation.py: `T_C = temp_K - 273.15`). Do NOT
pre-convert temperature to Celsius -- doing so causes negative Kelvin-equivalent
values and zero PET.

---

## 5. Tools Reference

| Tool                       | Stage       | Script                           | Purpose                                         |
|----------------------------|-------------|----------------------------------|-------------------------------------------------|
| `run_velma_engine`         | s5_execute (REAL) | `tools/run_velma_engine.py`  | Run EPA VELMA 2.1 JVelma.jar headless + success checks |
| `build_velma_weather_from_source` | s1_forcing (REAL) | `tools/build_velma_weather_from_source.py` | cmfd/mswx/nasa_power -> engine P (mm/d) + T (deg C) drivers |
| `convert_forcing_to_velma` | s1_forcing (SURROGATE) | `tools/convert_forcing_to_velma.py` | CMFD NetCDF to daily P (mm/d) + T (K) + srad |
| `convert_soil_to_velma`    | s2_params (SURROGATE) | `tools/convert_soil_to_velma.py`    | HWSD to 4-layer soil parameters               |
| `run_velma`                | s5_execute (SURROGATE) | `tools/run_velma.py`     | Python stand-in, NOT VELMA                    |
| `parse_output_velma`       | s6_output (SURROGATE) | `tools/parse_output_velma.py`       | Parse discharge, compute NSE/KGE/PBIAS        |

All tools follow the **validate -> process -> validate** pattern:
1. Parse CLI arguments with `argparse`
2. Validate all inputs (file existence, unit plausibility, range checks)
3. Process (convert, run, parse)
4. Validate outputs (physical plausibility, diagnostic warnings)
5. Return JSON: `{"status": "success/error", "output": {...}, "log": [...]}`

---

## 6. Output Description

**Source**: `dag.yaml` (the REAL engine). The dag is the model's identity; if this section and
`dag.yaml` ever disagree, `dag.yaml` wins and this section is the bug.

**Headline output** (the dag's rank-1 variable -- the one this model is judged by):

> `Q_sim_m3s` -- daily outlet discharge = `Runoff_All(mm/day)_Delineated_Average` x area / 86400 s,
> written by `run_velma_engine.py` to `velma_daily_runoff.csv`; pass `--area-km2 <gauged area>` when
> comparing with a gauge (`m3/s`).

| Output variable (dag `var`) | Rank | Unit | Engine source |
|-----------------------------|------|------|---------------|
| `Q_sim_m3s` | 1 | `m3/s` | `velma_daily_runoff.csv` Q_sim_m3s (from Runoff_All) |
| `mean_runoff_mm_d` | 2 | `mm/d` | DailyResults `Runoff_All(mm/day)_Delineated_Average` (daily) |
| `mean_et_mm_d` | 3 | `mm/d` | DailyResults `ET(mm/day)_Delineated_Average` (daily) |
| `final_sw_mm[4]` | 4 | `m3/m3` | DailyResults `Soil_Moisture(mm)_Delineated_Average_Layer_1..4` -- a FRACTION despite "(mm)" (dt_velma_029) |
| `final_swe_mm` | 5 | `mm` | DailyResults `Snow_Depth(mm)_Delineated_Average` (snow store, mm of water) |

All DailyResults columns are averages over the engine's delineated watershed. The SURROGATE's
outputs (same names, different meaning) are in `docs/surrogate_velma_4layer_dag.yaml`.

---

## 6b. Critical Domain Knowledge (Python SURROGATE)

These non-obvious facts cause silent failures in the SURROGATE pipeline. Each links to a diagnostic triplet. Item 1 (precipitation units) also applies to the real engine's drivers.

1. **dt_001**: CMFD precipitation is in kg/m2/s (= mm/s). Multiply by 86400
   to get mm/d. The explicit constant is `CMFD_PRECIP_KGM2S_TO_MMDAY = 86400.0`.
   Forgetting this makes precipitation ~0.03 mm/d instead of ~2.7 mm/d,
   producing near-zero runoff.

2. **dt_004 / dt_005**: The SURROGATE expects temperature in Kelvin (the real engine: deg C). The model converts
   to Celsius internally for PET computation. If you pass Celsius, the model
   subtracts 273.15 from values like 15, yielding -258 C and zero PET. This
   is a common mistake because most other hydrology models expect Celsius.

3. **dt_006 / dt_007**: Solar radiation in CMFD is in W/m2. If your source
   provides MJ/m2/d, divide by 0.0864. Wrong radiation units cause PET to be
   off by an order of magnitude.

4. **dt_008 / dt_009**: HWSD hydraulic conductivity is often in mm/h or cm/h.
   VELMA needs mm/d for each layer. Using hourly Ks makes percolation rates
   24x too low, causing excessive lateral flow and flashy response.

5. **Percolation cascade**: Water percolates L1->L2->L3->L4 sequentially. If
   a receiving layer saturates, excess returns upward as interflow (lateral
   flow). This bidirectional flow means that deep soil parameters strongly
   affect surface response timing.

6. **Root-weighted ET extraction**: ET is extracted from L1-L3 weighted by root
   fractions (0.30, 0.40, 0.25, 0.05). Each layer's actual ET is further
   stress-limited: full extraction above FC, linearly reduced between FC and WP,
   zero below WP. Setting wrong FC values causes either too much or too little ET.

7. **Snow temperature threshold**: Snow/rain partitioning uses T_snow (K), not
   T_snow (C). Default is 273.15 K = 0 C. If temperature is accidentally in
   Celsius (~15 C) while T_snow is 273.15 K, ALL precipitation becomes snow
   (since 15 < 273.15), producing zero runoff for months.

8. **Dual reservoir split**: The `split` parameter controls fast vs slow routing.
   Values near 1.0 make the model very flashy; values near 0.0 make it very
   sluggish. Typical basins need 0.3-0.7. If peak timing is wrong but volume
   is right, adjust split and k_fast/k_slow.

---

## 7. SURROGATE Parameters (lumped 4-layer stand-in; not EPA VELMA parameters)

| Parameter   | Symbol    | Unit   | Range         | Sensitivity | Description                                |
|-------------|-----------|--------|---------------|-------------|--------------------------------------------|
| PET scale   | pet_scale | --     | [0.3, 2.5]    | High        | Multiplier on Hargreaves PET               |
| Perc rate 1 | perc1     | 1/d    | [0.1, 0.9]    | High        | L1->L2 percolation fraction above FC       |
| Perc rate 2 | perc2     | 1/d    | [0.05, 0.7]   | Medium      | L2->L3 percolation fraction                |
| Perc rate 3 | perc3     | 1/d    | [0.01, 0.5]   | Medium      | L3->L4 percolation fraction                |
| Lat flow 1  | klat1     | 1/d    | [0.01, 0.8]   | Very High   | L1 lateral flow coefficient                |
| Lat flow 2  | klat2     | 1/d    | [0.005, 0.5]  | High        | L2 lateral flow coefficient                |
| Lat flow 3  | klat3     | 1/d    | [0.001, 0.3]  | Medium      | L3 lateral flow coefficient                |
| Lat flow 4  | klat4     | 1/d    | [0.001, 0.1]  | Low         | L4 lateral flow coefficient                |
| Baseflow    | k_base    | 1/d    | [0.001, 0.1]  | Medium      | L4 groundwater recession rate              |
| Fast recess | k_fast    | 1/d    | [0.05, 0.9]   | High        | Fast routing reservoir recession           |
| Slow recess | k_slow    | 1/d    | [0.005, 0.15] | Medium      | Slow routing reservoir recession           |
| Split       | split     | --     | [0.1, 0.9]    | High        | Fraction of runoff to fast reservoir       |
| Direct frac | f_direct  | --     | [0.01, 0.20]  | Low         | Impervious area / direct runoff fraction   |
| Degree-day  | ddf       | mm/K/d | [1.0, 8.0]    | Seasonal    | Snow melt degree-day factor                |

---

## 8. SURROGATE Soil Physics (lumped 4-layer stand-in; not EPA VELMA)

### Layer structure

```
Surface  ─────────────────────────────  0 cm
         │ L1: 0-10 cm  (100 mm)     │  Fast interflow, high root density
         ├────────────────────────────┤ 10 cm
         │ L2: 10-50 cm (400 mm)     │  Main root zone
         ├────────────────────────────┤ 50 cm
         │ L3: 50-150 cm (1000 mm)   │  Deep roots, slow interflow
         ├────────────────────────────┤ 150 cm
         │ L4: 150-300 cm (1500 mm)  │  Groundwater store
         └────────────────────────────┘ 300 cm
```

### Default soil parameters per layer

| Layer | Thickness (mm) | Porosity | FC frac | WP frac | Cap (mm) | FC (mm) | WP (mm) |
|-------|---------------|----------|---------|---------|----------|---------|---------|
| L1    | 100           | 0.45     | 0.55    | 0.20    | 45.0     | 24.8    | 9.0     |
| L2    | 400           | 0.42     | 0.60    | 0.22    | 168.0    | 100.8   | 36.9    |
| L3    | 1000          | 0.38     | 0.65    | 0.25    | 380.0    | 247.0   | 95.0    |
| L4    | 1500          | 0.35     | 0.70    | 0.28    | 525.0    | 367.5   | 147.0   |

### Vertical percolation equation

```
For layers i = 0, 1, 2 (L1->L2->L3->L4):
  excess_i = max(SW_i - FC_i, 0)
  perc_i = excess_i * perc_rate_i
  SW_i -= perc_i
  SW_{i+1} += perc_i
  if SW_{i+1} > Cap_{i+1}:
      backflow = SW_{i+1} - Cap_{i+1}
      SW_{i+1} = Cap_{i+1}
      lateral_flow += backflow   # returned as surface interflow
```

### Lateral flow equation (per layer)

```
For each layer i:
  excess_i = max(SW_i - FC_i, 0)
  lat_i = excess_i * klat_i
  SW_i -= lat_i
  total_lateral += lat_i
```

### Hargreaves PET

```
T_C = temp_K - 273.15
Rn_mm = max(srad_Wm2 * 0.0864 / 2.45, 0)   # W/m2 -> equivalent evaporation mm/d
s_ratio = clip(0.3 + 0.025 * max(T_C, 0), 0, 0.8)
PET = 1.26 * s_ratio * Rn_mm * pet_scale
```

### Snow (degree-day)

```
if T < T_snow (273.15 K):
    SWE += P
    water_input = 0
else:
    water_input = P
    melt = min(SWE, DDF * max(T - T_melt, 0))
    SWE -= melt
    water_input += melt
```

---

## 9. Historical Python SURROGATE results (not VELMA; not revalidated here)

**Basin**: Huai River at Bengbu (Station 51080), China
**Area**: 121,330 km2
**Forcing**: CMFD V0200 0.25-deg daily
**Tier**: analytic (Python reimplementation of VELMA physics)

| Period               | NSE   | KGE   | r     | PBIAS (%) | RMSE (m3/s) |
|----------------------|-------|-------|-------|-----------|-------------|
| Calibration 1981-85  | 0.80  | 0.80  | >0.85 | <10       | --          |
| Validation 1986-90   | >0.60 | >0.60 | >0.75 | <15       | --          |

Calibration method: Differential evolution (scipy), 80 iterations, population 20.
Objective: -(0.5*NSE + 0.5*KGE - 0.002*|PBIAS|) on 1981--1985 calibration period.
Spinup year: 1980.

### Performance bars from validation convention

(The numbers discussed right below are the SURROGATE's Bengbu numbers. The real engine's WS10
result is under REAL ENGINE -> Validated results.)

**Source**: `docs/validation_convention.yaml`. The convention is the authority
for metric direction, pass-bands, and citation keys; if these bars and the
convention ever disagree, the convention wins.

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band | Citation keys |
|--------------|--------|-----------|-------------------|-----------|----------------|---------------|
| `Q_sim_m3s` | nse | maximize | >= 0.5 (`ortuani2020`, `golmohammadi2014`) | >= 0.65 (`ortuani2020`, `golmohammadi2014`) | no cited threshold (`ortuani2020`, `golmohammadi2014`) | `ortuani2020`, `golmohammadi2014` |
| `Q_sim_m3s` | pbias | zero_centered | <= 15.0 absolute PBIAS (`ortuani2020`, `golmohammadi2014`) | <= 10.0 absolute PBIAS (`ortuani2020`, `golmohammadi2014`) | no cited threshold (`ortuani2020`, `golmohammadi2014`) | `ortuani2020`, `golmohammadi2014` |
| `Q_sim_m3s` | pbias | zero_centered | <= 15.0 absolute PBIAS (`ortuani2020`, `golmohammadi2014`) | <= 10.0 absolute PBIAS (`ortuani2020`, `golmohammadi2014`) | no cited threshold (`ortuani2020`, `golmohammadi2014`) | `ortuani2020`, `golmohammadi2014` |
| `mean_et_mm_d` | nse | maximize | >= 0.5 (`ahn2017`) | no cited threshold (`ahn2017`) | no cited threshold (`ahn2017`) | `ahn2017` |

For `Q_sim_m3s`, the reported calibration NSE of 0.80 is above the cited good
threshold of 0.65 (`ortuani2020`, `golmohammadi2014`); the convention provides
no cited very-good threshold for NSE. The reported calibration PBIAS of <10%
is within the cited good absolute-PBIAS threshold of 10.0 (`ortuani2020`,
`golmohammadi2014`); the convention provides no cited very-good threshold for
PBIAS. The validation PBIAS of <15% is within the cited satisfactory
absolute-PBIAS threshold of 15.0 (`ortuani2020`, `golmohammadi2014`).

---

## 10. Coupling Points (Python SURROGATE pipeline)

| Source              | Target              | Variable     | Unit    | Notes                                |
|---------------------|---------------------|--------------|---------|--------------------------------------|
| CMFD/ERA5 NetCDF    | Forcing converter   | Precip       | mm/d    | Basin-average via shapefile mask     |
| CMFD/ERA5 NetCDF    | Forcing converter   | Temperature  | K       | Basin-average; kept in Kelvin        |
| CMFD/ERA5 NetCDF    | Forcing converter   | Solar rad    | W/m2    | Basin-average                        |
| Hargreaves method   | Model internal      | PET          | mm/d    | From temperature (K) + srad (W/m2)  |
| HWSD / SoilGrids    | Soil converter      | Ksat, n, FC  | mm/d, --| Per-layer pedotransfer functions     |
| VELMA output        | Parse output        | Discharge    | m3/s    | Daily at basin outlet                |
| Observed gauge      | Validation          | Discharge    | m3/s    | Bengbu station                       |

---

## 11. Data Requirements (Python SURROGATE pipeline; the real engine needs a VELMA configuration + P/T drivers)

| Data Type            | Source            | Unit          | Required | Path / Notes                              |
|----------------------|-------------------|---------------|----------|-------------------------------------------|
| Precipitation        | CMFD V0200        | kg/m2/s       | Yes      | Convert to mm/d (x 86400)                |
| Temperature          | CMFD V0200        | K             | Yes      | Keep in K (model converts internally)     |
| Solar radiation      | CMFD V0200        | W/m2          | Yes      | For Hargreaves PET computation            |
| Wind speed           | CMFD V0200        | m/s           | Optional | Not used in current PET formulation       |
| Surface pressure     | CMFD V0200        | Pa            | Optional | Not used in current PET formulation       |
| Specific humidity    | CMFD V0200        | kg/kg         | Optional | Not used in current PET formulation       |
| Basin shapefile      | GIS               | --            | Yes      | For spatial masking of gridded data       |
| Observed discharge   | Gauge station     | m3/s          | Optional | For calibration and validation            |
| Soil properties      | HWSD / SoilGrids  | varies        | Optional | For 4-layer parameter estimation          |

---

## 12. Quick Start (Python SURROGATE -- NOT VELMA; for VELMA results use REAL ENGINE above)

```bash
# SURROGATE ONLY. 1. Convert CMFD forcing to the surrogate's Kelvin JSON
python ki/tools/convert_forcing_to_velma.py \
  --forcing-dir /path/to/CMFD/Data_forcing_01dy_025deg \
  --shapefile /path/to/basin.shp \
  --years 1980-1990 \
  --output forcing.json

# 2. Estimate 4-layer soil parameters from HWSD
python ki/tools/convert_soil_to_velma.py \
  --texture "silt loam" \
  --depth-cm 300 \
  --output params.json

# 3. Run model (simulation mode)
python ki/tools/run_velma.py \
  --mode simulate \
  --forcing forcing.json \
  --params params.json \
  --basin-area-km2 121330 \
  --output simulation.json

# 4. Parse output and validate
python ki/tools/parse_output_velma.py \
  --input simulation.json \
  --observed /path/to/observed_Q.csv \
  --output results.csv \
  --metrics-json metrics.json \
  --figure validation.png

# 5. Or run calibration end-to-end
python ki/tools/run_velma.py \
  --mode calibrate \
  --forcing forcing.json \
  --observed /path/to/observed_Q.csv \
  --basin-area-km2 121330 \
  --cal-start 1981-01-01 --cal-end 1985-12-31 \
  --output calibrated.json
```

---

## 13. Diagnostic Triplets Summary (surrogate-era entries; real-engine entries dt_velma_025..030 are listed under REAL ENGINE)

| ID     | Stage      | Failure Domain    | Severity | Symptom                                          |
|--------|------------|-------------------|----------|--------------------------------------------------|
| dt_001 | s1_forcing | unit_conversion   | silent   | Precip 86400x too low (kg/m2/s not mm/d)         |
| dt_002 | s1_forcing | unit_conversion   | silent   | Precip 8x too high (mm/3h not mm/d)              |
| dt_003 | s1_forcing | unit_conversion   | silent   | Precip 1000x too high (m/d not mm/d)             |
| dt_004 | s1_forcing | unit_conversion   | silent   | Temp in C passed to model expecting K -> neg PET |
| dt_005 | s1_forcing | unit_conversion   | silent   | Temp in F gives wrong PET magnitude              |
| dt_006 | s1_forcing | unit_conversion   | silent   | Solar rad in MJ/m2/d not W/m2 -> PET off 10x    |
| dt_007 | s1_forcing | unit_conversion   | silent   | Solar rad in kJ/m2/d not W/m2                    |
| dt_008 | s2_params  | unit_conversion   | silent   | Ks in mm/h not mm/d -- percolation 24x low       |
| dt_009 | s2_params  | unit_conversion   | silent   | Ks in cm/h not mm/d -- percolation 240x low      |
| dt_010 | s2_params  | unit_conversion   | silent   | Porosity in percent not fraction                  |
| dt_011 | s2_params  | unit_conversion   | silent   | Layer thickness in cm not mm                      |
| dt_012 | s2_params  | unit_conversion   | silent   | Area in ha not km2 -- Q conversion wrong          |
| dt_013 | s6_output  | unit_conversion   | silent   | Observed Q in mm/d not m3/s                       |
| dt_014 | s5_execute | conversion_factor | silent   | mm/d to m3/s factor wrong from area error         |

---

## 14. File Structure

```
ki/
  SKILL.md                             # This file -- agent entry point
  tools/
    run_velma_engine.py                # REAL engine: EPA VELMA 2.1 headless + success checks
    build_velma_weather_from_source.py # REAL engine: P (mm/day) + T (deg C) driver files
    convert_forcing_to_velma.py        # SURROGATE Stage 1: CMFD/ERA5 -> daily P, T(K), srad
    convert_soil_to_velma.py           # SURROGATE Stage 2: Soil data -> 4-layer params
    run_velma.py                       # SURROGATE Stage 5: Python lumped 4-layer stand-in (NOT VELMA)
    parse_output_velma.py              # SURROGATE Stage 6: Parse output + metrics
  dag.yaml                             # REAL engine contract (model identity)
  docs/surrogate_velma_4layer_dag.yaml # SURROGATE contract (not VELMA)
```
