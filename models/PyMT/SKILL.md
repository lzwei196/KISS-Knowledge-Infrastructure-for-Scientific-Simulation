---
name: pymt
description: PyMT. Use when the task involves running, configuring, calibrating or interpreting PyMT.
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

# PyMT Knowledge Infrastructure — SKILL.md

```yaml
package:
  name: pymt-ki
  version: 1.0.0
  target_model: PyMT (Python Modeling Toolkit)
  model_version: 1.3.3.dev0
  domain: earth-surface-dynamics / model-coupling-framework
  language: python
  authors: [CSDMS team, mcflugen@gmail.com]
  license: MIT
  validation_status: tested
```

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: Framework models use data from the coupled models.


## 1. Model Overview

### 1.1 What PyMT Is

PyMT (Python Modeling Toolkit) is an open-source Python package developed by the
Community Surface Dynamics Modeling System (CSDMS). It is NOT a single computational
model — it is a **model coupling framework** that wraps and connects any model
exposing the Basic Model Interface (BMI).

**Core capabilities:**
- Wrap BMI-enabled models in a unified Python API
- Couple models across disparate time/space scales
- Exchange data between models via CSDMS Standard Names
- Regrid data between different spatial grids (ESMF-based mappers)
- Write output to NetCDF (CF/UGRID compliant)
- Discover and load models via a plugin/entry-point system

**Domain scope:** Any earth-surface process — hydrology, coastal evolution,
sediment transport, permafrost, climate, biogeochemistry — as long as the
underlying model exposes BMI.

### 1.2 Key Concepts

| Concept | Description |
|---------|-------------|
| **BMI** | Basic Model Interface — standard API: `initialize`, `update`, `finalize`, `get_value`, `set_value` |
| **Standard Names** | CSDMS semantic variable naming (e.g., `sea_surface_water_wave__height`) |
| **Component** | High-level wrapper around a BMI model with events, ports, and printers |
| **BmiCap** | The bridge class that wraps a raw BMI object with PyMT features |
| **ModelCollection** | Registry that discovers installed model plugins via entry points |
| **Mapper** | Regridding utility (point-to-point, cell-to-point, ESMF conservative) |
| **Timeline** | Event scheduler that coordinates time-stepping across coupled models |
| **PortPrinter** | Output writer that captures variables to NetCDF at scheduled intervals |

### 1.3 Architecture

```
User Python Script
       │
       ▼
pymt.models.ModelName()          ← ModelCollection loads via entry points
       │
       ▼
BmiCap (bmi_bridge.py)           ← wraps BMI with setup, grids, mappers, units
       │
       ├─ SetupMixIn              ← model.setup() generates config files
       ├─ GridMapperMixIn         ← spatial regridding between grids
       ├─ BmiTimeInterpolator     ← temporal interpolation
       └─ bmi_ugrid               ← UGRID/NetCDF output
       │
       ▼
Underlying BMI Model (C/Fortran/Python compiled library)
```

---

## 2. Installation

### 2.1 Recommended (Conda)

```bash
mamba install pymt -c conda-forge
```

This installs PyMT and its core dependencies. Individual model plugins must be
installed separately:

```bash
mamba install pymt_cem pymt_hydrotrend pymt_waves -c conda-forge
```

### 2.2 From Source

```bash
git clone https://github.com/csdms/pymt.git
cd pymt
python -m venv venv
source venv/bin/activate
pip install -e ".[testing]"
```

### 2.3 Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| click | any | CLI framework |
| deprecated | any | Deprecation warnings |
| gimli.units | >=0.3.2 | Unit conversion (UDUNITS-based) |
| jinja2 | any | Config file template rendering |
| landlab | >=2 | Spatial grid data structures |
| matplotlib | any | Visualization |
| model_metadata | >=0.7, <0.8 | Model metadata discovery |
| netcdf4 | any | NetCDF I/O |
| numpy | <2 | Array operations |
| pyyaml | any | YAML parsing |
| scipy | any | Scientific computing |
| shapely | any | Geometric operations |
| xarray | any | Labeled array data |

### 2.4 Test Installation

```bash
python -c "import pymt; print(pymt.__version__)"
python -c "from pymt import MODELS; print(list(MODELS))"
```

---

## 3. Pipeline Overview

The PyMT workflow has 7 stages for using a single model or coupling models:

```
s1_discover  →  s2_configure  →  s3_initialize  →  s4_run  →  s5_output  →  s6_couple  →  s7_analyze
     │               │                │               │            │              │             │
  Find model    Setup params     Load model      Time-step    Write NetCDF   Link models   Post-process
```

### Stage Descriptions

| Stage | Name | Description | Key Methods/Tools |
|-------|------|-------------|-------------------|
| s1 | Discover | Find available BMI models via plugin system | `pymt.MODELS`, `model_collection.py` |
| s2 | Configure | Set parameters, generate config files | `model.setup()`, `model.parameters` |
| s3 | Initialize | Load model, allocate memory, read config | `model.initialize(cfg_file, dir=cfg_dir)` |
| s4 | Run | Time-step the model forward | `model.update()`, `model.run(stop)`, `model.go()` |
| s5 | Output | Write variables to files | `NcPortPrinter`, `model.get_value()` |
| s6 | Couple | Exchange data between models | `set_value()`, `get_value()`, mappers |
| s7 | Analyze | Post-process and visualize results | matplotlib, xarray, custom scripts |

---

## 4. Tools Reference

| Tool | Lines | Stage | Purpose |
|------|-------|-------|---------|
| `discover_models.py` | ~120 | s1 | Enumerate installed BMI model plugins |
| `configure_model.py` | ~180 | s2 | Generate config files with parameter overrides |
| `run_model.py` | ~200 | s4 | Execute a model through its full lifecycle |
| `parse_output.py` | ~170 | s5/s7 | Extract model output variables to CSV |
| `couple_models.py` | ~220 | s6 | Connect two BMI models and run coupled simulation |

---

## 5. Critical Domain Knowledge

### ALERT 1: Unit system is UDUNITS-based, not ad-hoc
PyMT uses `gimli.units` (wrapping UDUNITS) for all unit conversions. When calling
`model.get_value(var_name, units="...")`, the units string MUST be UDUNITS-compatible.
Common gotcha: `"celsius"` not `"C"` or `"deg_C"` (depends on gimli version).

**Detection:** `gimli.units.UnitError` or silently wrong values
**Fix:** Check `model.var_units(var_name)` and use compatible target units.

### ALERT 2: Variables are flat NumPy arrays, not shaped grids
`get_value()` always returns a **flattened** 1D array regardless of grid shape.
You must reshape manually using `model.grid_shape(grid_id)`.

**Detection:** Shape mismatch errors when plotting or coupling
**Fix:** `values.reshape(model.grid_shape(grid_id))`

### ALERT 3: Standard Names must match EXACTLY
Variable exchange between coupled models uses CSDMS Standard Names. A typo or
non-standard name silently fails — no data is exchanged, values stay at defaults.

**Detection:** Coupled model produces unchanged output
**Fix:** Check `model.input_var_names` and `model.output_var_names` for exact strings.

### ALERT 4: Azimuth vs. math angle convention
PyMT has explicit conversion functions (`transform_math_to_azimuth`,
`transform_azimuth_to_math`) in `pymt/units.py`. Coastal/wave models often use
azimuth (clockwise from north) while internal math uses counter-clockwise from east.

**Detection:** Wave direction or flow direction off by 90 degrees
**Fix:** Use `get_value(var_name, angle="azimuth")` or `angle="math"`.

### ALERT 5: numpy < 2 requirement
PyMT requires `numpy < 2` (pinned in requirements.txt, issue #173). Installing
numpy 2.x causes silent array dtype issues and potential segfaults in compiled
BMI libraries.

**Detection:** Segfaults, dtype errors, import failures
**Fix:** `pip install "numpy<2"` or use conda environment.

### ALERT 6: Model plugins are separate packages
`from pymt.models import Cem` will raise `ImportError` unless `pymt_cem` is
installed. The error message is not always clear about which package to install.

**Detection:** `ImportError` or empty `MODELS` list
**Fix:** `mamba install pymt_<modelname> -c conda-forge`

### ALERT 7: Config file paths are relative to run directory
When calling `model.initialize(cfg_file, dir=cfg_dir)`, the `cfg_file` path is
relative to `cfg_dir`. Using absolute paths for `cfg_file` will fail silently
or read wrong config.

**Detection:** Model runs with default parameters despite custom config
**Fix:** Always use the tuple returned by `model.setup()`: `model.initialize(*model.setup())`

### ALERT 8: Time units vary across models
Different BMI models use different time units (seconds, hours, days, years).
When coupling, you must check `model.time_units` and convert appropriately.
PyMT does NOT auto-convert time units between coupled models.

**Detection:** Coupled model runs too fast or too slow
**Fix:** Check `model.time_units` for both models, synchronize in coupling loop.

### ALERT 9: Grid types determine valid mappers
Not all mapper types work with all grid types. Using `PointToPoint` mapper with
an unstructured grid may silently produce wrong interpolation. ESMF mappers
require `esmpy` (optional dependency).

**Detection:** Interpolated values are NaN or wildly wrong
**Fix:** Match mapper type to grid types. Use `model.grid_type(grid_id)` to check.

---

## 6. Unit Trap Table

| Variable Category | Common Source Unit | PyMT Expected | Trap | Triplet |
|-------------------|--------------------|---------------|------|---------|
| Wave height | cm | m | ×0.01 | dt_001 |
| Wave angle | degrees (azimuth) | radians (math) | azimuth→math transform | dt_002 |
| Temperature | Celsius | varies by model | Check model units | dt_003 |
| Precipitation | mm/day | may need m/s | ÷86400÷1000 | dt_004 |
| Discharge | ft³/s | m³/s | ×0.0283168 | dt_005 |
| Time step | hours | model-specific | Check time_units | dt_006 |
| Grid coordinates | geographic (lon/lat) | may need projected (m) | Coordinate transform | dt_007 |
| Elevation | feet | meters | ×0.3048 | dt_008 |
| Wind speed | knots | m/s | ×0.514444 | dt_009 |
| Relative humidity | fraction (0-1) | may need % (0-100) | ×100 | dt_010 |

---

## 7. Data Flow: Single Model

```python
from pymt.models import ModelName

# 1. Instantiate
model = ModelName()

# 2. Configure — returns (config_file, config_dir)
args = model.setup(path="/runs/test1", param1=value1)

# 3. Initialize — load config, allocate grids
model.initialize(*args)

# 4. Query metadata
print(model.input_var_names)   # tuple of CSDMS Standard Names
print(model.output_var_names)
print(model.time_step)         # float
print(model.time_units)        # string, e.g., "d"

# 5. Run
for _ in range(100):
    model.update()                           # advance one time step
    vals = model.get_value("var_name")       # flat numpy array
    # optionally set forcing
    model.set_value("forcing_var", new_data)

# 6. Finalize — deallocate
model.finalize()
```

---

## 8. Data Flow: Coupled Models

```python
from pymt.models import Waves, Cem

waves = Waves()
cem = Cem()

# Setup both
w_args = waves.setup()
c_args = cem.setup()

# Initialize both
waves.initialize(*w_args)
cem.initialize(*c_args)

# Coupling loop
for t in range(1000):
    # 1. Update source model
    waves.update()

    # 2. Get output from source
    angle = waves.get_value("sea_surface_water_wave__azimuth_angle_of_opposite_of_phase_velocity")

    # 3. Set input on target (names must match!)
    cem.set_value("sea_surface_water_wave__azimuth_angle_of_opposite_of_phase_velocity", angle)

    # 4. Update target model
    cem.update()

# Finalize
waves.finalize()
cem.finalize()
```

---

## 9. Output Formats

### 9.1 Direct Array Access
```python
values = model.get_value("var_name")              # numpy array (flat)
values = model.get_value("var_name", units="m")    # with unit conversion
```

### 9.2 NetCDF Output (via PortPrinter)
```python
from pymt.portprinter.port_printer import NcPortPrinter

printer = NcPortPrinter(model, "var_name")
printer.open()
for t in range(100):
    model.update()
    printer.write()
printer.close()
```

### 9.3 UGRID/xarray Dataset
```python
from pymt.framework.bmi_ugrid import dataset_from_bmi_grid
ds = dataset_from_bmi_grid(model.bmi, grid_id)  # returns xarray.Dataset
```

---

## 10. Grid System

PyMT supports 4 grid types:

| Type | Class | Description |
|------|-------|-------------|
| `uniform_rectilinear` | `UniformRectilinear` | Regular spacing, origin + delta |
| `rectilinear` | `Rectilinear` | Variable spacing, 1D coordinate arrays |
| `structured` | `Structured` | Curvilinear, 2D coordinate arrays |
| `unstructured` | `Unstructured` | Arbitrary connectivity, UGRID format |

### Grid Query Methods
```python
grid_id = model.var_grid("var_name")
grid_type = model.grid_type(grid_id)
shape = model.grid_shape(grid_id)
x = model.grid_x(grid_id)
y = model.grid_y(grid_id)
```

---

## 11. Mapper System

Mappers transfer data between models on different grids:

| Mapper | Source Grid | Target Grid | Method |
|--------|-------------|-------------|--------|
| `PointToPoint` | any | any | Nearest-neighbor |
| `CellToPoint` | cells | points | Area-weighted average |
| `PointToCell` | points | cells | Area-weighted distribution |
| `EsmpMapper` | any | any | ESMF conservative remapping |

**Critical:** ESMF mappers require the optional `esmpy` package.

---

## 12. Plugin System

Models are discovered via Python entry points:

```ini
# In pymt_cem/setup.cfg or pyproject.toml
[options.entry_points]
pymt.plugins =
    Cem = pymt_cem:Cem
```

At runtime, `ModelCollection` iterates over `pymt.plugins` entry points and
wraps each with `BmiCap` to create the full PyMT model class.

### Listing Available Models
```python
from pymt import MODELS
for name in MODELS:
    print(name)
```

---

## 13. CLI Tool: cmt_config

```bash
cmt_config --help
cmt_config Waves --vars     # list variables
cmt_config Waves Cem        # show config for multiple models
```

---

## 14. Calibration Strategy

Since PyMT wraps external models, calibration depends on the underlying model:

1. **Parameter sensitivity** — Use `model.parameters` to list tuneable parameters
2. **Objective function** — Compute against observations (NSE, KGE, RMSE)
3. **Sampling** — Latin Hypercube or GLUE
4. **Execution** — Use `model.setup(param=value)` to create runs with different params
5. **Parallelism** — Each `model.setup()` creates an independent run directory

---

## 15. Validation: Quick Start

```bash
# Install PyMT + a test model
mamba create -n pymt_test python=3.10
mamba activate pymt_test
mamba install pymt pymt_hydrotrend -c conda-forge

# Run test
python -c "
from pymt.models import Hydrotrend
m = Hydrotrend()
args = m.setup()
m.initialize(*args)
print('Inputs:', m.input_var_names)
print('Outputs:', m.output_var_names)
m.update()
print('Time:', m.time, m.time_units)
m.finalize()
print('SUCCESS')
"
```

---

## 16. Diagnostic Triplets Summary

See `diagnostics/triplets.yaml` for full details. Key triplets:

| ID | Stage | Symptom | Severity |
|----|-------|---------|----------|
| dt_001 | s2 | Values 100x too large after unit conversion | silent |
| dt_002 | s6 | Wave direction off by 90 degrees | silent |
| dt_003 | s6 | Temperature output in wrong scale | silent |
| dt_004 | s2 | Precipitation way too high/low | silent |
| dt_005 | s2 | Discharge in wrong units | silent |
| dt_006 | s4 | Coupled model time desynchronized | degraded |
| dt_007 | s6 | Spatial mismatch, NaN interpolations | fatal |
| dt_008 | s2 | Elevation inversion | silent |
| dt_009 | s3 | Model runs with defaults, ignores config | silent |
| dt_010 | s6 | No data exchanged between coupled models | silent |

---

## 17. File Structure

```
ki/
├── SKILL.md                          ← this file
├── tools/
│   ├── discover_models.py            ← enumerate installed BMI plugins
│   ├── configure_model.py            ← generate config with param overrides
│   ├── run_model.py                  ← execute model lifecycle
│   ├── parse_output.py               ← extract output vars to CSV
│   └── couple_models.py              ← run coupled simulation
├── docs/
│   ├── s1_discovery.md               ← plugin discovery skill
│   ├── s2_configuration.md           ← model setup and params skill
│   ├── s3_initialization.md          ← initialization and grid inspection
│   ├── s4_execution.md               ← time-stepping and forcing
│   ├── s5_output.md                  ← NetCDF output and data extraction
│   ├── s6_coupling.md                ← model coupling and mapping
│   └── s7_analysis.md               ← post-processing and visualization
└── diagnostics/
    └── triplets.yaml                 ← 15+ symptom→diagnosis→remedy entries
```

---

## 18. Cross-References

- PyMT source: https://github.com/csdms/pymt
- BMI specification: https://bmi.readthedocs.io
- CSDMS Standard Names: https://csdms.colorado.edu/wiki/CSDMS_Standard_Names
- Model plugins: https://pymt.readthedocs.io/en/latest/models.html
- gimli.units: https://gimli.readthedocs.io
- UGRID conventions: http://ugrid-conventions.github.io/ugrid-conventions/

---

*Generated for PyMT v1.3.3.dev0 — CSDMS Python Modeling Toolkit*
*KI Package v1.0.0*
