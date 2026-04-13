# Stage 2: Model Configuration

## Purpose

Configure a PyMT model by setting parameters and generating the model
configuration file and run directory. This stage translates user intent
(e.g., "run for 1000 days with wave height 3.5 m") into the model's
native configuration format.

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| Model name | str | Yes | Name from `pymt.MODELS` |
| Parameter overrides | dict | No | Key-value pairs for non-default params |
| Run directory | str/path | No | Where to create config files (default: temp dir) |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| config_file | str | Name of generated config file (relative to config_dir) |
| config_dir | str | Absolute path to the run directory |
| Config file on disk | file | Model-specific configuration file |

## Procedure

### Step 1: Instantiate Model
```python
from pymt.models import Waves
model = Waves()
```

### Step 2: Review Available Parameters
```python
for name, default in model.parameters:
    print(f"  {name} = {default}")
```
This shows all tuneable parameters and their defaults.

### Step 3: Call setup() with Overrides
```python
# Default setup (temp directory)
cfg_file, cfg_dir = model.setup()

# Custom directory + parameters
cfg_file, cfg_dir = model.setup(
    path="/runs/experiment_01",
    incoming_wave_height=3.5,
    run_duration=1000,
)
```

### Step 4: Verify Config File
```python
import os
cfg_path = os.path.join(cfg_dir, cfg_file)
assert os.path.exists(cfg_path), f"Config not created: {cfg_path}"
print(open(cfg_path).read())
```

### Step 5: Store (cfg_file, cfg_dir) for Initialize
```python
# These are needed in Stage 3
args = (cfg_file, cfg_dir)
# Or use the shorthand:
args = model.setup(path="/runs/test")
model.initialize(*args)
```

## Verification

```python
import os
cfg_file, cfg_dir = model.setup()
assert os.path.isdir(cfg_dir), "Run directory not created"
assert os.path.isfile(os.path.join(cfg_dir, cfg_file)), "Config file missing"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| **Config path is relative** (dt_009) | Model ignores custom config, runs with defaults | Always use `model.initialize(*model.setup())` — do NOT construct paths manually |
| Misspelled parameter | `setup()` may silently ignore unknown kwargs | Check `model.parameters` for valid names |
| Run directory exists | May overwrite previous config | Use unique directory names per experiment |
| Missing template data | Config file generation fails | Check `model.datadir` exists and contains templates |
| Unit mismatch in params | Parameter in wrong units (e.g., cm vs m) | Check model docs for expected units |

## Example

```python
from pymt.models import Waves

w = Waves()

# List all parameters
print("=== Default Parameters ===")
for name, val in w.parameters:
    print(f"  {name}: {val}")

# Configure with overrides
cfg_file, cfg_dir = w.setup(
    path="./wave_test",
    incoming_wave_height=3.5,
    incoming_wave_period=10.0,
    run_duration=365,
)
print(f"\nConfig: {cfg_dir}/{cfg_file}")

# Verify
import os
assert os.path.exists(os.path.join(cfg_dir, cfg_file))
print("Configuration OK")
```
