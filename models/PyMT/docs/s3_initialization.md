# Stage 3: Model Initialization

## Purpose

Load a configured model into memory: read configuration, allocate grids,
set initial conditions, and prepare for time-stepping. After this stage,
the model is ready for `update()` calls.

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| config_file | str | Yes | Config filename (from setup()) |
| config_dir | str | Yes | Run directory path (from setup()) |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| Initialized model | object | Model ready for update() calls |
| Grid metadata | various | Shape, type, coordinates of computational grid |
| Time metadata | floats | start_time, end_time, time_step, time_units |
| Variable metadata | tuples | input_var_names, output_var_names |

## Procedure

### Step 1: Initialize from setup() Output
```python
# Best practice: unpack setup() directly
model.initialize(*model.setup())

# Or with stored values
cfg_file, cfg_dir = model.setup(path="/runs/test")
model.initialize(cfg_file, dir=cfg_dir)
```

### Step 2: Inspect Time Properties
```python
print(f"Start time:  {model.start_time} {model.time_units}")
print(f"End time:    {model.end_time} {model.time_units}")
print(f"Time step:   {model.time_step} {model.time_units}")
print(f"Current:     {model.time} {model.time_units}")
```

### Step 3: Inspect Variables
```python
print("Input variables:")
for name in model.input_var_names:
    grid_id = model.var_grid(name)
    print(f"  {name}")
    print(f"    units: {model.var_units(name)}")
    print(f"    type:  {model.var_type(name)}")
    print(f"    grid:  {grid_id} ({model.grid_type(grid_id)})")

print("\nOutput variables:")
for name in model.output_var_names:
    print(f"  {name} [{model.var_units(name)}]")
```

### Step 4: Inspect Grids
```python
for name in model.output_var_names:
    grid_id = model.var_grid(name)
    if grid_id is not None:
        print(f"Grid {grid_id}:")
        print(f"  type: {model.grid_type(grid_id)}")
        try:
            print(f"  shape: {model.grid_shape(grid_id)}")
        except Exception:
            print(f"  node count: {model.grid_node_count(grid_id)}")
```

### Step 5: Get Initial Values
```python
for name in model.output_var_names:
    val = model.get_value(name)
    print(f"{name}: shape={val.shape}, mean={val.mean():.4f}")
```

## Verification

```python
# Model is initialized if current_time == start_time
assert model.time == model.start_time, "Model not at start time"
# Input/output var names should be non-empty
assert len(model.output_var_names) > 0, "No output variables"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| **Absolute path for cfg_file** | Model reads wrong/no config | Use relative path from setup() |
| **Double initialization** | ValueError or memory corruption | Create new model instance instead |
| Wrong working directory | Config file not found | Use `dir=` kwarg in initialize() |
| Missing shared libraries | ImportError or OSError | Install model's compiled dependencies |
| Grid type mismatch | Unexpected grid topology | Check grid_type() before using mappers |

## Example

```python
from pymt.models import Waves

model = Waves()
args = model.setup()
model.initialize(*args)

# Full inspection
print(f"Time: {model.start_time} → {model.end_time}, dt={model.time_step} {model.time_units}")
print(f"Inputs:  {model.input_var_names}")
print(f"Outputs: {model.output_var_names}")

for var in model.output_var_names:
    val = model.get_value(var)
    print(f"  {var}: {val.shape} [{model.var_units(var)}]")

model.finalize()
```
