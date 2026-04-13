# S5 — Output Analysis & Visualization

## Purpose

Parse inversion results, export the recovered model to portable formats (CSV),
compute data-fit metrics, and generate diagnostic visualizations for quality
control and presentation.

## Inputs

| Input              | Format           | Units              | Required |
|--------------------|------------------|--------------------|----------|
| Recovered model    | .npy (n_active,) | model space        | Yes      |
| Predicted data     | .npy (nD,)       | data units         | Yes      |
| Observed data      | CSV or .npy      | data units         | For QC   |
| Mesh config        | JSON             | from S1            | Yes      |
| Model config       | JSON             | from S2            | For units|
| Convergence log    | JSON             | from S6            | For QC   |

## Outputs

| Output                 | Format    | Contents                          |
|------------------------|-----------|-----------------------------------|
| recovered_model.csv    | CSV       | x, y, z, model_value, phys_value |
| data_comparison.csv    | CSV       | observed, predicted, residual     |
| convergence.png        | PNG       | Φ_d vs iteration                  |
| model_slice.png        | PNG       | Horizontal slice through model    |
| data_comparison.png    | PNG       | Observed vs predicted scatter     |
| model_histogram.png    | PNG       | Distribution of recovered values  |

## Procedure

### Step 1: Transform Model to Physical Property Space

The recovered model `m` is in model space (e.g., log-conductivity).
Transform to physical property:

```python
# For log map
sigma = np.exp(m_recovered)

# For reciprocal map
rho = 1.0 / m_recovered

# For identity
prop = m_recovered
```

### Step 2: Export to CSV

```python
# Cell centers from mesh
cell_centers = mesh.cell_centers  # (n_cells, 3) array

# Only active cells
cc_active = cell_centers[active]
model_active = m_recovered

# Save
np.savetxt("recovered.csv",
    np.column_stack([cc_active, model_active, np.exp(model_active)]),
    delimiter=",",
    header="x,y,z,model_value,conductivity_Sm",
    comments=""
)
```

### Step 3: Compute Data-Fit Metrics

| Metric    | Formula                                        | Ideal    |
|-----------|------------------------------------------------|----------|
| R²        | 1 - Σ(d-dpred)² / Σ(d-d̄)²                   | → 1.0    |
| RMSE      | √(mean((d-dpred)²))                           | → 0      |
| NRMSE     | RMSE / (d_max - d_min)                         | < 0.1    |
| PBIAS     | 100 × Σ(d-dpred) / Σ|d|                       | → 0%     |
| Φ_d / nD  | normalized data misfit                         | ≈ 1.0    |

```python
residual = dobs - dpred
r2 = 1 - np.sum(residual**2) / np.sum((dobs - dobs.mean())**2)
rmse = np.sqrt(np.mean(residual**2))
```

### Step 4: Generate Plots

**Convergence curve** — verify the inversion converged:
```python
fig, ax = plt.subplots()
ax.semilogy(iterations, phi_d_history, 'b-o')
ax.axhline(n_data, color='r', linestyle='--', label='Target')
ax.set_xlabel('Iteration'); ax.set_ylabel('Φ_d')
```

**Model slice** — visualize recovered structure:
```python
mesh.plot_slice(sigma, normal='Y', ind=ny//2,
                grid=True, clim=[sigma.min(), sigma.max()])
```

**Data comparison** — observed vs predicted scatter:
```python
ax.scatter(dobs, dpred, c='#2563EB', s=10)
ax.plot([dobs.min(), dobs.max()], [dobs.min(), dobs.max()], 'k--')
```

## Verification

- [ ] CSV has correct number of rows (= n_active)
- [ ] Physical property values are in expected range
- [ ] R² > 0.9 for well-constrained inversions
- [ ] Φ_d / nD ≈ 1 (target misfit reached)
- [ ] No NaN values in outputs
- [ ] Model structure matches expected geology qualitatively

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| Model/physical confusion | Plotting model values instead of physical property | Color scale shows log values, misleading |
| Wrong cell indexing | Active cells not aligned with mesh centers | CSV has wrong coordinates |
| Missing transform | Exporting log-sigma as sigma | Values wrong by orders of magnitude |
| Incomplete convergence | Interpreting under-converged model as final | Artifacts, poor resolution |
| Data unit mismatch | Comparing mGal observed to SI predicted | Metrics appear terrible |

## Example

```python
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Load results
m_rec = np.load("results/m_recovered.npy")
dpred = np.load("results/dpred.npy")
dobs = np.loadtxt("observed.csv", delimiter=",", skiprows=1)

# Metrics
residual = dobs - dpred
r2 = 1 - np.sum(residual**2) / np.sum((dobs - dobs.mean())**2)
rmse = np.sqrt(np.mean(residual**2))
print(f"R² = {r2:.4f}, RMSE = {rmse:.6f}")

# Observed vs predicted
fig, ax = plt.subplots(figsize=(7, 7))
ax.scatter(dobs, dpred, c='#2563EB', s=10, alpha=0.7)
lims = [min(dobs.min(), dpred.min()), max(dobs.max(), dpred.max())]
ax.plot(lims, lims, 'k--')
ax.text(0.95, 0.05, f"R² = {r2:.3f}\nRMSE = {rmse:.4f}",
        transform=ax.transAxes, ha='right', va='bottom',
        bbox=dict(facecolor='white', alpha=0.8))
ax.set_xlabel("Observed"); ax.set_ylabel("Predicted")
fig.savefig("data_comparison.png", dpi=150, bbox_inches="tight")
```
