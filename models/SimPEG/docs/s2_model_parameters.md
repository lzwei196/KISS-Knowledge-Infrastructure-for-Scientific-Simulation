# S2 — Model & Physical Properties

## Purpose

Define the starting model vector, parameter mappings (model space → physical
property space), and bounds for the SimPEG inversion.  Correct unit handling
and map selection at this stage prevents the most dangerous class of silent
errors — the model runs and converges, but to a physically meaningless result.

## Inputs

| Input              | Format          | Units              | Required | Notes                           |
|--------------------|-----------------|--------------------|----------|---------------------------------|
| Mesh config        | JSON            | —                  | Yes      | From S1                         |
| Property name      | string          | —                  | Yes      | density, conductivity, etc.     |
| Background value   | float           | SI or CGS          | Yes      | Depends on --unit-system        |
| Bounds             | float pair      | same as background | No       | Physical constraints            |
| Map type           | string          | —                  | Yes      | identity, log, exp, reciprocal  |
| Reference model    | .npy array      | model space        | No       | Drives inversion toward geology |

## Outputs

| Output              | Format    | Contents                                |
|----------------------|-----------|-----------------------------------------|
| model_config.json    | JSON      | Map chain, bounds, background, metadata |
| m0.npy               | numpy     | Starting model vector (n_active,)       |

## Procedure

1. **Choose physical property and units**.  SimPEG uses SI internally:
   | Property       | SI Unit      | Common Input  | Conversion             |
   |----------------|-------------|---------------|------------------------|
   | Density         | kg/m^3      | g/cm^3 (CGS)  | × 1000                 |
   | Susceptibility  | SI (dimless)| CGS (dimless)  | × 4π ≈ 12.566         |
   | Conductivity    | S/m         | mS/m           | × 0.001                |
   | Resistivity     | Ω·m         | Ω·m            | 1.0 (identity)         |
   | Chargeability   | V/V         | mV/V           | × 0.001                |

2. **Select parameter mapping**.  The map transforms model vector `m` to
   physical property `p`:
   - `IdentityMap`: `p = m` — use when property is well-behaved (density)
   - `ExpMap`: `p = exp(m)` — log-parameterization keeps p > 0 (conductivity)
   - `ReciprocalMap`: `p = 1/m` — invert for resistivity from conductivity model
   - `LogMap`: `p = log(m)` — rarely used, property in log-space

3. **Set background and bounds in model space**:
   ```python
   # For log-conductivity: background σ = 1e-3 S/m
   m0_val = np.log(1e-3)  # = -6.9
   bounds = [np.log(1e-6), np.log(10)]  # model-space bounds
   ```

4. **Handle air/inactive cells**.  The `InjectActiveCells` map needs a value
   for inactive (air) cells:
   ```python
   # TRAP dt_009: Using 0 for conductivity → singular matrix
   air_val = np.log(1e-8)  # small but nonzero in model space
   inject_map = maps.InjectActiveCells(mesh, active, air_val)
   ```

5. **Chain maps** (right to left application):
   ```python
   model_map = maps.ExpMap(nP=n_active) * maps.InjectActiveCells(mesh, active, air_val)
   # m → inject into mesh → exp → physical σ
   ```

6. **Attach to simulation**:
   ```python
   sim.sigmaMap = model_map
   # or sim.rhoMap, sim.chiMap depending on method
   ```

## Verification

- [ ] Background value is in correct units (SI after conversion)
- [ ] Map output is positive for properties that must be positive (σ, χ)
- [ ] Air cell value doesn't cause singular systems
- [ ] Bounds are in model space, not physical property space
- [ ] Reference model has same length as n_active

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| **dt_001** | Density in g/cm^3 not converted to kg/m^3 | Gravity anomaly off by factor 1000 |
| **dt_002** | Susceptibility in CGS not converted to SI | Magnetic anomaly off by factor 4π |
| **dt_003** | Using resistivity where conductivity expected | Model is reciprocal of truth |
| **dt_009** | Air conductivity = 0 in InjectActiveCells | Solver encounters singular matrix, crashes or NaN |
| **dt_008** | Bounds in physical space, not model space | Optimizer hits wrong limits, model distorted |
| Mixed units | Background in SI but bounds in CGS | Silent constraint violation |

## Example

```python
import numpy as np
from simpeg import maps

n_active = 50000
mesh_n_cells = 80000

# Log-conductivity model with active cell injection
air_val = np.log(1e-8)
inject = maps.InjectActiveCells(mesh, active_cells, air_val)
exp_map = maps.ExpMap(nP=n_active)
model_map = exp_map * inject

# Starting model: σ = 1e-3 S/m → m = ln(1e-3) = -6.9
m0 = np.log(1e-3) * np.ones(n_active)

# Bounds in model (log) space
lower = np.log(1e-6) * np.ones(n_active)
upper = np.log(10.0) * np.ones(n_active)

# Verify forward pass
sigma = model_map * m0
print(f"σ range: {sigma.min():.2e} – {sigma.max():.2e} S/m")
assert sigma.min() > 0, "Conductivity must be positive"
```
