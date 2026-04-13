# S5: Model Execution

## Purpose

Run HydroCNHS to simulate daily streamflow at routing outlets. The model
takes a YAML config and climate data dictionaries, runs rainfall-runoff
computations for all subbasins, routes flow through the network, executes
any ABM agents, and returns daily discharge time series.

## Inputs

| Input | Format | Unit | Source |
|-------|--------|------|--------|
| model.yaml | YAML file | — | S3 output |
| temp | Python dict | °C | S1 output |
| prec | Python dict | cm/day | S1 output |
| pet (optional) | Python dict | cm/day | S1 output or auto-calculated |

## Outputs

| Output | Format | Unit | Access |
|--------|--------|------|--------|
| Q_routed | dict of arrays | cms (m³/s) | `model.dc.Q_routed` |
| Q_runoff | dict of arrays | cms | `model.dc.Q_runoff` |
| temp, prec, pet | dict of arrays | °C, cm/day | `model.dc.temp/prec/pet` |
| ABM outputs | custom fields | varies | `model.dc.<field_name>` |

## Procedure

### Direct Simulation

```python
import hydrocnhs
import pickle

# Load climate data
with open("climate_inputs.pickle", "rb") as f:
    climate = pickle.load(f)

# Initialize model
model = hydrocnhs.Model(model="model.yaml")

# Run simulation
Q = model.run(
    temp=climate["temp"],   # {outlet: [daily °C]}
    prec=climate["prec"],   # {outlet: [daily cm/day]}
    pet=climate.get("pet")  # optional, auto-calculated if None
)

# Access results
for outlet in model.dc.Q_routed:
    q = model.dc.Q_routed[outlet]
    print(f"{outlet}: mean Q = {sum(q)/len(q):.2f} cms")
```

### Using the execution wrapper

```bash
python run_hydrocnhs.py \
    --mode simulate \
    --model model.yaml \
    --climate-pickle climate_inputs.pickle \
    --output results.json
```

### Running with ABM

If the model includes ABM agents, ensure:
1. The ABM module file (e.g., `TRB_ABM.py`) is in the modules directory
2. The `Path.Modules` field in model.yaml points to the correct directory
3. Agent priorities are set correctly (lower number = higher priority)
4. Decision-making classes match those defined in the module

```python
# ABM agents execute automatically during model.run()
# Their outputs are collected in model.dc
model = hydrocnhs.Model("model_with_abm.yaml")
Q = model.run(temp=temp, prec=prec)

# Access agent-specific outputs (if defined in ABM module)
# e.g., model.dc.ResAgt_release, model.dc.DivAgt_diversion
```

## Verification

After running, verify outputs are physically plausible:

```python
import numpy as np

for outlet in model.dc.Q_routed:
    q = np.array(model.dc.Q_routed[outlet])
    print(f"{outlet}:")
    print(f"  Mean Q: {q.mean():.2f} cms")
    print(f"  Max Q:  {q.max():.2f} cms")
    print(f"  Min Q:  {q.min():.4f} cms")

    # Sanity checks
    assert not np.any(np.isnan(q)), "NaN values in discharge!"
    assert not np.any(q < 0), "Negative discharge!"

    # Check magnitude (basin-dependent)
    # For TRB (area ~200,000 ha): mean Q should be 10-50 cms
    # If Q is 10× too high: precipitation likely in mm not cm
    # If Q is 100× too low: area likely in km² not ha
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt_001: prec in mm/day | Q 10× too high | Convert to cm/day |
| dt_005: area in km² | Q 100× too low | Convert to ha |
| dt_014: -99 sentinel params | Runtime error or NaN | Set real values or calibrate |
| dt_015: ABM module not found | ImportError at runtime | Check Path.Modules |
| dt_016: Agent priority conflict | Wrong execution order | Set unique priorities |

## Example

Complete execution workflow for TRB:

```python
import hydrocnhs
import pickle
import numpy as np

# Load calibrated model and inputs
with open("TRB_inputs.pickle", "rb") as f:
    inputs = pickle.load(f)

model = hydrocnhs.Model("Calibrated_TRB_GWLF.yaml")
Q = model.run(temp=inputs["temp"], prec=inputs["prec"])

# Daily streamflow at basin outlet
q_wslo = np.array(model.dc.Q_routed["WSLO"])
print(f"WSLO: {q_wslo.mean():.2f} ± {q_wslo.std():.2f} cms")
print(f"  Max: {q_wslo.max():.2f} cms on day {q_wslo.argmax()}")
print(f"  Total volume: {q_wslo.sum() * 86400 / 1e6:.1f} million m³")
```
