# S3: Model Execution

## Purpose

Run any BMI-wrapped model through the complete Initialize → Run → Finalize (IRF) lifecycle. This stage handles the core BMI execution loop: initialize with a config, advance through time steps while extracting data, and clean up.

## Inputs

| Input              | Type     | Description                                       |
|--------------------|----------|---------------------------------------------------|
| BMI instance       | object   | Uninitialized BMI model object                    |
| Config file        | string   | Path to YAML config (from S1)                     |
| Output variables   | [string] | Variable names to track (default: all output vars)|
| End time override  | float    | Optional override of model end time               |
| Inject schedule    | dict     | Optional: {time: {var_name: values}} injections   |

## Outputs

| Output        | Format | Description                                     |
|---------------|--------|-------------------------------------------------|
| Time series   | dict   | {var_name: [values_at_each_timestep]}           |
| Output CSV    | file   | Time series written to CSV                      |
| Run metadata  | dict   | Model name, dt, n_steps, wall time             |

## Procedure

1. **Initialize**: Call `bmi.initialize(config_file)`
2. **Query metadata**: Get component name, time info, variable names/units
3. **Enter time loop**:
   - Check inject schedule; call `set_value()` if data injection needed
   - Call `bmi.update()` to advance one time step
   - Call `bmi.get_current_time()` to track progress
   - For each output variable: call `bmi.get_value(name, dest)` to extract
   - Store scalar values or summary stats (mean/min/max/std) for grid vars
4. **Finalize**: Call `bmi.finalize()` to clean up
5. **Write results**: Output CSV with time series

```bash
# Example: run heat model for 50 seconds
python bmi_runner.py heat BmiHeat heat_config.yaml --end-time 50 -o heat_results.csv
```

## Verification

- [ ] `initialize()` completes without error
- [ ] `get_current_time()` advances monotonically
- [ ] `get_value()` returns arrays of expected size (= grid_size)
- [ ] All output variables have non-null values
- [ ] `finalize()` completes without error
- [ ] Output CSV contains time column + variable columns

## The IRF Pattern

```
┌─────────────────────────────────────────────────────┐
│ INITIALIZE                                          │
│   bmi.initialize(config_file)                       │
│   → reads parameters, allocates arrays, sets IC     │
├─────────────────────────────────────────────────────┤
│ RUN (time loop)                                     │
│   while current_time < end_time:                    │
│     [optional] bmi.set_value(name, new_data)        │
│     bmi.update()                                    │
│     values = bmi.get_value(name, dest)              │
├─────────────────────────────────────────────────────┤
│ FINALIZE                                            │
│   bmi.finalize()                                    │
│   → deallocates memory, closes files, prints report │
└─────────────────────────────────────────────────────┘
```

## Traps

| Trap | Description | Detection | Fix |
|------|-------------|-----------|-----|
| **Uninitialized access** | Calling `get_value` before `initialize` | AttributeError or garbage values | Always call `initialize` first |
| **Post-finalize access** | Calling `get_value` after `finalize` | Segfault (C/Fortran) or exception | Extract all data before finalize |
| **Time unit mismatch** | end_time in hours but model uses seconds | Model runs 3600x too long or too short | Check `get_time_units()` first |
| **Array size mismatch** | dest array wrong size for `get_value` | Buffer overrun or exception | Use `get_var_nbytes / get_var_itemsize` for size |
| **2D array passed** | Passing 2D numpy array to `get_value` | Possible silent corruption | BMI always uses flattened 1D arrays |
| **update_until precision** | Floating-point rounding in time comparison | Model runs one step too many/few | Use `abs(current - target) < dt/2` |

## Example

```python
from heat import BmiHeat
import numpy as np

model = BmiHeat()
model.initialize("heat.yaml")

print(f"Model: {model.get_component_name()}")
print(f"Time step: {model.get_time_step()} {model.get_time_units()}")

# Get grid info
grid_id = model.get_var_grid("plate_surface__temperature")
grid_size = model.get_grid_size(grid_id)

# Run for 100 steps
for step in range(100):
    model.update()
    temp = np.empty(grid_size, dtype=float)
    model.get_value("plate_surface__temperature", temp)
    if step % 25 == 0:
        print(f"  Step {step}: max_temp={temp.max():.4f}")

model.finalize()
```
