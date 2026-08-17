---
name: bmi
description: BMI. Use when the task involves running, configuring, calibrating or interpreting BMI.
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

# BMI v2.0 (Basic Model Interface) — Knowledge Infrastructure

**Package**: `hydrocraft-bmi-framework` v1.0.0
**Model**: BMI v2.0 — Basic Model Interface Specification
**Source**: https://github.com/csdms/bmi
**Created by**: CSDMS (Community Surface Dynamics Modeling System), University of Colorado Boulder
**Authors**: Eric W.H. Hutton, Mark D. Piper, Gregory E. Tucker
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 17 diagnostic triplets | ~1,200 lines of validated Python
**Validation status**: `specification_validated` (bmi-example-python heat model)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: Framework models use data from the coupled models.


## Overview

The Basic Model Interface (BMI) is a **standardized set of control and query functions** that, when added to a software element such as a numerical model or dataset, makes that software easier to couple with other BMI-enabled software. BMI is developed and maintained by CSDMS (Community Surface Dynamics Modeling System) under NSF funding.

**What BMI is**: A language-agnostic interface specification — NOT a model itself. BMI defines 31 functions organized into 7 categories that any geoscience model can implement to become interoperable.

**What BMI does**:
- Provides standardized model control: Initialize → Run → Finalize (IRF) pattern
- Enables variable exchange between coupled models via getters/setters
- Describes model grids (scalar, uniform rectilinear, rectilinear, structured quad, unstructured)
- Reports time stepping, variable units, data types, and grid topology
- Allows external frameworks (e.g., pymt) to drive any BMI-wrapped model

**Key difference from standalone models**: BMI is middleware. It wraps an existing model without modifying its internals. The BMI layer introduces no dependencies — the model still works standalone.

**Supported languages**: C, C++, Fortran, Java, Python, R, JavaScript, Julia

---

## Installation

### Python specification (bmi-python)

```bash
# Via pip
pip install bmipy

# Via conda
conda install -c conda-forge bmipy
```

### Python example (bmi-example-python — heat diffusion model)

```bash
pip install bmi-example-python
# or
conda install -c conda-forge bmi-example-python
```

### Other language specifications

| Language | Package          | Install method          |
|----------|------------------|-------------------------|
| C        | bmi-c            | conda / cmake           |
| C++      | bmi-cxx          | conda / cmake           |
| Fortran  | bmi-fortran      | conda / cmake           |
| Java     | bmi-java         | Maven                   |
| Python   | bmipy            | pip / conda             |

### Dependencies

```
Python: numpy (for array exchange)
Docs:   sphinx, myst-parser (for building documentation)
```

---

## BMI Function Categories (7 groups, 31 functions)

### 1. Metadata Functions
| Function            | Purpose                          |
|---------------------|----------------------------------|
| `get_bmi_version`   | Returns BMI version string (≥2.1)|

### 2. Control Functions (IRF Pattern)
| Function          | Purpose                                      |
|-------------------|----------------------------------------------|
| `initialize`      | Setup model from config file (YAML preferred) |
| `update`          | Advance model by one internal time step       |
| `update_until`    | Advance model to a specific time              |
| `finalize`        | Cleanup, deallocate, close files              |

### 3. Information Functions
| Function                 | Purpose                              |
|--------------------------|--------------------------------------|
| `get_component_name`     | Model name string                    |
| `get_input_item_count`   | Number of input exchange items       |
| `get_output_item_count`  | Number of output exchange items      |
| `get_input_var_names`    | List of input variable names         |
| `get_output_var_names`   | List of output variable names        |

### 4. Variable Information Functions
| Function             | Purpose                                |
|----------------------|----------------------------------------|
| `get_var_grid`       | Grid identifier for a variable         |
| `get_var_type`       | Data type (e.g., `float64`)            |
| `get_var_units`      | Units string (UDUNITS convention)      |
| `get_var_itemsize`   | Bytes per element                      |
| `get_var_nbytes`     | Total bytes for variable               |
| `get_var_location`   | Grid element: `node`, `edge`, or `face`|

### 5. Time Functions
| Function            | Purpose                                |
|---------------------|----------------------------------------|
| `get_current_time`  | Current model time (float)             |
| `get_start_time`    | Model start time (typically 0.0)       |
| `get_end_time`      | Model end time                         |
| `get_time_units`    | Time unit string (UDUNITS: s, min, h, d)|
| `get_time_step`     | Internal time step (float)             |

### 6. Getter/Setter Functions
| Function                  | Purpose                            |
|---------------------------|------------------------------------|
| `get_value`               | Copy variable values to array      |
| `get_value_ptr`           | Reference to variable (live link)  |
| `get_value_at_indices`    | Get values at specific indices     |
| `set_value`               | Overwrite variable values          |
| `set_value_at_indices`    | Set values at specific indices     |

### 7. Grid Functions
| Function                   | Purpose                              |
|----------------------------|--------------------------------------|
| `get_grid_rank`            | Number of dimensions                 |
| `get_grid_size`            | Total number of nodes                |
| `get_grid_type`            | Grid type string                     |
| `get_grid_shape`           | Dimensions array [ny, nx]            |
| `get_grid_spacing`         | Cell spacing [dy, dx]                |
| `get_grid_origin`          | Lower-left corner [y0, x0]          |
| `get_grid_x`               | Node x-coordinates                   |
| `get_grid_y`               | Node y-coordinates                   |
| `get_grid_z`               | Node z-coordinates                   |
| `get_grid_node_count`      | Number of nodes (unstructured)       |
| `get_grid_edge_count`      | Number of edges (unstructured)       |
| `get_grid_face_count`      | Number of faces (unstructured)       |
| `get_grid_edge_nodes`      | Edge-node connectivity               |
| `get_grid_face_edges`      | Face-edge connectivity               |
| `get_grid_face_nodes`      | Face-node connectivity               |
| `get_grid_nodes_per_face`  | Nodes per face array                 |

---

## Pipeline Stages

The BMI workflow for wrapping and running a model follows these stages:

| Stage | Name                    | Tool                        | Description                                  |
|-------|-------------------------|-----------------------------|----------------------------------------------|
| S1    | Configuration Setup     | `config_generator.py`       | Generate YAML config file for a BMI model    |
| S2    | Compliance Check        | `compliance_checker.py`     | Validate BMI implementation completeness     |
| S3    | Model Execution         | `bmi_runner.py`             | Run model via IRF pattern with data exchange |
| S4    | Output Extraction       | `output_extractor.py`       | Extract variables to CSV/NetCDF via getters  |

---

## Unit Trap Table

BMI itself does not prescribe units for model variables, but it **requires** that units be queryable via `get_var_units()` and follow UDUNITS conventions. Common traps arise when coupling two BMI models with mismatched units.

| Variable Type   | Expected Convention       | Common Trap                                | Detection                                      |
|-----------------|---------------------------|--------------------------------------------|-------------------------------------------------|
| Time            | UDUNITS: `s`, `h`, `d`    | Using `years` (ambiguous: 365.2422 days)   | Check `get_time_units()` returns UDUNITS string |
| Length           | `m` (meters)              | Mixing `km` and `m` between models         | Compare `get_var_units()` across coupled models |
| Temperature     | `K` (Kelvin)              | Mixing `K` and `degC` without offset       | Values < 200 likely Celsius, not Kelvin         |
| Flux            | `m s-1` or `kg m-2 s-1`  | Failing to convert `mm/day` to `m/s`       | Check magnitude: 1 mm/day ≈ 1.16e-8 m/s        |
| Pressure        | `Pa`                      | Mixing `hPa`, `kPa`, `Pa`                 | Surface pressure ~101325 Pa, ~1013 hPa          |
| Dimensionless   | `""` or `"1"`             | Using `"none"` for unitless variables      | `"none"` means no units concept, not dimensionless|
| Grid spacing    | Model-specific            | ij-order vs xy-order in shape/spacing      | BMI always uses ij-order: [ny, nx], [dy, dx]    |
| Array layout    | 1D flattened              | Passing 2D arrays to BMI functions         | BMI always uses flattened 1D arrays             |
| Grid origin     | ij-order [y0, x0]         | Passing origin as [x0, y0]                 | BMI origin is [y0, x0] in ij-indexing           |

---

## Grid Type Reference

| Grid Type                  | Rank | Required Functions                                    |
|----------------------------|------|-------------------------------------------------------|
| `scalar`                   | 0    | get_grid_rank, get_grid_size                          |
| `points`                   | 1    | get_grid_rank, get_grid_size, get_grid_x/y/z          |
| `vector`                   | 1    | get_grid_rank, get_grid_size, get_grid_x/y/z          |
| `uniform_rectilinear`      | 1-3  | rank, size, shape, spacing, origin                    |
| `rectilinear`              | 1-3  | rank, size, shape, x, y, z                            |
| `structured_quadrilateral` | 2-3  | rank, size, shape, x, y, z                            |
| `unstructured`             | any  | rank, x, y, z, node/edge/face counts, connectivity   |

---

## Tool Reference

### `config_generator.py`
Generates a YAML configuration file for a BMI-wrapped model from user-supplied parameters.
- **Input**: Model name, grid dimensions, time parameters, initial conditions
- **Output**: YAML config file ready for `initialize(config_file)`
- **Pattern**: validate → generate → validate

### `compliance_checker.py`
Validates that a Python BMI implementation correctly implements all 31 required functions.
- **Input**: Python module/class implementing BMI
- **Output**: Compliance report (pass/fail per function, warnings)
- **Pattern**: discover → test → report

### `bmi_runner.py`
Executes a BMI-wrapped model through the full IRF lifecycle with optional data injection/extraction.
- **Input**: BMI class, config file, time range, optional set_value schedule
- **Output**: Time series of selected output variables
- **Pattern**: initialize → loop(update + get_value) → finalize

### `output_extractor.py`
Extracts model state variables via BMI getters and writes to CSV or NetCDF.
- **Input**: Running BMI model instance, list of variable names, output format
- **Output**: CSV or NetCDF file with extracted data
- **Pattern**: query_vars → extract_loop → write_output

---

## Quick Start Example (Python Heat Model)

```python
from heat import BmiHeat
import numpy as np

# 1. Initialize
model = BmiHeat()
model.initialize("heat.yaml")

# 2. Query model info
print(model.get_component_name())         # "The 2D Heat Equation"
print(model.get_input_var_names())         # ("plate_surface__temperature",)
print(model.get_output_var_names())        # ("plate_surface__temperature",)
print(model.get_time_units())              # "s"
print(model.get_time_step())              # 0.25

# 3. Get grid info
grid_id = model.get_var_grid("plate_surface__temperature")
print(model.get_grid_type(grid_id))       # "uniform_rectilinear"
print(model.get_grid_shape(grid_id, np.empty(2, dtype=int)))  # [10, 20]

# 4. Run and extract
for _ in range(100):
    model.update()

temp = np.empty(200, dtype=float)
model.get_value("plate_surface__temperature", temp)
print(f"Max temp: {temp.max():.2f}")

# 5. Finalize
model.finalize()
```

---

## Best Practices Summary

1. **All 31 BMI functions must be implemented** — unused ones should raise `NotImplementedError` or return `BMI_FAILURE`
2. **Use YAML for configuration files** (preferred by CSDMS, though not required)
3. **Use CSDMS Standard Names** for exchange items to enable automatic coupling
4. **Arrays are always flattened 1D** — developer handles reshape internally
5. **Grid indexing is always ij-order** (row-major), not xy-order
6. **Avoid global variables** — enables multiple model instances
7. **Memory allocation is the model's responsibility**, not the BMI layer's
8. **Use UDUNITS for time** — avoid `years` (ambiguous definition)
9. **Refactor into IRF** if model has monolithic main loop
10. **Return status codes** (C/Fortran) or **raise exceptions** (Python/C++/Java) on failure

---

## References

- Hutton, E.W.H., Piper, M.D., Tucker, G.E. (2020). "The Basic Model Interface 2.0: A standard interface for coupling numerical models in the geosciences." JOSS, 5(51), 2317. DOI: 10.21105/joss.02317
- Peckham, S.D., Hutton, E.W.H., Norris, B. (2013). "A component-based approach to integrated modeling in the geosciences: The design of CSDMS." Computers & Geosciences, 53, 3-12.
- BMI Documentation: https://bmi.readthedocs.io
- CSDMS Standard Names: https://csdms.colorado.edu/wiki/CSDMS_Standard_Names
- UDUNITS: https://www.unidata.ucar.edu/software/udunits/
