# Stage 4: Model Execution

## Purpose

Advance the model through time by calling `update()` repeatedly. This is
the core simulation loop where forcing data can be injected via `set_value()`
and results extracted via `get_value()` at each time step.

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| Initialized model | object | Yes | Model after initialize() |
| Forcing data | numpy arrays | No | External data to inject via set_value() |
| Duration | float | No | Number of time steps or target time |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| Model state | object | Model advanced to target time |
| Output variables | numpy arrays | Values at each time step via get_value() |
| Time series | list of floats | Time stamps for each step |

## Procedure

### Step 1: Simple Run to End
```python
# Method A: go() runs entire simulation
model.go()

# Method B: manual loop with full control
while model.time < model.end_time:
    model.update()
```

### Step 2: Run with Data Capture
```python
import numpy as np

times = []
discharge = []

while model.time < model.end_time:
    model.update()
    times.append(model.time)
    val = model.get_value("channel_exit_water__volume_flow_rate")
    discharge.append(float(val.mean()))
```

### Step 3: Run with Forcing Injection
```python
# Set external forcing at each step
for i in range(1000):
    # Set wave angle from external source
    external_angle = compute_wave_angle(i)
    model.set_value("sea_surface_water_wave__azimuth_angle_of_opposite_of_phase_velocity",
                    np.array([external_angle]))
    model.update()
```

### Step 4: Run with Unit Conversion
```python
# get_value with automatic unit conversion
temp_celsius = model.get_value("temperature", units="degC")
temp_kelvin = model.get_value("temperature", units="K")
```

### Step 5: Run with Angle Convention
```python
# PyMT handles azimuth↔math conversion
angle_azimuth = model.get_value("wave_angle", angle="azimuth")  # CW from N
angle_math = model.get_value("wave_angle", angle="math")        # CCW from E
```

### Step 6: Always Finalize
```python
try:
    while model.time < model.end_time:
        model.update()
finally:
    model.finalize()
```

## Verification

```python
# Model advanced past start
assert model.time > model.start_time, "Model did not advance"
# Check a key output is non-zero
val = model.get_value(model.output_var_names[0])
assert not np.all(val == 0), "Output is all zeros — check model initialization"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| **Flat array from get_value** (ALERT 2) | Shape (N,) instead of (rows, cols) | `val.reshape(model.grid_shape(grid_id))` |
| **Time unit mismatch** (dt_006) | Model runs 365x too fast/slow | Check `model.time_units` — may be "d", "s", "yr" |
| **Angle convention** (ALERT 4) | Directions off by 90 degrees | Use `angle="azimuth"` or `angle="math"` in get_value |
| **Unit conversion error** (ALERT 1) | `gimli.units.UnitError` | Use UDUNITS-compatible strings |
| Missing finalize() | Memory leak, temp files remain | Always use try/finally |
| set_value wrong shape | ValueError or silent truncation | Match array size to `model.var_size(name)` |

## Example

```python
from pymt.models import Waves
import numpy as np

model = Waves()
model.initialize(*model.setup())

results = {"time": [], "wave_height": []}

try:
    for step in range(100):
        model.update()
        results["time"].append(float(model.time))
        wh = model.get_value("sea_surface_water_wave__height")
        results["wave_height"].append(float(wh.mean()))

    print(f"Ran {len(results['time'])} steps")
    print(f"Wave height range: {min(results['wave_height']):.2f} - {max(results['wave_height']):.2f}")
finally:
    model.finalize()
```
