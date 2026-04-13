# Stage 1: Model Discovery

## Purpose

Discover and enumerate BMI-enabled model plugins installed in the current
Python environment. This is the entry point for any PyMT workflow — you must
know which models are available before you can configure or run them.

## Inputs

| Input | Type | Description |
|-------|------|-------------|
| Python environment | env | Active virtualenv or conda environment with PyMT |
| Model plugin packages | pip/conda | e.g., `pymt_cem`, `pymt_hydrotrend`, `pymt_waves` |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| Model list | Python list | Names of available models via `pymt.MODELS` |
| Model metadata | dict per model | Input/output variable names, parameters, grid info |

## Procedure

### Step 1: Import PyMT
```python
import pymt
from pymt import MODELS
print(f"PyMT version: {pymt.__version__}")
```

### Step 2: List Available Models
```python
for name in MODELS:
    print(name)
```
If this list is empty, no model plugins are installed.

### Step 3: Install Model Plugins
```bash
# Conda (recommended)
mamba install pymt_hydrotrend pymt_cem pymt_waves -c conda-forge

# Pip (if model supports it)
pip install pymt_hydrotrend
```

### Step 4: Inspect a Model
```python
model = MODELS.Hydrotrend()
print("Input vars:", model.input_var_names)
print("Output vars:", model.output_var_names)
print("Parameters:", list(model.parameters))
```

### Step 5: Verify Plugin Registration
```python
# Check entry points directly
from importlib.metadata import entry_points
eps = entry_points()
if hasattr(eps, 'select'):
    pymt_eps = list(eps.select(group='pymt.plugins'))
else:
    pymt_eps = eps.get('pymt.plugins', [])
for ep in pymt_eps:
    print(f"  {ep.name}: {ep.value}")
```

## Verification

```bash
python -c "from pymt import MODELS; assert len(list(MODELS)) > 0, 'No models found'"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| No models found | Empty MODELS list | Install model plugin packages |
| ImportError on model | Missing compiled dependency | Check model's own dependencies (C/Fortran libs) |
| Wrong Python env | Models installed in different env | Activate correct conda/venv environment |
| Entry point not registered | Package installed but model not in MODELS | Reinstall with `pip install -e .` or check setup.cfg |

## Example

```python
from pymt import MODELS

# List all models
print("Available models:", list(MODELS))

# Quick test: instantiate Hydrotrend
if hasattr(MODELS, 'Hydrotrend'):
    ht = MODELS.Hydrotrend()
    print(f"Hydrotrend outputs: {ht.output_var_names}")
    print(f"Time step: {ht.time_step} {ht.time_units}")
```
