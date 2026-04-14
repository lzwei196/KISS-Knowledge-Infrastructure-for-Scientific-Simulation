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

# PorePy Knowledge Infrastructure

| Field            | Value                                                        |
|------------------|--------------------------------------------------------------|
| **Model**        | PorePy v1.12.0                                               |
| **Domain**       | Fractured porous media simulation (subsurface flow, poromechanics) |
| **Language**     | Python 3.10+                                                 |
| **Build**        | pip install (setuptools)                                     |
| **Tools**        | 4 tools                                                      |
| **Triplets**     | 18 diagnostic entries                                        |
| **Developers**   | Porous Media Group, University of Bergen, Norway             |
| **License**      | GPL v3                                                       |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for recharge forcing documentation.
See `data_ki/GLHYMPS/SKILL.md` for hydrogeology data.
See `data_ki/FanWTD/SKILL.md` for water table depth.
See `data_ki/GRACE/SKILL.md` for GRACE TWS validation data.


## 1  Overview

PorePy is a simulation tool for multiphysics processes in fractured and deformable
porous media. It provides:

- **Automatic mesh generation** for complex 2D/3D fracture networks via Gmsh
- **Mixed-dimensional grids (MDG)** coupling matrix, fractures, intersections, and wells
- **Discretization methods**: MPFA, MPSA, TPFA, VEM, RT0 finite elements
- **Automatic differentiation (AD)** for Jacobian assembly
- **Ready-made models**: single-phase flow, poromechanics, thermoporomechanics,
  multiphase compositional flow, contact mechanics, fracture propagation

PorePy is a **Python API-driven** framework — there are no external config files or CLI
commands. Simulations are defined by subclassing model mixins and calling
`pp.run_stationary_model()` or `pp.run_time_dependent_model()`.

---

## 2  Installation

```bash
# Create virtual environment
python3 -m venv venv && source venv/bin/activate

# Install from source
cd source/repo
pip install -e ".[development,testing]"

# Verify installation
python -c "import porepy as pp; print(pp.__version__)"
```

### Dependencies

| Package    | Purpose                        | Required |
|------------|--------------------------------|----------|
| numpy      | Numerical arrays               | Yes      |
| scipy      | Sparse linear algebra          | Yes      |
| gmsh       | Mesh generation                | Yes      |
| meshio     | Mesh I/O                       | Yes      |
| numba      | JIT compilation                | Yes      |
| networkx   | Graph algorithms               | Yes      |
| shapely    | Computational geometry         | Yes      |
| matplotlib | Visualization                  | Yes      |
| sympy      | Symbolic math                  | Yes      |
| pypardiso  | Fast sparse solver             | Optional |
| tqdm       | Progress bars                  | Optional |

---

## 3  Pipeline Stages

| Stage | Name                    | Tool                         | Description                                          |
|-------|-------------------------|------------------------------|------------------------------------------------------|
| s1    | Domain Definition       | —                            | Define geometry, fractures, wells                    |
| s2    | Forcing / Parameters    | `convert_forcing_data.py`    | Convert physical parameters to PorePy format         |
| s3    | Material Properties     | `convert_material_params.py` | Map rock/fluid properties to SolidConstants/FluidComponent |
| s4    | Mesh Generation         | —                            | Create MDG via `pp.create_mdg()`                     |
| s5    | Model Assembly          | —                            | Compose model class from mixins, set BCs/ICs         |
| s6    | Execution               | `run_porepy.py`              | Run stationary or time-dependent simulation          |
| s7    | Output Parsing          | `parse_porepy_output.py`     | Extract VTU results to CSV for analysis              |
| s8    | Validation              | —                            | Compare outputs against analytical/benchmark solutions |

---

## 4  Unit System — CRITICAL

PorePy uses an **internal unit scaling system** via `pp.Units`. All material properties
are stored in **SI units** internally. The `Units` class converts between user-specified
scales and SI.

### Base Units

| Symbol | Quantity    | SI Default | Example Custom          |
|--------|-------------|------------|-------------------------|
| `m`    | Length      | 1 m        | `1e-3` → millimeters    |
| `s`    | Time        | 1 s        | **Must be 1** (not implemented otherwise) |
| `kg`   | Mass        | 1 kg       | `1e3` → metric tons     |
| `K`    | Temperature | 1 K        | 1 K (rarely changed)    |
| `mol`  | Amount      | 1 mol      | `1e-3` → millimoles     |
| `rad`  | Angle       | 1 rad      | 1 rad                   |

### Derived Units

| Unit | Formula              | Example                        |
|------|----------------------|--------------------------------|
| Pa   | kg / (m · s²)        | Pressure, stress               |
| J    | kg · m² / s²         | Energy                         |
| N    | kg · m / s²          | Force                          |
| W    | kg · m² / s³         | Power                          |

### Unit Conversion API

```python
units = pp.Units(m=1e-3)  # Working in mm
# Convert 500 Pa from SI → user units
val = units.convert_units(500, "Pa")            # → 500 / (1e-3)^-1 ...
# Convert back to SI
val_si = units.convert_units(val, "Pa", to_si=True)
```

### Unit Trap Table — CRITICAL FAILURE MODES

| Trap ID | Variable       | Expected Unit   | Common Mistake           | Consequence                         |
|---------|----------------|-----------------|--------------------------|-------------------------------------|
| dt_001  | Permeability   | m²              | cm² or Darcy (9.87e-13)  | Flow rates off by orders of magnitude |
| dt_002  | Pressure       | Pa              | MPa or bar               | Stress/displacement 1e6× wrong     |
| dt_003  | Viscosity      | Pa·s            | cP (1e-3 factor)         | Darcy velocity wrong by 1000×      |
| dt_004  | Density        | kg/m³           | g/cm³ (1000× factor)     | Gravity term wrong                  |
| dt_005  | Young's modulus | Pa              | GPa (1e9 factor)         | Displacement 1e9× too large        |
| dt_006  | Porosity       | dimensionless   | Percentage (0–100)       | Mass balance wrong by 100×         |
| dt_007  | Time step      | seconds         | hours or days            | Transient results on wrong timescale |
| dt_008  | Cell size      | meters          | mm or km                 | Mesh too fine/coarse for domain     |
| dt_009  | Biot coeff.    | dimensionless   | Must be 0 < α ≤ 1       | Negative effective stress           |
| dt_010  | Thermal cond.  | W/(m·K)         | cal/(cm·s·°C)            | Heat transfer rate wrong            |
| dt_011  | Time scaling   | must be 1 s     | Any other value          | `NotImplementedError` raised        |
| dt_012  | Frac. aperture | meters          | mm (1e-3 factor)         | Fracture transmissivity 1e9× wrong |

---

## 5  Input Format

PorePy is configured entirely through Python dictionaries and class definitions.

### Model Parameters Dictionary

```python
model_params = {
    "linear_solver": "pypardiso",       # or "scipy_sparse"
    "units": pp.Units(),                 # Unit scaling
    "time_manager": pp.TimeManager(      # Time stepping
        schedule=[0, 3.15e7],            # Start/end in seconds
        dt_init=86400,                   # Initial dt (1 day)
        constant_dt=True,
    ),
    "material_constants": {
        "solid": pp.SolidConstants(**granite),
        "fluid": pp.FluidComponent(**water),
    },
    "grid_type": "cartesian",            # or "simplex"
    "meshing_arguments": {
        "cell_size": 0.5,                # meters
    },
    "folder_name": "output",
    "file_name": "results",
}
```

### Material Values (SI Units)

**Granite (default solid)**:
| Property               | Value        | Unit      |
|------------------------|--------------|-----------|
| density                | 2683.0       | kg/m³     |
| porosity               | 0.013        | —         |
| permeability           | 5.0e-18      | m²        |
| biot_coefficient       | 0.47         | —         |
| shear_modulus          | 1.485e10     | Pa        |
| lame_lambda            | 7.021e9      | Pa        |
| specific_heat_capacity | 790.0        | J/(kg·K)  |
| thermal_conductivity   | 2.5          | W/(m·K)   |
| friction_coefficient   | 0.6          | —         |

**Water (default fluid)**:
| Property               | Value        | Unit      |
|------------------------|--------------|-----------|
| density                | 998.2        | kg/m³     |
| viscosity              | 1.002e-3     | Pa·s      |
| compressibility        | 4.559e-10    | 1/Pa      |
| specific_heat_capacity | 4182.0       | J/(kg·K)  |
| thermal_conductivity   | 0.5975       | W/(m·K)   |
| thermal_expansion      | 2.068e-4     | 1/K       |

### Fracture Definition

```python
# 2D fracture in a 2D domain
frac = pp.LineFracture(np.array([[0.25, 0.75], [0.5, 0.5]]))

# 3D planar fracture
frac_3d = pp.PlaneFracture(np.array([
    [0, 1, 1, 0],  # x-coords
    [0, 0, 1, 1],  # y-coords
    [0.5, 0.5, 0.5, 0.5],  # z-coords (planar)
]))

# Create network and MDG
network = pp.create_fracture_network(fracs=[frac], domain=domain)
mdg = pp.create_mdg(grid_type="simplex", meshing_args={"cell_size": 0.1},
                     fracture_network=network)
```

---

## 6  Output Format

### Primary: VTU/VTK Files

PorePy exports results via `pp.Exporter` to VTU format for ParaView:

- `<file_name>_<subdomain>.vtu` — cell data (pressure, displacement, temperature)
- `<file_name>_<interface>.vtu` — interface/mortar data (fluxes)
- `<file_name>.pvd` — time series collection file

### Key Output Variables

| Variable          | Symbol | Unit  | Location    |
|-------------------|--------|-------|-------------|
| Pressure          | p      | Pa    | Cell centers|
| Displacement      | u      | m     | Cell centers|
| Temperature       | T      | K     | Cell centers|
| Darcy flux        | q      | m³/s  | Faces       |
| Stress            | σ      | Pa    | Cell centers|
| Fracture aperture | a      | m     | Fracture cells |
| Contact traction  | t      | Pa    | Interface   |

### Solver Statistics

Written to `solver_statistics.json`:
- Newton iterations per time step
- Linear solver time
- Convergence history
- Time step adaptations

---

## 7  Model Types Reference

| Model Class              | Physics                            | Variables    |
|--------------------------|------------------------------------|--------------|
| `SinglePhaseFlow`        | Darcy flow in porous media         | p            |
| `MomentumBalance`        | Linear elasticity                  | u            |
| `Poromechanics`          | Coupled flow + mechanics (Biot)    | p, u         |
| `ContactMechanics`       | Fracture contact + elasticity      | u, contact   |
| `Thermoporomechanics`    | THM coupling                       | p, u, T      |
| `CompositionalFlow`      | Multiphase multicomponent          | p, fractions |

---

## 8  Solver Configuration

### Newton Solver Parameters

| Parameter                    | Default | Description                      |
|------------------------------|---------|----------------------------------|
| `nl_max_iterations`          | 10      | Maximum Newton iterations        |
| `nl_convergence_inc_atol`    | 1e-6    | Absolute increment tolerance     |
| `nl_convergence_res_atol`    | 1e-6    | Absolute residual tolerance      |
| `nl_convergence_inc_rtol`    | 1e-4    | Relative increment tolerance     |
| `nl_convergence_res_rtol`    | 1e-4    | Relative residual tolerance      |

### Convergence Criteria

- `IncrementBasedAbsoluteCriterion` — ||Δx|| < tol
- `ResidualBasedAbsoluteCriterion` — ||r|| < tol
- `MaxIterationsCriterion` — stops if max iterations exceeded
- `IncrementBasedNanCriterion` — stops if NaN in increment

---

## 9  Calibration Parameters

For subsurface flow problems, parameters in priority order:

| Priority | Parameter          | Typical Range       | Sensitivity |
|----------|--------------------|---------------------|-------------|
| 1        | Permeability       | 1e-20 – 1e-12 m²   | Very high   |
| 2        | Porosity           | 0.001 – 0.40        | High        |
| 3        | Fracture aperture  | 1e-5 – 1e-2 m       | Very high   |
| 4        | Biot coefficient   | 0.1 – 1.0           | Medium      |
| 5        | Fluid viscosity    | 1e-4 – 1e-2 Pa·s    | High        |
| 6        | Young's modulus    | 1e8 – 1e11 Pa       | Medium      |
| 7        | Friction coeff.    | 0.1 – 0.9           | Low–Medium  |

---

## 10  Quick Start Example

```bash
# 1. Install
python3 -m venv venv && source venv/bin/activate
cd source/repo && pip install -e .

# 2. Run a simple flow example
python -c "
import numpy as np
import porepy as pp

class SimpleFlow(pp.SinglePhaseFlow):
    def set_domain(self):
        self._domain = pp.Domain({'xmin': 0, 'xmax': 1, 'ymin': 0, 'ymax': 1})
    def set_fractures(self):
        self._fractures = []

params = {
    'grid_type': 'cartesian',
    'meshing_arguments': {'cell_size': 0.1},
    'folder_name': 'test_output',
}
model = SimpleFlow(params)
pp.run_stationary_model(model, {})
print('Simulation complete. Check test_output/ for VTU files.')
"
```

---

## 11  File Structure

```
ki/
├── SKILL.md                          # This file — master reference
├── tools/
│   ├── convert_forcing_data.py       # Convert forcing/boundary data
│   ├── convert_material_params.py    # Convert material properties
│   ├── run_porepy.py                 # Execution wrapper
│   └── parse_porepy_output.py        # Output parser (VTU → CSV)
├── docs/
│   ├── s1_domain_definition.md       # Domain and fracture setup
│   ├── s2_forcing_parameters.md      # Boundary conditions and forcing
│   ├── s3_material_properties.md     # Rock and fluid materials
│   ├── s4_mesh_generation.md         # MDG creation and meshing
│   ├── s5_model_execution.md         # Running simulations
│   └── s6_output_analysis.md         # Parsing and visualizing results
└── diagnostics/
    └── triplets.yaml                 # Symptom → Diagnosis → Remedy
```

---

## 12  Diagnostic Triplets Summary

| ID     | Stage | Severity | Description                                    |
|--------|-------|----------|------------------------------------------------|
| dt_001 | s2    | silent   | Permeability in wrong units (Darcy vs m²)      |
| dt_002 | s2    | silent   | Pressure in MPa instead of Pa                  |
| dt_003 | s2    | silent   | Viscosity in cP instead of Pa·s                |
| dt_004 | s2    | silent   | Density in g/cm³ instead of kg/m³              |
| dt_005 | s3    | silent   | Young's modulus in GPa instead of Pa           |
| dt_006 | s3    | silent   | Porosity as percentage instead of fraction     |
| dt_007 | s6    | silent   | Time step in hours/days instead of seconds     |
| dt_008 | s4    | degraded | Cell size mismatch with domain scale           |
| dt_009 | s3    | fatal    | Biot coefficient > 1 or < 0                    |
| dt_010 | s3    | silent   | Thermal conductivity in wrong unit system       |
| dt_011 | s2    | fatal    | Time unit scaling ≠ 1 s                        |
| dt_012 | s3    | silent   | Fracture aperture in mm instead of m           |
| dt_013 | s6    | fatal    | Newton solver diverges (NaN in increment)      |
| dt_014 | s4    | fatal    | Gmsh fails on degenerate fracture geometry     |
| dt_015 | s6    | degraded | Linear solver fails (singular matrix)          |
| dt_016 | s7    | degraded | VTU file missing expected variables            |
| dt_017 | s6    | silent   | Wrong BC type (Dirichlet vs Neumann swap)      |
| dt_018 | s4    | fatal    | Fracture extends outside domain                |

---

## 13  Coupling Points

PorePy can be coupled with external models:

- **Watershed models** (SWAT+, VIC): Provide recharge boundary conditions
- **Reservoir models** (MODFLOW): Compare pressure/head fields
- **Geomechanics** (FLAC, ABAQUS): Import stress fields
- **Climate data** (CMIP6, ERA5): Provide transient boundary conditions

Data exchange is typically through CSV/VTU files or direct Python array passing.
