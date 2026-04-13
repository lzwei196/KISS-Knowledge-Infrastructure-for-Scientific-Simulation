# s5: Joint Inversion — Multi-Method Structurally-Coupled Inversion

## Purpose

Combine multiple geophysical datasets (e.g., ERT + SRT) in a single inversion
to improve subsurface model resolution. Joint inversion exploits the fact that
different geophysical properties often share structural boundaries (e.g., a
clay layer has both low resistivity and low velocity).

## Inputs

| Input                | Format           | Unit          | Source            |
|----------------------|------------------|---------------|-------------------|
| ERT DataContainer    | `.ohm`           | Ω·m           | s0 output         |
| SRT DataContainer    | `.sgt`           | s             | s0 output         |
| Common mesh          | `.bms` / Mesh    | m             | s1 output         |
| Coupling constraints | JSON / config    | —             | User design       |

## Outputs

| Output               | Format           | Unit          | Destination       |
|----------------------|------------------|---------------|-------------------|
| Resistivity model    | NumPy array      | Ω·m           | Interpretation    |
| Velocity model       | NumPy array      | m/s           | Interpretation    |
| Joint mesh           | `.bms` / `.vtk`  | m             | Visualization     |
| Cross-gradient map   | NumPy array      | dimensionless | QC                |

## Procedure

### Step 1: Prepare compatible datasets
Both datasets must share the same mesh or have compatible parameterizations.

```python
import pygimli as pg
from pygimli.physics import ert
from pygimli.physics import traveltime as tt

# Load both datasets
ert_data = ert.load("ert_survey.ohm")
srt_data = tt.load("srt_picks.sgt")

# Create a common mesh that includes all sensor positions
all_sensors = []
for s in ert_data.sensors():
    all_sensors.append([s.x(), s.y()])
for s in srt_data.sensors():
    all_sensors.append([s.x(), s.y()])
```

### Step 2: Structurally-coupled joint inversion

pyGIMLi supports joint inversion through the `JointModelling` framework:

```python
from pygimli.frameworks import JointModelling

# Create individual forward operators
ert_fop = ert.ERTModelling()
srt_fop = tt.TravelTimeDijkstraModelling()

# Create joint forward operator
joint_fop = JointModelling([ert_fop, srt_fop])

# Set up joint inversion with cross-gradient coupling
from pygimli.frameworks import JointInversion
inv = JointInversion(joint_fop)
inv.setLambda(20)
inv.setCrossGradientWeight(1.0)  # coupling strength

# Run
model = inv.run([ert_data, srt_data])
```

### Step 3: Alternative — sequential cooperative inversion
If full joint inversion is complex, use sequential approach:

```python
# Step A: Invert ERT first
ert_mgr = ert.ERTManager(ert_data)
res_model = ert_mgr.invert(lam=20)

# Step B: Use ERT structure to constrain SRT
srt_mgr = tt.TravelTimeManager(srt_data)
# Apply structural constraint from ERT gradients
# srt_mgr.fop.setConstraints(ert_gradients)
vel_model = srt_mgr.invert(lam=50)
```

### Step 4: Petrophysical joint inversion
Convert both properties to a common petrophysical parameter:

```python
# Archie's law: resistivity = a * rho_w * porosity^(-m) * S_w^(-n)
# Wyllie's equation: velocity = 1 / (porosity/v_fluid + (1-porosity)/v_matrix)

# Invert for porosity using both ERT and SRT constraints
# This requires custom forward operators that implement the
# petrophysical relationships
```

### Step 5: Cross-gradient analysis
```python
# Compute cross-gradient between resistivity and velocity models
import numpy as np

# Gradients of each model on the mesh
grad_res = mesh_gradient(res_model)  # (n_cells, 2)
grad_vel = mesh_gradient(vel_model)  # (n_cells, 2)

# Cross-gradient (should be ~0 at structural boundaries)
cross_grad = grad_res[:, 0] * grad_vel[:, 1] - grad_res[:, 1] * grad_vel[:, 0]
```

## Verification

1. **Both models converge**: χ² ≈ 1.0 for each dataset independently
2. **Structural consistency**: boundaries align between resistivity and velocity
3. **Cross-gradient minimum**: near zero at structural boundaries
4. **Physical consistency**: low resistivity + low velocity = clay (not artifact)
5. **Improvement over independent**: joint should produce sharper boundaries

## Traps

| Trap | Symptom | Cause | Fix |
|------|---------|-------|-----|
| dt_001 | One method dominates | Imbalanced data weights | Normalize by dataset size |
| dt_002 | Mesh incompatibility | Different meshes | Use common mesh for both |
| dt_003 | Cross-gradient too strong | Over-coupling | Reduce coupling weight |
| dt_004 | Non-physical correlation | Artifacts, not geology | Check data quality first |
| dt_005 | Divergence | Conflicting constraints | Start with weaker coupling |

## Example

```python
import pygimli as pg
from pygimli.physics import ert
from pygimli.physics import traveltime as tt

# Load datasets
ert_data = ert.load("ert_survey.ohm")
srt_data = tt.load("srt_picks.sgt")

# Independent inversions for comparison
ert_mgr = ert.ERTManager(ert_data)
res_ind = ert_mgr.invert(lam=20, verbose=True)

srt_mgr = tt.TravelTimeManager(srt_data)
vel_ind = srt_mgr.invert(lam=50, verbose=True)

# Compare structural boundaries
fig, axes = plt.subplots(2, 1, figsize=(12, 8))
pg.show(ert_mgr.paraDomain, res_ind, ax=axes[0],
        label="Resistivity (Ω·m)", cMap="Spectral_r", logScale=True)
pg.show(srt_mgr.paraDomain, 1.0/vel_ind, ax=axes[1],
        label="Velocity (m/s)", cMap="plasma")
plt.savefig("joint_comparison.png", dpi=150)
```

## When to Use Joint Inversion

| Scenario | Benefit | Risk |
|----------|---------|------|
| ERT + SRT with same profile | High — structural coupling improves both | Low |
| ERT + IP (same instrument) | High — same electrodes, consistent geometry | Low |
| ERT + gravity | Moderate — different scales, different depth sensitivity | Medium |
| Surface + borehole | High — complementary coverage | Medium (mesh complexity) |
| Different survey dates | Low — subsurface may have changed | High |
