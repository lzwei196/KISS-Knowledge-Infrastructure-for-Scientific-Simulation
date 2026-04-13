# S5: Model Assembly and Execution

## Purpose

Assemble the PorePy model from equation mixins, constitutive laws, and solver
parameters, then execute the simulation. This stage covers model composition,
solver selection, and the execution workflow.

## Inputs

| Input              | Type            | Description                             |
|--------------------|-----------------|-----------------------------------------|
| Model class        | Python class    | Composed from PorePy mixins             |
| model_params       | `dict`          | Domain, materials, units, meshing       |
| solver_params      | `dict`          | Newton iterations, tolerances           |

## Outputs

| Output               | Type                | Description                          |
|----------------------|---------------------|--------------------------------------|
| VTU files            | `.vtu` / `.pvd`     | Simulation results in ParaView format|
| solver_statistics    | `.json`             | Convergence and timing data          |
| Model object         | Python object       | Contains solution state              |

## Procedure

### Step 1: Compose model class

PorePy models are built via multiple inheritance of mixins:

```python
import porepy as pp

# Simple: Use a pre-built model
model = pp.SinglePhaseFlow(model_params)

# Advanced: Compose from mixins
class CustomPoromechanics(
    pp.FluidMassBalanceEquations,
    pp.MomentumBalanceEquations,
    pp.EquationsPoromechanics,
    pp.SolutionStrategy,
    pp.ModelGeometry,
):
    def set_domain(self):
        self._domain = pp.Domain(...)

    def set_fractures(self):
        self._fractures = [...]
```

### Step 2: Configure solver parameters

```python
solver_params = {
    # Newton solver
    "nl_max_iterations": 15,
    "nl_convergence_res_atol": 1e-8,
    "nl_convergence_inc_atol": 1e-8,

    # Progress bars (requires tqdm)
    "progressbars": True,
    "prepare_simulation": True,
}
```

### Step 3: Run stationary problem

```python
model = pp.SinglePhaseFlow(model_params)
pp.run_stationary_model(model, solver_params)
# Results in model_params["folder_name"]/*.vtu
```

### Step 4: Run time-dependent problem

```python
model_params["time_manager"] = pp.TimeManager(
    schedule=[0, 86400],    # 1 day in seconds
    dt_init=3600,           # 1 hour time step
    constant_dt=True,
)
model = pp.Poromechanics(model_params)
pp.run_time_dependent_model(model, solver_params)
```

### Step 5: Post-processing

```python
# Access solution after simulation
mdg = model.mdg
for sd in mdg.subdomains():
    pressure = model.pressure([sd]).value(model.equation_system)
    print(f"Pressure range: {pressure.min():.2e} to {pressure.max():.2e} Pa")
```

## Verification

- Check convergence: Newton iterations < `nl_max_iterations` for each step
- Check residual: final residual < `nl_convergence_res_atol`
- No NaN values in solution arrays
- Output VTU files exist in the specified folder
- Physical reasonableness: pressure within expected range

## Traps

| ID     | Trap                                         | Consequence                              |
|--------|----------------------------------------------|------------------------------------------|
| dt_013 | Newton divergence (NaN in increment)          | Simulation crash at first nonlinear step |
| dt_015 | Singular matrix (pure Neumann BCs)            | Linear solver failure                    |
| dt_017 | Dirichlet/Neumann BC types swapped            | Wrong flow direction or magnitude        |
| dt_007 | Time step too large for physics               | Newton non-convergence                   |
| dt_011 | pp.Units(s≠1)                                 | NotImplementedError at prepare_simulation|

## Example

```python
import numpy as np
import porepy as pp

class QuickFlow(pp.SinglePhaseFlow):
    def set_domain(self):
        self._domain = pp.Domain({"xmin": 0, "xmax": 1, "ymin": 0, "ymax": 1})

    def set_fractures(self):
        self._fractures = []

# Stationary flow
model = QuickFlow({
    "grid_type": "cartesian",
    "meshing_arguments": {"cell_size": 0.1},
    "folder_name": "quick_test",
})
pp.run_stationary_model(model, {"nl_max_iterations": 10})

# Check output
import os
vtu_files = [f for f in os.listdir("quick_test") if f.endswith(".vtu")]
print(f"Generated {len(vtu_files)} VTU files")
```

### Execution Wrapper

For automated pipeline execution:

```bash
python ki/tools/run_porepy.py --model single_phase_flow --config config.json
python ki/tools/run_porepy.py --example mandel_biot
```
