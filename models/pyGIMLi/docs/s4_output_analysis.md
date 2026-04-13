# s4: Output Analysis — Result Extraction, QC, and Export

## Purpose

Parse pyGIMLi inversion results, compute quality metrics, export to portable
formats (CSV, VTK), and generate diagnostic plots. This stage provides the
quantitative basis for interpreting geophysical models.

## Inputs

| Input                | Format           | Unit          | Source            |
|----------------------|------------------|---------------|-------------------|
| Model array          | `.npy`           | Ω·m or s/m    | s3 output         |
| Mesh                 | `.bms`           | m             | s3 output         |
| Response array       | `.npy`           | Ω·m or s      | s3 output         |
| Result metadata      | JSON             | —             | s3 output         |
| Observed data        | DataContainer    | varies        | s0 output         |

## Outputs

| Output               | Format           | Unit          | Destination       |
|----------------------|------------------|---------------|-------------------|
| Model cells CSV      | `.csv`           | m + Ω·m/m/s   | GIS / analysis    |
| Data fit CSV         | `.csv`           | varies        | QC                |
| Metrics JSON         | `.json`          | —             | Documentation     |
| Model figure         | `.png`           | —             | Publication       |
| Histogram            | `.png`           | —             | QC                |

## Procedure

### Step 1: Load results
```python
import numpy as np
import pygimli as pg

model = np.load("results/model.npy")
mesh = pg.load("results/mesh.bms")
response = np.load("results/response.npy")
```

### Step 2: Compute data-fit metrics
```python
# Load observed data
from pygimli.physics import ert
data = ert.load("survey.ohm")
observed = np.array(data['rhoa'])
errors = np.array(data['err'])

# Compute metrics
residuals = observed - response
abs_rms = np.sqrt(np.mean(residuals**2))
rel_rms = np.sqrt(np.mean((residuals / observed)**2))
chi2 = np.mean((residuals / (observed * errors))**2)
r = np.corrcoef(observed, response)[0, 1]

print(f"Absolute RMS: {abs_rms:.4f}")
print(f"Relative RMS: {rel_rms:.4f}")
print(f"Chi²: {chi2:.3f}")
print(f"Correlation: {r:.4f}")
```

### Step 3: Model statistics
```python
print(f"Model range: {model.min():.1f} – {model.max():.1f} Ohm·m")
print(f"Mean: {model.mean():.1f} Ohm·m")
print(f"Median: {np.median(model):.1f} Ohm·m")
print(f"Geometric mean: {np.exp(np.mean(np.log(model))):.1f} Ohm·m")
```

### Step 4: Coverage / sensitivity analysis
```python
# Get Jacobian and compute coverage
J = mgr.fop.jacobian()
coverage = np.array(pg.math.sumCols(J))  # cumulative sensitivity
coverage /= coverage.max()  # normalize to 0–1

# Mask low-coverage cells
threshold = 0.1
reliable = coverage > threshold
print(f"Cells with coverage > {threshold}: {reliable.sum()}/{len(coverage)}")
```

### Step 5: Export to CSV
```python
# Using KI tool
# python ki/tools/parse_gimli_output.py --results-dir results/ --method ert --output analysis/

# Or manually
import csv
with open("analysis/model_cells.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["cell_id", "x", "z", "resistivity_ohm_m", "coverage"])
    for i, cell in enumerate(mesh.cells()):
        c = cell.center()
        writer.writerow([i, f"{c.x():.3f}", f"{c.y():.3f}",
                         f"{model[i]:.2f}", f"{coverage[i]:.4f}"])
```

### Step 6: Generate publication figures
```python
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 1, figsize=(12, 8))

# Model section
ax1, cbar1 = pg.show(mesh, model, ax=axes[0], label="Resistivity (Ω·m)",
                       cMap="Spectral_r", logScale=True, coverage=coverage)
axes[0].set_title("ERT Inversion Result")
axes[0].set_xlabel("Distance (m)")
axes[0].set_ylabel("Depth (m)")

# Data fit
axes[1].scatter(observed, response, c='black', s=10, alpha=0.5)
axes[1].plot([observed.min(), observed.max()],
             [observed.min(), observed.max()], 'r--')
axes[1].set_xlabel("Observed ρₐ (Ω·m)")
axes[1].set_ylabel("Predicted ρₐ (Ω·m)")
axes[1].set_title(f"Data Fit (R² = {r**2:.3f}, χ² = {chi2:.2f})")
axes[1].set_xscale('log')
axes[1].set_yscale('log')

plt.tight_layout()
plt.savefig("analysis/result_figure.png", dpi=150)
```

### Step 7: Export VTK for 3D
```python
# Add model as cell data
mesh.addData("resistivity", model)
mesh.addData("coverage", coverage)
mesh.exportVTK("analysis/result.vtk")
# Open in ParaView for 3D visualization
```

## Verification

1. **χ² ≈ 1.0**: neither over- nor under-fitting
2. **R² > 0.95**: strong correlation between observed and predicted
3. **Relative RMS < 5%**: data well reproduced
4. **Model range**: physically plausible for site geology
5. **No systematic residuals**: random scatter, not structured patterns
6. **Coverage > 10%**: for cells used in interpretation

## Traps

| Trap | Symptom | Cause | Fix |
|------|---------|-------|-----|
| dt_001 | Resistivity range 1000× off | Unit confusion in data | Check data conversion step |
| dt_007 | Artifacts at edges | Boundary cells included | Mask by coverage threshold |
| dt_009 | Systematic misfit pattern | Wrong error model | Review error estimation |
| dt_015 | Model too smooth | High lambda or low error | Reduce lambda, check error |

## Example

```bash
# Full analysis pipeline
python ki/tools/parse_gimli_output.py \
    --results-dir results/ \
    --method ert \
    --output analysis/ \
    --coverage-threshold 0.1

# View metrics
cat analysis/metrics.json
```

## Metrics Reference

| Metric | Good | Acceptable | Poor | Meaning |
|--------|------|------------|------|---------|
| χ²     | 0.8–1.2 | 0.5–2.0 | >5 or <0.3 | Data fit vs. noise |
| R²     | >0.98 | >0.90 | <0.80 | Correlation |
| Rel. RMS | <3% | <10% | >20% | Relative misfit |
| Coverage | >50% cells >0.1 | >30% | <20% | Model reliability |
