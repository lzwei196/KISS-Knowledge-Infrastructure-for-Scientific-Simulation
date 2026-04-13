# S5: Model Execution

## Purpose

Run the assembled SuperflexPy model with prepared forcing data and parameters.
This stage sets the timestep, feeds input arrays, solves the ODEs through the
element hierarchy, and collects output streamflow and state time series.

## Inputs

| Input | Format | Units | Notes |
|-------|--------|-------|-------|
| Model object | SuperflexPy Unit/Node/Network | — | From Stage 3 |
| P array | numpy.ndarray | mm/d | Precipitation |
| PET array | numpy.ndarray | mm/d | Potential ET |
| Timestep | float | days | Must match forcing resolution |
| Parameters | dict (optional) | varies | Override values |

## Outputs

| Output | Format | Units | Description |
|--------|--------|-------|-------------|
| Q_sim | list[numpy.ndarray] | mm/d | Simulated streamflow |
| States | dict | mm | Final state values |
| State arrays | numpy.ndarray | mm | Time series of states |

## Procedure

### Step 1: Set timestep

```python
model.set_timestep(1.0)  # days
```

**CRITICAL**: The timestep must match the temporal resolution of the forcing data.
If forcing is hourly, use `dt = 1.0/24.0`. The ODE solver uses this value directly
in the finite difference approximation.

### Step 2: Set input

```python
# For GR4J (InterceptionFilter expects [PET, P]):
model.set_input([PET, P])

# For HBV (UnsaturatedReservoir expects [P, PET]):
model.set_input([P, PET])
```

**CRITICAL**: Input order depends on the first element in the model. Check the
element's `set_input()` docstring. Getting this wrong is a **silent error** (dt_005).

### Step 3: Run model

```python
Q = model.get_output()  # Returns list of numpy arrays
```

This cascades through all layers:
1. First layer receives the raw input
2. Each subsequent layer gets output from the previous layer
3. Parallel elements in the same layer are solved independently
4. The ODE solver iterates through timesteps

### Step 4: Collect results

```python
Q_sim = Q[0]  # First (usually only) output flux
print(f"Mean Q: {Q_sim.mean():.3f} mm/d")
print(f"Total Q: {Q_sim.sum():.1f} mm")

# Get final states
states = model.get_states()

# Reset for next run
model.reset_states()
```

### Batch execution for calibration

```python
def run_model(params_dict):
    model.reset_states()
    model.set_parameters(params_dict)
    model.set_timestep(1.0)
    model.set_input([PET, P])
    Q = model.get_output()
    return Q[0]
```

```bash
python ki/tools/run_superflexpy.py \
    --model gr4j \
    --forcing forcing.json \
    --solver implicit_euler \
    --params x1=300 x3=50 x4=2.0 \
    --output results.json
```

## Verification

- [ ] Output length equals input length
- [ ] No NaN values in output
- [ ] No negative streamflow values
- [ ] Runoff ratio (total Q / total P) is 0.1–0.9 for most catchments
- [ ] Water balance: P - ET - Q ≈ ΔS over long periods

## Traps

| Trap ID | Description | Impact |
|---------|-------------|--------|
| dt_003 | Timestep doesn't match forcing | Silent error in ODE |
| dt_005 | Input array order swapped | Silent nonsense results |
| dt_009 | Numba first-call delay | Appears to hang for 5-30s |
| dt_010 | Explicit solver produces negative storage | Numerical instability |
| dt_015 | Root finder non-convergence | Degraded accuracy |

## Example

```python
import numpy as np
from superflexpy.implementation.models.gr4j import model

# Synthetic forcing
P = np.random.exponential(5.0, 365)  # mm/d
PET = np.random.uniform(0, 5, 365)   # mm/d

model.set_timestep(1.0)
model.set_input([PET, P])
Q = model.get_output()

print(f"Simulated {len(Q[0])} timesteps")
print(f"Mean Q = {Q[0].mean():.2f} mm/d")
print(f"Runoff ratio = {Q[0].sum()/P.sum():.3f}")
```
