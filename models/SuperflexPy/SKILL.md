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

# SuperflexPy (v1.3.2) — Knowledge Infrastructure

**Package**: superflexpy-ki v1.0.0
**Model**: SuperflexPy v1.3.2 — Flexible Conceptual Hydrological Modelling Framework
**Authors**: Marco Dal Molin, Fabrizio Fenicia, Dmitri Kavetski
**Created by**: Hydrocraft / auto_dissect
**Last updated**: 2026-03-25
**Stats**: 4 tools | 5 skill docs | 18 diagnostic triplets | ~2500 lines

---

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
| s7 | Calibration | Python API | Optimize parameters (scipy, spotpy) |
| s8 | Validation | Python API | Compute NSE, KGE, PBIAS on hold-out period |

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

### dk_008: State reset does NOT reset lag function memory

`reset_states()` resets reservoir storage (S0) to initial values but the lag
function state behavior depends on the implementation. After calibration runs,
explicitly reinitialize lag states to `None` to ensure clean simulation.

---

## Pre-Built Models

### GR4J (4 parameters)

**Structure**: InterceptionFilter → ProductionStore → Splitter(90/10) →
[UH1 | UH2] → [RoutingStore | Transparent] → Junction → FluxAggregator

| Parameter | Symbol | Default | Range | Units | Controls |
|-----------|--------|---------|-------|-------|----------|
| PS capacity | x1 | 50.0 | 10–2000 | mm | Production store size |
| Exchange coeff | x2 | 0.1 | -5–5 | mm/d | Groundwater exchange |
| RS capacity | x3 | 20.0 | 1–500 | mm | Routing store size |
| UH time | x4 | 3.5 | 0.5–10 | d | Unit hydrograph base time |
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
| Smax | 50.0 | 10–1000 | mm | UnsaturatedReservoir |
| Ce | 1.0 | 0.1–2.0 | - | UnsaturatedReservoir |
| m | 0.01 | 0.001–1.0 | - | UnsaturatedReservoir |
| beta | 2.0 | 0.5–5.0 | - | UnsaturatedReservoir |
| k | 0.01 | 0.001–1.0 | 1/d | PowerReservoir |
| alpha | 2.5 | 1.0–5.0 | - | PowerReservoir |

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
| 3 | x4 | 0.5–10 d | High | Controls peak timing |
| 4 | x2 | -5–5 mm/d | Medium | Positive = import, negative = export |

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
| dt_018 | silent | unit_conversion | x2 exchange coefficient sign convention |

See `diagnostics/triplets.yaml` for full symptom→diagnosis→remedy entries.

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
    └── triplets.yaml               # 18 diagnostic triplets
```
