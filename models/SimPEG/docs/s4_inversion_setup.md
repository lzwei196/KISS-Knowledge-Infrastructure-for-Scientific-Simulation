# S4 — Inversion Setup & Execution

## Purpose

Configure and run the SimPEG inversion to recover a geophysical model from
observed data.  The inversion minimizes the objective function
`Φ(m) = Φ_d(m) + β·Φ_m(m)` where Φ_d is the data misfit and Φ_m is the
regularization (model norm), balanced by trade-off parameter β.

## Inputs

| Input              | Format            | Units               | Required |
|--------------------|-------------------|----------------------|----------|
| Simulation         | SimPEG Simulation | —                    | Yes      |
| Observed data      | numpy array (nD,) | method-specific      | Yes      |
| Uncertainties      | relative + floor  | fraction + data unit | Yes      |
| Starting model     | numpy array (n,)  | model space          | Yes      |
| Mesh               | discretize Mesh   | meters               | Yes      |
| Active cells       | bool array        | —                    | Yes      |

## Outputs

| Output             | Format            | Contents                      |
|--------------------|-------------------|-------------------------------|
| Recovered model    | numpy array (n,)  | Model vector in model space   |
| Predicted data     | numpy array (nD,) | Forward response of result    |
| Convergence log    | JSON              | phi_d, phi_m per iteration    |

## Procedure

### Step 1: Create Data Object

```python
from simpeg import data as simpeg_data

data_obj = simpeg_data.Data(
    survey,
    dobs=observed_data,
    relative_error=0.05,   # 5% of |d|
    noise_floor=1e-3,      # absolute floor in data units
)
```

**Uncertainty formula**: `std = sqrt(floor^2 + (rel * |d|)^2)`

### Step 2: Data Misfit

```python
from simpeg import data_misfit
dmis = data_misfit.L2DataMisfit(data=data_obj, simulation=sim)
```

### Step 3: Regularization

```python
from simpeg import regularization

# Standard Tikhonov
reg = regularization.WeightedLeastSquares(
    mesh, active_cells=active,
    alpha_s=1e-4,    # smallness weight
    alpha_x=1.0,     # x-smoothness weight
    alpha_y=1.0,     # y-smoothness weight
    alpha_z=1.0,     # z-smoothness weight
)

# Or sparse (L0/L1) for compact bodies
reg = regularization.Sparse(
    mesh, active_cells=active,
    norms=[0, 1, 1, 1],  # [smallness, x, y, z] norms
)
```

**Tuning alpha ratios**: The ratio `alpha_s / alpha_xyz` controls the
balance between keeping the model close to the reference vs keeping it
smooth. Small `alpha_s` → smoother models; large `alpha_s` → closer
to reference.

### Step 4: Optimization

```python
from simpeg import optimization

# Unbounded
opt = optimization.InexactGaussNewton(maxIter=30, maxIterCG=30)

# Bounded (required for physical constraints)
opt = optimization.ProjectedGNCG(
    maxIter=30, maxIterCG=30,
    upper=upper_bound, lower=lower_bound,
)
```

### Step 5: Inverse Problem

```python
from simpeg import inverse_problem
inv_prob = inverse_problem.BaseInvProblem(dmis, reg, opt)
```

### Step 6: Directives

```python
from simpeg import directives

directive_list = directives.DirectiveList(
    directives.BetaEstimate_ByEig(beta0_ratio=1e0),
    directives.TargetMisfit(),
    directives.BetaSchedule(coolingFactor=5, coolingRate=1),
)
```

**Key directives**:
| Directive                  | Purpose                                      |
|----------------------------|----------------------------------------------|
| `BetaEstimate_ByEig`      | Estimate initial β from eigenvalue ratio     |
| `TargetMisfit`             | Stop when Φ_d ≈ nD (chi-squared criterion)  |
| `BetaSchedule`             | Decrease β each iteration                    |
| `UpdateIRLS`               | Iteratively reweighted least squares (sparse)|
| `UpdateSensitivityWeights` | Depth/distance weighting                     |
| `UpdatePreconditioner`     | Update BFGS preconditioner                   |
| `SaveOutputEveryIteration` | Save model at each iteration                 |

### Step 7: Run Inversion

```python
from simpeg import inversion
inv = inversion.BaseInversion(inv_prob, directiveList=directive_list)
m_recovered = inv.run(m0)
```

## Verification

- [ ] Final Φ_d ≈ nD (target misfit reached)
- [ ] Convergence curve shows monotonic decrease
- [ ] Recovered model values are within physical bounds
- [ ] Predicted data matches observed data visually
- [ ] Model structure is consistent with known geology

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| **dt_010** | noise_floor=0 → infinite weight on zero-crossing data | Overfit artifacts, non-physical model |
| **dt_013** | β too large: data misfit never reaches target | Under-fit, model stays at starting model |
| **dt_014** | β too small: immediate overfit | Noisy, non-physical model |
| **dt_015** | Wrong optimization for bounded problem | Bounds ignored, model goes non-physical |
| **dt_008** | Default alpha ratios for non-uniform cell sizes | Over-smoothing in refined regions |
| maxIter too small | Inversion stops before convergence | Under-resolved model |
| Contradictory directives | TargetMisfit + fixed BetaSchedule | Premature stop or runaway β |

## Example

```python
import numpy as np
from simpeg import (
    data, data_misfit, regularization, optimization,
    inverse_problem, inversion, directives,
)

# Assume sim, survey, model_map, active, mesh are defined (from S1-S3)

# Create data with 5% relative error + 0.001 floor
data_obj = data.Data(survey, dobs=observed, relative_error=0.05, noise_floor=0.001)

# Misfit + regularization + optimizer
dmis = data_misfit.L2DataMisfit(data=data_obj, simulation=sim)
reg = regularization.WeightedLeastSquares(mesh, active_cells=active)
opt = optimization.ProjectedGNCG(maxIter=30, upper=1.0, lower=-1.0)

# Assemble and run
inv_prob = inverse_problem.BaseInvProblem(dmis, reg, opt)
dirList = directives.DirectiveList(
    directives.BetaEstimate_ByEig(beta0_ratio=1e0),
    directives.TargetMisfit(),
)
inv = inversion.BaseInversion(inv_prob, directiveList=dirList)

m0 = np.zeros(active.sum())
m_rec = inv.run(m0)
print(f"Recovered model: min={m_rec.min():.4f}, max={m_rec.max():.4f}")
```
