# Stage 6: Model Coupling

## Purpose

Connect two or more BMI models so that output variables from one model
feed as input to another. This is PyMT's core capability — coupling
models across different time/space scales with automatic data exchange.

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| Source model | PyMT model | Yes | Model providing output data |
| Target model | PyMT model | Yes | Model consuming input data |
| Variable mapping | dict | Yes | {source_var: target_var} |
| Mapper | Mapper object | No | Spatial regridding (if grids differ) |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| Coupled simulation | results | Both models advanced in sync |
| Exchanged data log | list | Values transferred at each step |

## Procedure

### Step 1: Initialize Both Models
```python
from pymt.models import Waves, Cem

waves = Waves()
cem = Cem()

waves.initialize(*waves.setup())
cem.initialize(*cem.setup())
```

### Step 2: Find Matching Variables
```python
# Variables with matching CSDMS Standard Names
src_out = set(waves.output_var_names)
tgt_in = set(cem.input_var_names)
matches = src_out & tgt_in
print(f"Auto-matchable variables: {matches}")
```

### Step 3: Basic Coupling Loop
```python
for t in range(1000):
    # Update source
    waves.update()

    # Transfer data
    for var in matches:
        values = waves.get_value(var)
        cem.set_value(var, values)

    # Update target
    cem.update()
```

### Step 4: Coupling with Spatial Mapping
```python
from pymt.mappers.pointtopoint import NearestVal

# When grids differ, use a mapper
mapper = NearestVal()
mapper.initialize(
    waves.grid_x(0), waves.grid_y(0),  # source grid
    cem.grid_x(0), cem.grid_y(0),       # target grid
)

for t in range(1000):
    waves.update()

    src_val = waves.get_value(var)
    tgt_val = mapper.run(src_val)
    cem.set_value(var, tgt_val)

    cem.update()
```

### Step 5: Handle Different Time Steps
```python
# If models have different dt, update the faster one more often
src_dt = waves.time_step  # e.g., 1 hour
tgt_dt = cem.time_step    # e.g., 1 day
ratio = int(tgt_dt / src_dt)

for day in range(365):
    for sub_step in range(ratio):
        waves.update()
    values = waves.get_value(var)
    cem.set_value(var, values)
    cem.update()
```

### Step 6: Finalize Both
```python
try:
    # coupling loop ...
    pass
finally:
    waves.finalize()
    cem.finalize()
```

## Verification

```python
# After coupling, both models should have advanced
assert waves.time > waves.start_time
assert cem.time > cem.start_time
# Target model output should differ from uncoupled run
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| **Standard Name mismatch** (dt_010) | No data exchanged, target uses defaults | Check exact strings in `input_var_names` / `output_var_names` |
| **Azimuth vs math angle** (dt_002) | Wave direction off by 90 degrees | Use `get_value(var, angle="azimuth")` |
| **Different time units** (dt_006) | Models desynchronize | Check `time_units` and convert |
| **Grid size mismatch** | ValueError on set_value | Use mapper to regrid, or check `var_size()` |
| **Missing ESMF** | Conservative mapping unavailable | Install `esmpy` for ESMF mappers |
| One model crashes | Other model not finalized | Always use try/finally for both |
| Variable not in input_var_names | set_value silently ignored | Verify var is an input variable |

## Example

```python
from pymt.models import Waves, Cem

# Initialize both
waves = Waves()
cem = Cem()
waves.initialize(*waves.setup())
cem.initialize(*cem.setup())

# Find connections
connections = set(waves.output_var_names) & set(cem.input_var_names)
print(f"Coupling variables: {connections}")

# Run coupled
try:
    for t in range(100):
        waves.update()
        for var in connections:
            data = waves.get_value(var)
            cem.set_value(var, data)
        cem.update()

    print(f"Waves final time: {waves.time}")
    print(f"CEM final time: {cem.time}")
finally:
    waves.finalize()
    cem.finalize()
```
