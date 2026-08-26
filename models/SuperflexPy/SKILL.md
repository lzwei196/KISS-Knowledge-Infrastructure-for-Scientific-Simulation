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
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (21 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (17 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |
| what past runs learned | `.kdt_evolution.jsonl` | append-only memory of previous runs and fixes on this KI. |

*Projected 2026-08-21 from the KI's actual contents — 10 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing.py --help` |
| `tools/convert_parameters.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_parameters.py --help` |
| `tools/parse_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output.py --help` |
| `tools/run_superflexpy.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_superflexpy.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# SuperflexPy (v1.3.2) — Knowledge Infrastructure

**Package**: superflexpy-ki v1.0.0
**Model**: SuperflexPy v1.3.2 — Flexible Conceptual Hydrological Modelling Framework
**Authors**: Marco Dal Molin, Fabrizio Fenicia, Dmitri Kavetski
**Created by**: Hydrocraft / auto_dissect
**Last updated**: 2026-03-25
**Stats**: 4 tools | 5 skill docs | 21 diagnostic triplets | ~2800 lines

---

## WHICH PYTHON — read this before you run anything

**The interpreter named in the projected tool index above CANNOT run these tools.**
`KISSPATH_PYTHON_ENV/bin/python` has no `superflexpy`.
The only interpreter on this machine that does is the model's own work venv:

```bash
SFP=KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/SuperflexPy/venv/bin/python
$SFP KISSPATH_KI_ROOT/SuperflexPy/knowledge_infrastructure/tools/run_superflexpy.py --help
```

`preflight_check.py` already resolves this (it probes both and picks the one that
imports `superflexpy`) — run it first and use the interpreter it reports.
That venv has numpy 1.24.4 / numba 0.57.1 / scipy / pandas / xarray / netCDF4,
but **not** `ki_tools_common` — `parse_output.py` adds the canonical checkout to
`sys.path` itself, and any script of your own must do the same:

```python
sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
```

Its `netCDF4` reads Caravan files fine, while `python_env`'s raises
`OSError: [Errno -101] NetCDF: HDF error` on every one of them.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: unit documentation and known traps live in
`ki_tools_common` (`load_forcing`, `soil_utils`) — **not** in `data_ki/<X>/tools/`.
Those `data_ki/CMFD/SKILL.md`, `data_ki/HWSD/SKILL.md`, `data_ki/ObservedQ/SKILL.md`
references are stale KDT-4 paths; KDT 5.0 removed tools from `data_ki`.

### Caravan / GRDC-Caravan (the bound observation for this model)

A Caravan per-gauge `.nc` is the ideal input for a lumped SuperflexPy model: it
already carries **basin-averaged** ERA5-Land forcing and the gauge's observed
discharge on one daily axis, so no basin averaging or area conversion is needed.

```bash
$SFP tools/convert_forcing.py --format caravan \
    --input KISSPATH_DATA/observed_data/dischargeandwatershed/GRDC-Caravan-extension-nc/timeseries/netcdf/grdc/GRDC_6503201.nc \
    --start 1979-01-01 --end 1990-12-31 --area 1517.1 --pet-min 0 \
    --output forcing.json
```

| Caravan variable | Meaning | Unit | Trap |
|---|---|---|---|
| `total_precipitation_sum` | basin-mean P | **mm/d** | no `units` attribute on the variable |
| `potential_evaporation_sum` | basin-mean PET | **mm/d**, positive = demand | already sign-flipped by Caravan; goes slightly negative on condensation days — pass `--pet-min 0` (dt_021) |
| `streamflow` | observed discharge | **mm/d, basin-averaged — NOT m³/s** | the file's global `Units` attribute documents every ERA5 field and says *nothing* about `streamflow`; applying an area conversion is a silent area-squared error |

**Verify the unit claim, don't take it on faith**: GRDC_1159100 (Orange R. at
Vioolsdrif, 786,038 km²) has mean `streamflow` 0.0248 → 225 m³/s, matching the
published GRDC mean.

**PET product bias (dt_020)** — ERA5-Land PET is a well-watered potential and in
humid maritime catchments exceeds P. GR4J's `InterceptionFilter` removes
`min(P, PET)` first, so raw Caravan PET can cap the model below the *observed*
runoff. On the Irish gauges: P 995, PET 1208, Q_obs 604 mm/yr — interception
alone removes 444 mm/yr, leaving a 551 mm/yr ceiling under a 604 mm/yr
observation. Calibrate a PET coefficient: `--free-params ... cpet` for GR4J,
`Ce` for HBV (calibrated values 0.44 and 0.39 on the same catchment).


## Overview

SuperflexPy is an open-source Python framework for building flexible, conceptual,
distributed hydrological models. Unlike monolithic rainfall-runoff models, SuperflexPy
provides a **component-based architecture** with four hierarchical levels — Elements,
Units, Nodes, and Networks — allowing modelers to assemble arbitrary model structures
from simple lumped configurations to complex semi-distributed catchment networks.

The framework ships with pre-built implementations of well-known models (GR4J, HBV,
HYMOD) while supporting custom element creation. All differential equations are solved
numerically using configurable approximators (Explicit/Implicit Euler, Runge-Kutta 4)
with pluggable root finders (Pegasus, Newton). Numba JIT compilation provides optional
performance acceleration.

**Publication**: Dal Molin et al. (2021), *Geoscientific Model Development*, 14, 7047–7072,
doi:10.5194/gmd-14-7047-2021

**Repository**: https://github.com/dalmo1991/superflexPy
**Documentation**: https://superflexpy.readthedocs.io

---

## Installation

### From PyPI (recommended)

```bash
python3 -m venv venv
source venv/bin/activate
pip install superflexpy
```

### From source

```bash
python3 -m venv venv
source venv/bin/activate
cd source/repo
pip install -e .
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| numpy   | 1.24.3  | Array operations, numerical computation |
| numba   | 0.57.1  | JIT compilation for ODE solvers |

### Optional dependencies (for examples/calibration)

| Package | Purpose |
|---------|---------|
| pandas  | Data I/O for CSV/tabular forcing data |
| scipy   | Optimization for parameter calibration |
| matplotlib | Plotting results |
| spotpy  | Advanced calibration algorithms |

---

## Architecture: Four-Level Hierarchy

SuperflexPy organizes hydrological models into four nested levels:

### Level 1: Elements (Atomic Components)

Elements are the smallest building blocks. Types include:

| Element Type | Base Class | Description | Examples |
|-------------|------------|-------------|----------|
| Reservoir   | `ODEsElement` | Storage governed by dS/dt = In - Out | PowerReservoir, UnsaturatedReservoir, ProductionStore, RoutingStore |
| Lag Function | `LagElement` | Time-delay convolution | UnitHydrograph1, UnitHydrograph2 |
| Connector   | `BaseElement` | Route/split/merge fluxes | Splitter, Junction, Transparent |
| Filter      | `BaseElement` | Transform fluxes without storage | InterceptionFilter, FluxAggregator |

### Level 2: Units (Element Networks)

A Unit connects Elements into a **directed acyclic graph (DAG)** organized in layers.
Elements in the same layer can run in parallel. A Unit represents a single model
structure (e.g., one complete GR4J or HBV model).

### Level 3: Nodes (Parallel Units)

A Node aggregates multiple Units running in parallel with fractional weights,
representing Hydrological Response Units (HRUs) within a sub-catchment.

### Level 4: Network (Routed Nodes)

A Network connects Nodes in a tree topology for semi-distributed modelling,
routing accumulated flows from headwater to outlet.

---

## Pipeline (8 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| s1 | Forcing Preparation | `convert_forcing.py` | Convert global/station data to numpy arrays (mm/d) |
| s2 | Parameter Setup | `convert_parameters.py` | Prepare parameters from soil/land-use data |
| s3 | Model Assembly | Python API | Build Element→Unit→Node→Network hierarchy |
| s4 | Initial Conditions | Python API | Set initial states (S0, lag arrays) |
| s5 | Model Execution | `run_superflexpy.py` | Run simulation via `get_output()` |
| s6 | Output Extraction | `parse_output.py` | Extract streamflow, states to CSV |
| s7 | Calibration | `run_superflexpy.py --calibrate` | Differential evolution on a date-bounded calibration window |
| s8 | Validation | `parse_output.py --val-start/--val-end` | NSE/KGE/PBIAS from `ki_tools_common.metrics.all_metrics` on the hold-out period |

**s7/s8 are TOOL stages, not "write your own loop".** They were documented as
"Python API" until 2026-08-21, which is why agents kept hand-rolling calibration
loops — and a hand-rolled loop that omits `model.reset_states()` between trials
is silently wrong (dt_019: the same parameter vector re-scores up to 5.45 mm/d
differently). Use the tools.

```bash
# s1 -> s8, one gauge
$SFP tools/convert_forcing.py --format caravan --input <gauge>.nc \
      --start 1979-01-01 --end 1990-12-31 --pet-min 0 --output forcing.json
$SFP tools/convert_parameters.py --model gr4j --output params.json
$SFP tools/run_superflexpy.py --model gr4j --forcing forcing.json \
      --params-json params.json --architecture numba --diagnostics \
      --calibrate --cal-start 1981-01-01 --cal-end 1985-12-31 \
      --val-start 1986-01-01 --val-end 1990-12-31 \
      --free-params x1 x3 x4 x2 cpet --output results.json
$SFP tools/parse_output.py --input results.json --output series.csv --warmup 731 \
      --cal-start 1981-01-01 --cal-end 1985-12-31 \
      --val-start 1986-01-01 --val-end 1990-12-31 --metrics-json metrics.json
```

`--params-json` is the s2 → s5 hand-off: it takes both the values AND the
calibration ranges that `convert_parameters.py` publishes, so the search space
is the one s2 declared rather than a range retyped by hand.
`--architecture numba` is ~30x faster than `python` and gives bit-identical
results (verified) — always use it for calibration.
`--diagnostics` emits dag outputs `AET`, `S` and `F` plus a term-by-term water
balance built from the model's own element fluxes (not from a residual, which
would always close and prove nothing).

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|-------|---------|
| convert_forcing | s1 | tools/convert_forcing.py | ~200 | Convert CSV/station forcing to model input arrays |
| convert_parameters | s2 | tools/convert_parameters.py | ~180 | Map soil/land-use to model parameters |
| run_superflexpy | s5 | tools/run_superflexpy.py | ~220 | Execute model and save outputs |
| parse_output | s6 | tools/parse_output.py | ~170 | Parse raw output to standardized CSV |

---

## Input Format and Units

### Forcing Data

SuperflexPy accepts forcing as **lists of numpy arrays**. Each array is one flux
time series with length = number of timesteps.

| Variable | Symbol | Unit | Array Index | Notes |
|----------|--------|------|-------------|-------|
| Precipitation | P | mm/d (or mm/timestep) | 0 or 1 | Total rainfall |
| Potential Evapotranspiration | PET | mm/d (or mm/timestep) | 0 or 1 | Depends on element |
| Temperature | T | °C | varies | Only if snow module used |

**CRITICAL**: Input order varies by element type:
- `InterceptionFilter`: [PET, P] — PET is index 0
- `UnsaturatedReservoir`: [P, PET] — P is index 0
- `PowerReservoir`: [P] — single input
- `Unit` (e.g., GR4J): [PET, P] — follows first element's convention

### Input File Format (test data)

The test data uses space-separated format with 6-line header:

```
Maimai data courtesy Jeff McDonnell
1.0  ! stepsize (d)
ST1: All data in mm/d
ST2
ST3
*  ! list directed format ok here
year, month, day, hour, min, QC, P (mm/d), E (mm/d), Q_obs (mm/d)
1985  1  2  0  0  0  1.000000e-001  0.000000e+000  2.646000e-001
```

### Parameter Format

Parameters are set as Python dictionaries:

```python
parameters = {
    'element_id_param_name': value,  # Prefixed format
}
# Example for GR4J Unit:
model.set_parameters({
    'model_ps_x1': 300.0,        # Production store capacity [mm]
    'model_ps_alpha': 2.0,       # PS exponent [-]
    'model_rs_x2': 0.5,          # Exchange coefficient [mm/d]
    'model_rs_x3': 50.0,         # Routing store capacity [mm]
    'model_uh1_lag-time': 2.0,   # UH1 lag [d]
    'model_uh2_lag-time': 4.0,   # UH2 lag [d]
})
```

---

## Output Format

### Direct API Output

`model.get_output()` returns a **list of numpy arrays** — one per output flux.
For most single-outlet models, the result is `[Q_array]` where Q is in mm/timestep.

### Network Output

`network.get_output()` returns a **dict** mapping node IDs to lists of output arrays.

### Reference Results Format (CSV)

```csv
# Q_FR, S_FR
3.159780e-05, 9.996840e-02
3.166701e-01, 3.983298e+00
```

Column order is model-specific. For the FR test: streamflow Q (mm/d), storage S (mm).

---

## Output Description

Source: `dag.yaml`. The dag is the authority for observable outputs and validation
rank; if this section ever disagrees with `dag.yaml`, the dag wins.

**Headline output**: `Q_sim` is the dag's rank-1 variable, so this model is judged by
simulated total streamflow at the catchment / Unit outlet.

> `Q_sim` — Simulated total streamflow at the catchment / Unit outlet; model.get_output() returns a list of numpy arrays (one per output flux). (`mm/d`)

| Output variable (dag `var`) | Rank / role | Unit | Description |
|---|---:|---|---|
| `Q_sim` | 1 | mm/d | Simulated total streamflow at the catchment / Unit outlet; model.get_output() returns a list of numpy arrays (one per output flux). |
| `Network_Q` | dag output | see `dag.yaml` | Listed as an additional dag output. |
| `AET` | dag output | see `dag.yaml` | Listed as an additional dag output. |
| `S` | dag output | see `dag.yaml` | Listed as an additional dag output. |
| `F` | dag output | see `dag.yaml` | Listed as an additional dag output. |

---

## Unit Conversion Table

Exact shapes live in `docs/format_spec.yaml`. This table restates the units already
documented in this KI body and the dag headline output; verify raw source metadata
before adding new conversions.

| Variable | Source unit documented here | Model / output unit | Factor | Type |
|---|---|---|---|---|
| Precipitation (`P`) | mm/d | mm/d | x1 | already model-ready |
| Potential evapotranspiration (`PET`) | mm/d | mm/d | x1 | already model-ready |
| Temperature (`T`) | degC | degC | x1 | already model-ready when snow modules use it |
| Timestep (`dt`) | days (float) | days (float) | x1 | already model-ready |
| Storage (`S`, `S0`) | mm | mm | x1 | already model-ready |
| Catchment area | km2 | km2 | x1 | already model-ready for Node area inputs |
| HRU weights | fraction [0,1] | fraction [0,1] | x1 | already model-ready |
| `Q_sim` | model output | mm/d | x1 | dag rank-1 output |

---

## Unit Trap Table

These are the most common unit-related errors that cause silent model failures.

| # | Trap ID | Variable | Expected Unit | Common Wrong Unit | Impact |
|---|---------|----------|---------------|-------------------|--------|
| 1 | dt_001 | Precipitation | mm/d | m/d, mm/h, in/d | Flows off by 1000x, 24x, or 25.4x |
| 2 | dt_002 | PET | mm/d | mm/month, W/m² | Severe water balance error |
| 3 | dt_003 | Timestep | days (float) | hours, seconds | ODE solver mismatch |
| 4 | dt_004 | Storage (S0) | mm | m, cm | Initial transient or instability |
| 5 | dt_005 | x1 (PS capacity) | mm | m, cm | Ps fraction (S/x1) corrupted |
| 6 | dt_006 | x3 (RS capacity) | mm | m | Qr equation breaks |
| 7 | dt_007 | x4 (lag time) | d | h, timesteps | UH weights malformed |
| 8 | dt_008 | Area (Node) | km² | m², ha | Network routing flux wrong |
| 9 | dt_009 | Weights (Node) | fraction [0,1] | percentage [0,100] | Outputs scaled 100x |
| 10 | dt_010 | x2 (exchange) | mm/d | mm/h | Exchange flux wrong |

---

## Critical Domain Knowledge

### dk_001: Input array order is element-specific (SILENT)

The order of fluxes in `set_input()` varies between element types. The
`InterceptionFilter` expects `[PET, P]` while `UnsaturatedReservoir` expects
`[P, PET]`. Swapping these produces nonsensical results with no error message.
Always check the element's `set_input()` docstring.

### dk_002: Timestep must match forcing resolution (SILENT)

`element.set_timestep(dt)` sets the ODE integration step in **days** (float).
If forcing is daily, `dt=1.0`. If hourly, `dt=1/24`. A mismatch means the
ODE solver integrates over the wrong time interval, producing silently wrong
storage dynamics.

### dk_003: Numba JIT compilation delay on first call

The first call to `get_output()` with Numba-based solvers triggers JIT
compilation, which can take 5–30 seconds. Subsequent calls are fast. This is
not a hang — do not kill the process.

### dk_004: Parameter prefixing follows hierarchy

When accessing parameters through a Unit or higher, names are automatically
prefixed: `unit_id_element_id_param_name`. Getting this wrong raises a
`KeyError`. Use `model.get_parameters_name()` to discover the actual names.

### dk_005: Lag states must be initialized as None

For `LagElement` subclasses (UnitHydrograph1/2), the initial state must be
`{'lag': None}`. The framework auto-creates the lag array from the lag-time
parameter. Providing a pre-allocated array of wrong length causes crashes.

### dk_006: Splitter weight/direction matrices must be consistent

The `Splitter` element uses `weight` and `direction` matrices to distribute
fluxes. Dimension mismatches between these matrices and the number of
upstream/downstream elements cause cryptic index errors. The weight matrix
shape is `[n_downstream][n_upstream_fluxes]` and direction is
`[n_downstream][n_upstream_fluxes]`.

### dk_007: Network topology must be a tree (no cycles, no branching)

The `Network` class only supports tree topologies: each node has at most one
downstream connection. Cycles cause infinite loops. Multiple downstream
connections are not supported. Use `Splitter` elements within a Unit instead.

### dk_008: EVERY repeat `get_output()` needs `reset_states()` first (SILENT)

Superseded measurement, 2026-08-21 — the hedge that used to be here ("the lag
function state behavior depends on the implementation") is resolved:

* `Unit.reset_states()` DOES restore both reservoir storage and the
  `LagElement` memory (`element.py:712` re-deepcopies a `None` init state back
  to `None`). You do **not** need to reinitialize lag states by hand.
* But you MUST call it. SuperflexPy carries state forward across calls, so a
  second `get_output()` with **identical parameters** continues from the first
  run's storage. Measured on GR4J over 500 days: max difference 5.45 mm/d
  without the reset, exactly 0.0 with it.
* Consequence for calibration: without the reset, every trial starts from
  whatever the previous trial left behind, so the optimiser is fitting
  evaluation ORDER. Nothing errors. See dt_019.

The package's own example fixes the ordering — `set_parameters` →
`reset_states` → `get_output` (`examples/02_calibrate_a_model.ipynb`).
`run_superflexpy.py --calibrate` already does this; prefer it to a hand loop.

---

## Pre-Built Models

### GR4J (4 parameters)

**Structure**: InterceptionFilter → ProductionStore → Splitter(90/10) →
[UH1 | UH2] → [RoutingStore | Transparent] → Junction → FluxAggregator

Defaults below are the ones the TOOLS actually ship (`convert_parameters.py`
`MODEL_DEFAULTS` and `run_superflexpy.py` `build_model`), corrected 2026-08-21 —
this table previously said x1=50, x3=20, x4=3.5, which matched neither tool.

| Parameter | Symbol | Default | Range | Units | Controls |
|-----------|--------|---------|-------|-------|----------|
| PS capacity | x1 | 350.0 | 10–2000 | mm | Production store size |
| Exchange coeff | x2 | 0.0 | -5–5 | mm/d | Groundwater exchange (**+ = LOSS**, see dt_018) |
| RS capacity | x3 | 90.0 | 1–500 | mm | Routing store size |
| UH time | x4 | 1.7 | 0.5–10 | d | Unit hydrograph base time; sets `uh1_lag-time = x4` AND `uh2_lag-time = 2·x4` |
| PS exponent | alpha | 2.0 | fixed | - | Evap/precip partition |
| Perc exponent | beta | 5.0 | fixed | - | Percolation rate |
| Perc coeff | ni | 4/9 | fixed | - | Percolation scaling |
| RS exponent | gamma | 5.0 | fixed | - | Routing outflow |
| Exchange exp | omega | 3.5 | fixed | - | Exchange flux |

**Input**: `[PET, P]` in mm/d
**Output**: `[Q]` in mm/d

### HBV-style (UnsaturatedReservoir + PowerReservoir)

| Parameter | Default | Range | Units | Element |
|-----------|---------|-------|-------|---------|
| Smax | 200.0 | 10–1000 | mm | UnsaturatedReservoir |
| Ce | 1.0 | 0.1–2.0 | - | UnsaturatedReservoir — this IS the PET correction coefficient; with a reanalysis PET product it is a first-order lever, not a nuisance (dt_020) |
| m | 0.01 | 0.001–1.0 | - | UnsaturatedReservoir |
| beta | 2.0 | 0.5–5.0 | - | UnsaturatedReservoir |
| k | 0.05 | 0.001–1.0 | 1/d | PowerReservoir |
| alpha | 2.5 | 1.0–5.0 | - | PowerReservoir |

Defaults corrected 2026-08-21 to match `convert_parameters.py` /
`run_superflexpy.py` (this table said Smax 50.0 and k 0.01, matching neither).
HBV has **no interception filter**, so unlike GR4J it does not lose
`min(P, PET)` off the top — which is why it needs `Ce` rather than `cpet`.

**Input**: `[P, PET]` in mm/d
**Output**: `[Q]` in mm/d

### HYMOD

| Parameter | Default | Range | Units | Element |
|-----------|---------|-------|-------|---------|
| Smax | 50.0 | 10–500 | mm | UpperZone |
| m | 0.01 | 0.001–1.0 | - | UpperZone |
| beta | 2.0 | 0.5–5.0 | - | UpperZone |
| k | 0.1 | 0.01–1.0 | 1/d | LinearReservoir (×3 + lower) |

---

## Numerical Solvers

| Solver | Type | Stability | Speed | Use Case |
|--------|------|-----------|-------|----------|
| ExplicitEuler | Explicit | Conditional | Fast | Quick tests, smooth forcings |
| ImplicitEuler | Implicit | Unconditional | Medium | Production runs, stiff ODEs |
| RungeKutta4 | Explicit | Conditional | Slow | High accuracy needs |

| Root Finder | Method | Architecture | Notes |
|------------|--------|-------------|-------|
| PegasusPython | Bracketing | Python | Robust, default choice |
| PegasusNumba | Bracketing | Numba | Fast, JIT-compiled |

---

## Calibration Parameters (Priority Order)

For GR4J — calibrate these first, in this order:

| Priority | Parameter | Range | Sensitivity | Notes |
|----------|-----------|-------|-------------|-------|
| 1 | x1 | 10–2000 mm | Very High | Controls production/infiltration split |
| 2 | x3 | 1–500 mm | High | Controls routing store depletion rate |
| 3 | x4 | 0.5–10 d | High | Controls peak timing. **Not a SuperflexPy parameter name** — use the `x4` alias in `run_superflexpy.py`, which sets `gr4j_uh1_lag-time = x4` and `gr4j_uh2_lag-time = 2·x4` |
| 4 | x2 | -5–5 mm/d | Medium | **Positive = EXPORT (loss), negative = IMPORT (gain)** — corrected 2026-08-21 against `RoutingStore.get_output()` ("Exchange flux (F), positive if loss"); the old "positive = import" reading here and in dt_018 was inverted |
| 5 | cpet | 0.2–2.0 – | High with a reanalysis PET product | PET-forcing correction; GR4J has no internal PET coefficient (dt_020) |

For HBV-style:

| Priority | Parameter | Range | Sensitivity |
|----------|-----------|-------|-------------|
| 1 | Smax | 10–1000 mm | Very High |
| 2 | beta | 0.5–5.0 | High |
| 3 | k | 0.001–1.0 | High |
| 4 | alpha | 1.0–5.0 | Medium |
| 5 | Ce | 0.1–2.0 | Medium |
| 6 | m | 0.001–1.0 | Low |

---

## Quick Start

```python
import numpy as np
from superflexpy.implementation.models.gr4j import model

# Load forcing data
P = np.array([0.1, 4.2, 0.0, 13.2, 2.4, 14.3, 4.4, 1.7, 0.0, 50.6])  # mm/d
PET = np.zeros(10)  # mm/d

# Set timestep
model.set_timestep(1.0)  # daily

# Set input: [PET, P] for GR4J
model.set_input([PET, P])

# Run model
Q = model.get_output()  # Returns [Q_array] in mm/d

# Access states
states = model.get_states()
param_names = model.get_parameters_name()

# Reset for next run
model.reset_states()
```

### Running unit tests

```bash
cd source/repo
python -m pytest test/unittest/01_FR.py -v
```

---

## Coupling Points

| # | Source | Target | Variable | Notes |
|---|--------|--------|----------|-------|
| 1 | Climate reanalysis | SuperflexPy | P, PET (mm/d) | Must match timestep |
| 2 | Soil databases (HWSD) | SuperflexPy | Smax, beta | Pedotransfer functions |
| 3 | SuperflexPy | Routing model | Q (mm/d or m³/s) | Multiply by area for volumetric |
| 4 | SuperflexPy | Water quality | Q partitioned by path | Use splitter outputs |
| 5 | Calibration framework | SuperflexPy | Parameters dict | Via set_parameters() |

---

## Data Requirements

| Data | Source | Format | Units |
|------|--------|--------|-------|
| Precipitation | Station/gridded | numpy array | mm/d |
| PET | Calculated/gridded | numpy array | mm/d |
| Observed Q | Gauging station | numpy array | mm/d |
| Catchment area | GIS | scalar float | km² |
| HRU weights | GIS/analysis | list of floats | fraction [0,1] |

---

## Validated Results

Validated result values are not stated in the extracted KI facts. When a run is
evaluated, judge it against `docs/validation_convention.yaml`; do not substitute
remembered thresholds.

### Performance Metrics — judged against the field's bar, not intuition

Source: `docs/validation_convention.yaml`. Every cited threshold below carries the
citation key provided by the convention. A null convention band is written as
`no cited threshold`.

| Dag variable | Metric | Direction | Convention bar |
|---|---|---|---|
| `Q_sim` | NSE | maximize | very_good >= 0.8 (`moriasi2015`); good >= 0.7 (`moriasi2015`); satisfactory >= 0.5 (`moriasi2015`) |
| `Q_sim` | PBIAS | zero_centered | very_good band = 5.0 (`moriasi2015`); good band = 10.0 (`moriasi2015`); satisfactory band = 15.0 (`moriasi2015`) |
| `Q_sim` | PBIAS | zero_centered | satisfactory: no cited threshold |
| `Network_Q` | NSE | maximize | very_good >= 0.8 (`moriasi2015`); good >= 0.7 (`moriasi2015`); satisfactory >= 0.5 (`moriasi2015`) |
| `Network_Q` | PBIAS | zero_centered | very_good band = 5.0 (`moriasi2015`); good band = 10.0 (`moriasi2015`); satisfactory band = 15.0 (`moriasi2015`) |

| Metric | Calibration | Validation | Full Period | Bar (convention, cited) |
|---|---|---|---|---|
| NSE for `Q_sim` | not stated in extracted facts | not stated in extracted facts | not stated in extracted facts | satisfactory >= 0.5 (`moriasi2015`), good >= 0.7 (`moriasi2015`), very_good >= 0.8 (`moriasi2015`) |
| PBIAS for `Q_sim` | not stated in extracted facts | not stated in extracted facts | not stated in extracted facts | satisfactory band = 15.0 (`moriasi2015`), good band = 10.0 (`moriasi2015`), very_good band = 5.0 (`moriasi2015`); duplicate satisfactory row: no cited threshold |

### Data Replacement Tracking

| Component | Source | Status | Notes |
|---|---|---|---|
| Forcing | Pipeline | Pending | Use `convert_forcing.py`; units documented as mm/d. |
| Parameters | Pipeline | Pending | Use `convert_parameters.py`; parameter units are documented in the model sections above. |
| Model execution | SuperflexPy package | Pending | Must run the real package; `Q_sim` is the rank-1 output. |
| Output parsing | Pipeline | Pending | Use `parse_output.py`; bind validation to `Q_sim` first. |

---

## Diagnostic Triplets Summary

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | silent | unit_conversion | Precipitation units wrong (m vs mm) |
| dt_002 | silent | unit_conversion | PET in mm/month instead of mm/d |
| dt_003 | silent | unit_conversion | Timestep mismatch with forcing |
| dt_004 | silent | unit_conversion | Storage initial state wrong units |
| dt_005 | silent | parameter_format | Input array order swapped |
| dt_006 | fatal | parameter_format | Parameter prefix wrong |
| dt_007 | fatal | parameter_format | Lag state not set to None |
| dt_008 | silent | parameter_format | Splitter weight matrix wrong shape |
| dt_009 | degraded | runtime | Numba JIT first-call delay |
| dt_010 | fatal | runtime | Negative storage from explicit solver |
| dt_011 | silent | architecture | Network has cycle |
| dt_012 | silent | architecture | Node weights don't sum to 1 |
| dt_013 | silent | unit_conversion | Area in m² instead of km² |
| dt_014 | silent | unit_conversion | Node weights as percentages |
| dt_015 | degraded | runtime | Root finder non-convergence |
| dt_016 | silent | parameter_format | Time-varying param wrong length |
| dt_017 | fatal | dependency | Numba version incompatible with numpy |
| dt_018 | silent | unit_conversion | x2 exchange sign: **positive = LOSS** (entry corrected 2026-08-21; it previously said the opposite) |
| dt_019 | silent | runtime | Repeat `get_output()` without `reset_states()` — calibration fits evaluation order |
| dt_020 | silent | unit_conversion | Reanalysis PET exceeds the demand the structure needs; calibrate `cpet` (GR4J) / `Ce` (HBV) |
| dt_021 | silent | unit_conversion | Negative reanalysis PET makes GR4J's interception filter ADD precipitation; use `--pet-min 0` |

See `diagnostics/triplets.yaml` for full symptom→diagnosis→remedy entries (21 entries; dt_019-dt_021 added 2026-08-21, dt_018 corrected).

---

## File Structure

```
ki/
├── SKILL.md                        # This file — main reference
├── tools/
│   ├── convert_forcing.py          # s1: Forcing data converter
│   ├── convert_parameters.py       # s2: Parameter converter
│   ├── run_superflexpy.py          # s5: Model execution wrapper
│   └── parse_output.py             # s6: Output parser
├── docs/
│   ├── s1_forcing_preparation.md   # Forcing preparation skill
│   ├── s2_parameter_setup.md       # Parameter configuration skill
│   ├── s3_model_assembly.md        # Model assembly skill
│   ├── s5_model_execution.md       # Model execution skill
│   └── s6_output_extraction.md     # Output parsing skill
└── diagnostics/
    └── triplets.yaml               # 21 diagnostic triplets
```
