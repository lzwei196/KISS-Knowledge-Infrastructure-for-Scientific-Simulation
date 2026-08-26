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
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (16 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_parameters.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_parameters.py --help` |
| `tools/generate_yaml_config.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/generate_yaml_config.py --help` |
| `tools/parse_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_output.py --help` |
| `tools/run_pydeltarcm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_pydeltarcm.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# PyDeltaRCM v2.2.0 — Knowledge Infrastructure

**Package**: `pyDeltaRCM-ki` v1.0.0
**Model**: pyDeltaRCM v2.2.0 — Reduced-Complexity Delta Model
**Domain**: Geomorphology / Delta Evolution / Sediment Transport
**Authors**: Andrew J. Moodie, Jayaram Hariharan, Eric Barefoot, Paola Passalacqua
**Paper**: Moodie et al. (2021), JOSS, 6(64), 3398
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 15+ diagnostic triplets
**Validation status**: `tested` (default delta, 5 timesteps)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for meteorological forcing documentation.
See `data_ki/USGS_Sediment/SKILL.md` for suspended sediment observations.


## Overview

PyDeltaRCM is a computationally efficient, open-source numerical delta model based on the original DeltaRCM (Reduced-Complexity Model) design by Man Liang (Liang et al., 2015). It simulates river delta formation and evolution through:

- **Weighted random walk** water routing (parcels follow probability-weighted paths)
- **Sediment transport** via sand (bedload) and mud (suspended) parcel routing
- **Topographic evolution** through deposition and erosion
- **Basin subsidence** (optional, configurable onset time and rate)
- **Sea level rise** (configurable rate in m/s of model time)
- **Stratigraphy recording** (sand fraction at each saved timestep)

The model operates on a 2D rectangular grid with a single inlet channel, routing water and sediment parcels from the inlet into a receiving basin. Each timestep represents one bankfull flood event; real-world time conversion uses an intermittency factor (If).

**Key difference from hydrological models**: PyDeltaRCM is a morphodynamic model, not a rainfall-runoff model. It does NOT take meteorological forcing. Instead, it generates its own water and sediment discharge from prescribed inlet conditions (velocity u0, depth h0, channel width N0, sediment concentration C0).

---

## Installation

### From PyPI

```bash
pip install pyDeltaRCM
```

### From Source

```bash
git clone https://github.com/DeltaRCM/pyDeltaRCM.git
cd pyDeltaRCM
pip install -e .
```

### Dependencies

```
matplotlib>=3.6.1   # Plotting
scipy>=1.5          # Sparse matrix, ndimage
netCDF4             # Output file I/O
pyyaml>=5.1         # Configuration parsing
numba               # JIT-compiled routing kernels
numpy               # Array operations
```

### Python Version

Requires Python >= 3.11. Tested on 3.11, 3.12, 3.13.

---

## Execution

### CLI

```bash
# Run with a YAML config file
pyDeltaRCM --config my_config.yml

# Shorthand
python -m pyDeltaRCM --config my_config.yml
```

### Python API (recommended)

```python
import pyDeltaRCM

# Initialize from YAML
delta = pyDeltaRCM.DeltaModel(input_file='my_config.yml')

# Or with keyword arguments (no YAML needed)
delta = pyDeltaRCM.DeltaModel(
    out_dir='output_test',
    Length=5000, Width=10000, dx=50,
    h0=5.0, u0=1.0, N0_meters=250,
    save_eta_grids=True, save_dt=86400
)

# Run for N timesteps
for t in range(100):
    delta.update()

# Finalize
delta.finalize()
```

### Preprocessor (batch/ensemble runs)

```python
import pyDeltaRCM

pp = pyDeltaRCM.Preprocessor('batch_config.yml')
pp.run_jobs()
```

The Preprocessor supports `matrix`, `set`, and `ensemble` YAML keywords for parameter sweeps and ensemble simulations, with optional parallel execution.

---

## Pipeline (7 Stages)

| # | Stage | Method/Tool | Description |
|---|-------|-------------|-------------|
| 0 | Configuration | YAML file or kwargs | Define domain geometry, inlet conditions, output settings |
| 1 | Initialization | `DeltaModel.__init__()` | Parse config, create domain, init arrays, open NetCDF |
| 2 | Water routing | `route_water()` | Weighted random walk for Np_water parcels, compute free surface |
| 3 | Sediment routing | `route_sediment()` | Route sand (bedload) and mud (suspended) parcels |
| 4 | Subsidence | `apply_subsidence()` | Optional basin subsidence (sigma field) |
| 5 | Timestep finalization | `finalize_timestep()` | Flooding correction, sea level update |
| 6 | Output | `output_data()` | Save grids/figures to NetCDF at save_dt intervals |

### Timestep Structure

Each call to `delta.update()` executes stages 2-6 in sequence:
1. `solve_water_and_sediment_timestep()` → water routing (itermax iterations) + sediment routing
2. `apply_subsidence()` → optional subsidence
3. `finalize_timestep()` → boundary conditions, sea level rise
4. Time increment: `self._time += self.dt`
5. `output_data()` → save if save interval reached
6. `output_checkpoint()` → checkpoint if enabled

---

## Input: YAML Configuration

The model is configured via a YAML file. All parameters have defaults in `default.yml`.

### Domain Geometry

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| `Length` | 5000 | m | Domain length (parallel to inlet) |
| `Width` | 10000 | m | Domain width (perpendicular to inlet) |
| `dx` | 50 | m | Cell face length (grid resolution) |
| `L0_meters` | 150 | m | Inlet channel length |
| `N0_meters` | 250 | m | Inlet channel width |
| `S0` | 0.00015 | - | Characteristic topset slope (dimensionless) |

### Inlet Flow Conditions

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| `u0` | 1.0 | m/s | Reference inlet velocity |
| `h0` | 5.0 | m | Reference inlet depth |
| `hb` | null (=h0) | m | Basin depth |
| `C0_percent` | 0.1 | % | Sediment concentration (as %) |
| `f_bedload` | 0.5 | - | Fraction of sediment as bedload (0-1) |

### Sea Level and Subsidence

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| `H_SL` | 0.0 | m | Initial sea level elevation |
| `SLR` | 0.0 | m/s | Sea level rise rate (model time) |
| `toggle_subsidence` | False | - | Enable/disable subsidence |
| `subsidence_rate` | 2e-9 | m/s | Maximum subsidence rate |
| `start_subsidence` | 216000 | s | Time to begin subsidence |

### Routing Parameters

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| `Np_water` | 2000 | - | Number of water parcels |
| `Np_sed` | 2000 | - | Number of sediment parcels |
| `itermax` | 3 | - | Water routing iterations per timestep |
| `theta_water` | 1.0 | - | Water routing depth weighting |
| `coeff_theta_sand` | 2.0 | - | Sand routing depth weight multiplier |
| `coeff_theta_mud` | 1.0 | - | Mud routing depth weight multiplier |

### Output Controls

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| `out_dir` | 'deltaRCM_Output' | - | Output directory name |
| `save_dt` | 86400 | s | Output save interval (seconds of model time) |
| `save_eta_grids` | False | - | Save topography grids to NetCDF |
| `save_stage_grids` | False | - | Save water stage grids |
| `save_depth_grids` | False | - | Save water depth grids |
| `save_discharge_grids` | False | - | Save water discharge grids |
| `save_velocity_grids` | False | - | Save velocity grids |
| `save_sedflux_grids` | False | - | Save sediment flux grids |
| `save_sandfrac_grids` | False | - | Save sand fraction grids |
| `save_eta_figs` | False | - | Save topography figures |
| `save_checkpoint` | False | - | Enable checkpoint saving |
| `checkpoint_dt` | null | s | Checkpoint save interval |

---

## 6. Output Description

Output is saved to `<out_dir>/pyDeltaRCM_output.nc`.

This section restates `dag.yaml`; if this body and the dag disagree, the dag is the source of truth.

**Headline output** (`validation_rank: 1` in `dag.yaml`):

> `discharge` — Water-discharge magnitude (CF long_name channel_water_flowing__volume_rate). (`m3/s`)

Other dag outputs: `eta`, `stage`, `depth`, `velocity`, `sedflux`, `sandfrac`, `strata_sand_frac`.

| Output variable (dag `var`) | Rank | File | Unit | Description |
|-----------------------------|------|------|------|-------------|
| `discharge` | 1 | `pyDeltaRCM_output.nc (save_discharge_grids)` | `m3/s` | Water-discharge magnitude (CF long_name channel_water_flowing__volume_rate). |
| `stage` | 2 | `pyDeltaRCM_output.nc (save_stage_grids)` | `m` | Water-surface elevation reconstructed from the weighted-random-walk free-surface scheme. |
| `eta` | 3 | `pyDeltaRCM_output.nc (save_eta_grids)` | `m` | Bed (topographic) elevation field; the primary morphodynamic state defining delta planform and topography. |
| `depth` | 4 | `pyDeltaRCM_output.nc (save_depth_grids)` | `m` | Water flow depth, depth = max(stage - eta, 0). |
| `velocity` | 5 | `pyDeltaRCM_output.nc (save_velocity_grids)` | `m/s` | Water-flow velocity magnitude uw = sqrt(ux^2 + uy^2), clamped to u_max = 2*u0. |
| `sedflux` | 6 | `pyDeltaRCM_output.nc (save_sedflux_grids)` | `m3/s` | Sediment flux field qs (combined sand + mud transport). |
| `sandfrac` | 7 | `pyDeltaRCM_output.nc (save_sandfrac_grids)` | `-` | Surface bed sand fraction (0-1) from active-layer mixing during deposition. |
| `strata_sand_frac` | 8 | `pyDeltaRCM_output.nc (stratigraphy) / reconstructed from eta + sandfrac` | `-` | Stratigraphic (subsurface) sand fraction recorded at each bed elevation over time; reconstructable from saved eta + sandfrac surfaces. |

### Dimensions
- `seconds` (or `time` in legacy mode): unlimited, model time in seconds
- `x`: grid x-coordinates (Length / dx cells)
- `y`: grid y-coordinates (Width / dx cells)

### Variables (depending on save flags)

| Variable | Dimensions | Unit | Description |
|----------|-----------|------|-------------|
| `eta` | (time, x, y) | m | Bed elevation |
| `stage` | (time, x, y) | m | Water surface elevation |
| `depth` | (time, x, y) | m | Water depth |
| `discharge` | (time, x, y) | m3/s | Water discharge magnitude |
| `velocity` | (time, x, y) | m/s | Flow velocity magnitude |
| `sedflux` | (time, x, y) | m3/s | Sediment flux |
| `sandfrac` | (time, x, y) | - | Sand fraction (0-1) |
| `strata_depth` | (time, x, y) | m | Stratigraphy elevation |
| `strata_sand_frac` | (time, x, y) | - | Stratigraphy sand fraction |

### Metadata
- `pyDeltaRCM_version`: version string
- All input parameters stored as global attributes

---

## Derived Parameters (Computed Internally)

These are not set by users but are critical for understanding model behavior:

| Parameter | Formula | Unit | Description |
|-----------|---------|------|-------------|
| `dt` | `dVs / Qs0` | s | Model timestep |
| `Qw0` | `u0 * h0 * N0 * dx` | m³/s | Total water discharge |
| `Qs0` | `Qw0 * C0` | m³/s | Total sediment discharge |
| `dVs` | `0.1 * N0² * V0` | m³ | Sediment volume per timestep |
| `V0` | `h0 * dx²` | m³ | Reference cell volume |
| `gamma` | `g * S0 * dx / u0²` | - | Water routing weight coefficient |
| `C0` | `C0_percent / 100` | - | Sediment concentration (fraction) |
| `stepmax` | `2 * (L + W)` | cells | Max parcel walk steps |

---

## 8. Unit Conversion Table (Unit Table)

PyDeltaRCM is a morphodynamic delta model and has no meteorological forcing conversion table: `dag.yaml` declares `inputs.forcing: []`. The model uses YAML parameters and writes selected NetCDF grids. The table below documents the KI's critical model-side units and output units; exact I/O shapes remain in `docs/format_spec.yaml`.

| Variable or control | Source unit (verified) | Model/output unit | Factor | Type |
|---------------------|------------------------|-------------------|--------|------|
| Meteorological forcing | none (`inputs.forcing: []`) | none | n/a | not applicable |
| `Length`, `Width`, `dx`, `L0_meters`, `N0_meters` | user-provided meters | `m` | x1 | multiplicative |
| `u0` | user-provided velocity | `m/s` | x1 | multiplicative |
| `h0`, `hb`, `H_SL` | user-provided elevation/depth | `m` | x1 | multiplicative |
| `C0_percent` | percent | internal fraction `C0 = C0_percent / 100` | /100 | multiplicative |
| `f_bedload` | fraction (0-1) | fraction (0-1) | x1 | multiplicative |
| `SLR`, `subsidence_rate` | user must provide m/s of model time | `m/s (model time)` | x1 | multiplicative |
| `start_subsidence`, `save_dt` | user must provide seconds of model time | `s (model time)` | x1 | multiplicative |
| `discharge` output | model NetCDF `save_discharge_grids` | `m3/s` | x1 | output unit |
| `eta`, `stage`, `depth` outputs | model NetCDF grids | `m` | x1 | output unit |
| `velocity` output | model NetCDF `save_velocity_grids` | `m/s` | x1 | output unit |
| `sedflux` output | model NetCDF `save_sedflux_grids` | `m3/s` | x1 | output unit |
| `sandfrac`, `strata_sand_frac` outputs | model NetCDF / stratigraphy | `-` | x1 | output unit |

### Unit Trap Table

These unit conversions and constraints are critical for correct model behavior:

| Parameter | Expected Unit | Common Mistake | Effect of Mistake |
|-----------|--------------|----------------|-------------------|
| `Length`, `Width` | meters | Using km | Domain 1000x too small |
| `dx` | meters | Must be < Length and < Width | ValueError at startup |
| `u0` | m/s | Using cm/s | 100x too slow, unrealistic morphology |
| `h0` | meters | Using cm | 100x too shallow, dry delta |
| `SLR` | m/s (model time) | Using mm/yr | Must convert: mm/yr ÷ (365.25*86400*If) |
| `subsidence_rate` | m/s (model time) | Using mm/yr | Same conversion as SLR |
| `C0_percent` | % (0.01-1.0 typical) | Using fraction 0.001 | 100x too little sediment |
| `save_dt` | seconds (model time) | Using days | Pass days*86400 |
| `f_bedload` | fraction (0-1) | Using percentage | Crash if > 1 |
| `sand_frac_bc` | fraction (0-1) | Using percentage | Initial sand fraction wrong |
| `start_subsidence` | seconds (model time) | Using years | Convert: years * 365.25 * 86400 * If |
| `gamma` | dimensionless | If > 0.1, instability | Adjust S0, dx, or u0 |

### Time Conversion

PyDeltaRCM simulates bankfull conditions. To convert model time to real time:

```
real_time = model_time / If
```

Where `If` is the intermittency factor (fraction of time the river is at bankfull, typically 0.01-0.1).

Example: 1 year of model time at If=0.05 represents 20 years of real time.

---

## 11. Validated Results

This section restates `docs/validation_convention.yaml` and `knowledge_infrastructure.yaml`; do not substitute remembered thresholds. The convention file wins for pass bands, and null bands are written as `no cited threshold`.

### Validation Summary

| Source | Field | Value |
|--------|-------|-------|
| `knowledge_infrastructure.yaml` | validation tier | `validated` |
| `knowledge_infrastructure.yaml` | tier justification | `measured: NSE=1.000, KGE=0.999, R=1.000, 2 scorecard(s)` |
| `knowledge_infrastructure.yaml` | best_nse | `0.99999` |
| `knowledge_infrastructure.yaml` | best_kge | `0.999` |
| `knowledge_infrastructure.yaml` | best_r | `0.99999` |

### Performance Metrics - Convention Bars

Headline metric for the dag rank-1 output:

> Bar for `discharge` (`csi`, direction `maximize`, convention `cites: []`): satisfactory: no cited threshold; good: no cited threshold; very_good: no cited threshold. Achieved CSI is not recorded in `SKILL.md`, so this body gives no pass/fail verdict.

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band | Convention cites |
|--------------|--------|-----------|-------------------|-----------|----------------|------------------|
| `discharge` | `csi` | maximize | no cited threshold | no cited threshold | no cited threshold | `[]` |
| `eta` | `csi` | maximize | no cited threshold | no cited threshold | no cited threshold | `[]` |
| `stage` | `csi` | maximize | no cited threshold | no cited threshold | no cited threshold | `[]` |

The convention also states that `discharge` is conventionally assessed as channel-network flux partition and directionality, not absolute spatial CSI, until a fetched threshold exists.

---

## Tools Reference

| Tool | Script | Purpose |
|------|--------|---------|
| `generate_yaml_config` | `tools/generate_yaml_config.py` | Generate YAML config from parameters |
| `convert_parameters` | `tools/convert_parameters.py` | Convert real-world units to model units |
| `run_pyDeltaRCM` | `tools/run_pydeltarcm.py` | Execute model with preflight checks |
| `parse_output` | `tools/parse_output.py` | Extract results from NetCDF to CSV/plots |

---

## Customization via Hooks

PyDeltaRCM provides a hook system for subclassing. Each model operation has a `hook_<operation>` method that is called before the operation:

| Hook | Called Before |
|------|-------------|
| `hook_import_files` | Configuration parsing |
| `hook_process_input_to_model` | Parameter assignment |
| `hook_create_other_variables` | Derived variable creation |
| `hook_create_domain` | Domain initialization |
| `hook_after_create_domain` | After domain creation |
| `hook_route_water` | Water routing |
| `hook_after_route_water` | After water routing |
| `hook_route_sediment` | Sediment routing |
| `hook_after_route_sediment` | After sediment routing |
| `hook_solve_water_and_sediment_timestep` | Full water+sed timestep |
| `hook_apply_subsidence` | Subsidence application |
| `hook_finalize_timestep` | Timestep finalization |
| `hook_after_finalize_timestep` | After timestep finalization |
| `hook_output_data` | Data output |
| `hook_output_checkpoint` | Checkpoint output |
| `hook_init_output_file` | NetCDF file creation |
| `hook_load_checkpoint` | Checkpoint loading |

### Example Subclass

```python
from pyDeltaRCM import DeltaModel

class MyDelta(DeltaModel):
    def hook_after_route_water(self):
        # Custom analysis after each water routing
        self.max_depth_history.append(self.depth.max())
```

---

## Preprocessor: Batch Runs

### Matrix Expansion

```yaml
out_dir: 'sensitivity_study'
Length: 5000
Width: 10000
matrix:
  u0: [0.5, 1.0, 1.5, 2.0]
  h0: [3.0, 5.0, 7.0]
# Creates 4 x 3 = 12 jobs
```

### Set Expansion

```yaml
out_dir: 'scenarios'
set:
  - {u0: 0.5, h0: 3.0, SLR: 0.0}
  - {u0: 1.0, h0: 5.0, SLR: 1e-8}
  - {u0: 1.5, h0: 7.0, SLR: 5e-8}
# Creates exactly 3 jobs
```

### Ensemble

```yaml
out_dir: 'ensemble_study'
ensemble: 10
matrix:
  u0: [0.5, 1.0]
# Creates 2 x 10 = 20 jobs with random seeds
```

### Parallel Execution

```yaml
parallel: 4   # number of parallel processes
```

---

## Key Model Equations

### Water Routing Weight

```
w_i = exp(-gamma * max(0, (stage_i - stage_current) / dx)) * depth_i^theta_water
```

### Sediment Deposition (mud)

```
dep = 1  if  |u| < U_dep_mud
ero = 1  if  |u| > U_ero_mud
```

### Timestep

```
dt = dVs / Qs0 = (0.1 * N0^2 * h0 * dx^2) / (u0 * h0 * N0 * dx * C0_percent/100)
```

### Gamma (stability parameter)

```
gamma = g * S0 * dx / u0^2
```

If gamma > 0.1, the model may be numerically unstable. Reduce dx, reduce S0, or increase u0.

---

## Common Configurations

### Small Test Run (fast, ~seconds)

```yaml
out_dir: 'test_run'
Length: 2500
Width: 5000
dx: 50
save_eta_grids: true
save_dt: 86400
```

### Publication-Quality Run

```yaml
out_dir: 'pub_run'
Length: 10000
Width: 20000
dx: 25
Np_water: 5000
Np_sed: 5000
itermax: 5
save_eta_grids: true
save_depth_grids: true
save_velocity_grids: true
save_sandfrac_grids: true
save_dt: 86400
```

### Sea Level Rise Scenario

```yaml
out_dir: 'slr_scenario'
Length: 5000
Width: 10000
SLR: 5e-9
# Note: SLR is in m/s of model time. With If=0.05:
# Real rate = 5e-9 m/s * 86400 s/day * 365.25 day/yr / If
#           = 3.15 mm/yr real-world equivalent
```

---

## File Structure

```
pyDeltaRCM/
├── model.py           # DeltaModel class (main entry point)
├── preprocessor.py    # Preprocessor for batch/ensemble runs
├── init_tools.py      # Domain creation, config parsing, NetCDF setup
├── iteration_tools.py # Timestep operations, output, stratigraphy
├── water_tools.py     # Water parcel routing
├── sed_tools.py       # Sediment parcel routing (sand + mud)
├── shared_tools.py    # Utilities, random seed, parcel helpers
├── hook_tools.py      # Hook method definitions
├── debug_tools.py     # Debugging utilities
├── default.yml        # Default parameter values
└── _version.py        # Version string
```
