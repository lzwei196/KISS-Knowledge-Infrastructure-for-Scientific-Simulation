# s3: Forward Modelling and Inversion — Running pyGIMLi

## Purpose

Execute forward modelling (compute synthetic data from a known model) or
inversion (recover model parameters from measured data). This is the core
computational stage of the pyGIMLi workflow.

## Inputs

| Input                | Format           | Unit          | Source            |
|----------------------|------------------|---------------|-------------------|
| DataContainer        | `.ohm` / `.sgt`  | Ω·m or s      | s0 output         |
| Mesh                 | `.bms` / Mesh    | m             | s1 output         |
| Region config        | JSON             | method-dep.   | s2 output         |
| Error estimates      | array in data    | fraction 0–1  | s0 or manual      |

## Outputs

| Output               | Format           | Unit          | Destination       |
|----------------------|------------------|---------------|-------------------|
| Model array          | `.npy`           | Ω·m or s/m    | s4 analysis       |
| Response array       | `.npy`           | Ω·m or s      | s4 analysis       |
| Mesh with model      | `.bms` / `.vtk`  | m             | Visualization     |
| Chi² history         | JSON             | dimensionless | QC                |
| Result summary       | JSON             | —             | Documentation     |

## Procedure

### Step 1: Forward Modelling (Synthetic Data)
```python
import pygimli as pg
from pygimli.physics import ert

# Create measurement scheme
scheme = ert.createData(nElecs=41, schemeName='wa')  # Wenner-alpha

# Create mesh and assign model
mesh = pg.meshtools.createParaMesh2DGrid(scheme.sensors())

# Simulate with noise
data = ert.simulate(mesh, res=100.0, scheme=scheme,
                    noiseLevel=0.03, noiseAbs=5e-5)

# Save synthetic data
data.save("synthetic.ohm")
```

### Step 2: Inversion (ERT)
```python
from pygimli.physics import ert

# Load field data
data = ert.load("field_survey.ohm")

# Create manager
mgr = ert.ERTManager(data)

# Run inversion
model = mgr.invert(
    lam=20,           # regularization strength
    maxIter=10,       # max iterations
    verbose=True,     # print progress
    zWeight=0.7,      # vertical smoothing weight
    robustData=False, # L2 norm (default)
)

# Access results
chi2 = mgr.inv.chi2()       # final chi-squared
response = mgr.inv.response  # predicted data
mesh = mgr.paraDomain        # inversion mesh

print(f"Chi² = {chi2:.3f}, iterations = {mgr.inv.iter}")
```

### Step 3: Inversion (SRT)
```python
from pygimli.physics import traveltime as tt

data = tt.load("picks.sgt")
mgr = tt.TravelTimeManager(data)

# SRT inversion (inverts for slowness)
model = mgr.invert(lam=50, maxIter=15, verbose=True)

# Model is slowness (s/m) — convert to velocity
import numpy as np
velocity = 1.0 / np.array(model)
```

### Step 4: Monitor convergence

The inversion should converge to χ² ≈ 1.0:
- **χ² >> 1**: underfitting (model too smooth, or errors too small)
- **χ² << 1**: overfitting (fitting noise, or errors too large)
- **χ² oscillates**: instability — reduce lambda more slowly

```python
# Convergence is printed during verbose=True:
# Iteration 1: chi² = 15.2, lambda = 20.0
# Iteration 2: chi² = 3.4,  lambda = 10.0
# Iteration 3: chi² = 1.5,  lambda = 5.0
# Iteration 4: chi² = 1.1,  lambda = 2.5
# Iteration 5: chi² = 1.02, lambda = 1.25
```

### Step 5: Visualize results
```python
# Show inverted model
mgr.showResult()

# Or with more control
ax, cbar = pg.show(mgr.paraDomain, model, label="Resistivity (Ω·m)",
                    cMap="Spectral_r", logScale=True)

# Show data fit
mgr.showFit()
```

### Step 6: Save results
```python
import numpy as np

# Save model
np.save("model.npy", model)

# Save mesh
mgr.paraDomain.save("mesh.bms")

# Export VTK for 3D visualization
mgr.paraDomain.exportVTK("result.vtk")
```

## Verification

1. **χ² ≈ 1.0**: data fit matches noise level
2. **Monotonic decrease**: chi² should decrease each iteration
3. **Model range**: physically plausible (ERT: 1–100000 Ω·m; SRT: 100–6500 m/s)
4. **No artifacts**: checkerboard patterns near electrodes = singularity removal issue
5. **Smooth transitions**: unless using blocky regularization
6. **Coverage**: check sensitivity — low-coverage cells are unreliable

## Traps

| Trap | Symptom | Cause | Fix |
|------|---------|-------|-----|
| dt_016 | χ² stuck >> 1 | Lambda too high or wrong transform | Reduce lambda, check transforms |
| dt_017 | Inversion diverges (NaN) | Error = 0 or negative data | Check error estimation, remove bad data |
| dt_018 | Electrode artifacts | Singularity removal off | Set `sr=True` in ERTManager |
| dt_014 | Over-smoothed | Lambda too high | Start at lam=20, reduce to 1–5 |
| dt_015 | Noisy/rough model | Lambda too low | Increase lambda or use robustData |

## Example

```bash
# Using KI execution wrapper
python ki/tools/run_pygimli.py \
    --data survey.ohm \
    --method ert \
    --mode invert \
    --lam 20 \
    --max-iter 10 \
    --z-weight 0.7 \
    --relative-error 0.03 \
    --output results/

# Check results
cat results/result.json
```

## Algorithm Details

### Gauss-Newton Inversion
The inversion solves iteratively:
```
(J^T W_d J + λ W_m) Δm = J^T W_d (d_obs - d_pred) - λ W_m (m - m_ref)
```
Where:
- **J**: Jacobian (sensitivity matrix)
- **W_d**: Data weighting matrix (from error estimates)
- **W_m**: Model regularization matrix (smoothness/roughness)
- **λ**: Regularization parameter (trade-off)
- **Δm**: Model update
- **m_ref**: Reference model

Lambda is reduced automatically when χ² decreases, following a cooling schedule.
